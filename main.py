import csv
import json
import logging
import sqlite3
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger("hb_research_assistant")

CSV_PATH = Path(__file__).parent / "data" / "HBBiblio_Dec2025_Complete.csv"
STATIC_DIR = Path(__file__).parent / "static"
ABSTRACT_EXCERPT_LEN = 250
# Human-readable snapshot date for the current corpus. Surfaced via /api/stats
# so the landing page reads it live — editable in one place when the corpus is
# swapped (no template change needed).
CORPUS_LAST_UPDATED = "December 2025"
GEMINI_MODEL = "gemini-3.1-flash-lite"


def _load_api_keys() -> list[str]:
    """Collect one or more Gemini API keys from the environment so load can be
    spread across several free-tier keys (each has its own RPM/TPM/RPD quota).
    Accepts either a single `GEMINI_API_KEYS` list (comma/space/newline
    separated) or `GEMINI_API_KEY` plus numbered `GEMINI_API_KEY_2..8`.
    Order is preserved and duplicates dropped. A single key behaves exactly as
    before."""
    keys: list[str] = []
    multi = os.getenv("GEMINI_API_KEYS", "")
    if multi.strip():
        keys = [k.strip() for k in re.split(r"[,\s]+", multi) if k.strip()]
    else:
        primary = os.getenv("GEMINI_API_KEY", "").strip()
        if primary:
            keys.append(primary)
        for i in range(2, 9):
            k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if k:
                keys.append(k)
    seen: set[str] = set()
    uniq: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


_API_KEYS = _load_api_keys()
_clients: list[genai.Client] = [genai.Client(api_key=k) for k in _API_KEYS]
_client_lock = threading.Lock()
_client_idx = 0
if _clients:
    logger.info("Gemini configured with %d API key(s)", len(_clients))


def _client_order() -> list[genai.Client]:
    """Return all clients, rotated so each request starts at the next key
    (round-robin load spreading). Callers iterate the list to fail over to the
    next key when one is rate-limited/exhausted."""
    global _client_idx
    if not _clients:
        return []
    with _client_lock:
        start = _client_idx
        _client_idx = (_client_idx + 1) % len(_clients)
    return _clients[start:] + _clients[:start]


def _is_quota_error(exc: Exception) -> bool:
    """True for rate-limit / quota-exhausted / transient-overload errors that
    are worth retrying on a *different* key."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 503):
        return True
    msg = str(exc).upper()
    return any(t in msg for t in ("RESOURCE_EXHAUSTED", "RATE_LIMIT", "QUOTA", "UNAVAILABLE", "429", "503"))


def _generate_with_rotation(**kwargs):
    """Run models.generate_content, spreading load across keys and failing over
    to the next key on a quota/rate error. Raises the last error if all keys
    fail (the caller's try/except turns that into a 502)."""
    clients = _client_order()
    if not clients:
        raise RuntimeError("AI service not configured")
    last_exc: Exception | None = None
    for i, client in enumerate(clients):
        try:
            return client.models.generate_content(**kwargs)
        except Exception as exc:  # noqa: BLE001 — re-raised below
            last_exc = exc
            if _is_quota_error(exc) and i < len(clients) - 1:
                logger.warning("Gemini key %d rate-limited/exhausted; failing over", i + 1)
                continue
            raise
    raise last_exc  # pragma: no cover


def _chat_with_rotation(system_prompt: str, history: list, message: str):
    """Create a chat session and send one message, with the same round-robin +
    failover behaviour as _generate_with_rotation."""
    clients = _client_order()
    if not clients:
        raise RuntimeError("AI service not configured")
    last_exc: Exception | None = None
    for i, client in enumerate(clients):
        try:
            session = client.chats.create(
                model=GEMINI_MODEL,
                config=genai_types.GenerateContentConfig(system_instruction=system_prompt),
                history=history,
            )
            return session.send_message(message)
        except Exception as exc:  # noqa: BLE001 — re-raised below
            last_exc = exc
            if _is_quota_error(exc) and i < len(clients) - 1:
                logger.warning("Gemini key %d rate-limited/exhausted; failing over", i + 1)
                continue
            raise
    raise last_exc  # pragma: no cover

_db: sqlite3.Connection = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class AuditRequest(BaseModel):
    bibliography: str


class StructuredConcept(BaseModel):
    term: str = ""
    alts: list[str] = []


class StructuredQuery(BaseModel):
    """A smart-search interpretation the user has hand-edited in the UI (e.g.
    removed a term or a synonym). Run verbatim against the corpus — no LLM."""
    must: list[StructuredConcept] = []
    any: list[StructuredConcept] = []
    exclude: list[str] = []
    author: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    type: Optional[str] = None
    page: int = 1
    per_page: int = 20


class ExportRequest(BaseModel):
    ids: list[str] = []                 # serial_no (sNo) values, in display order
    format: str = "csv"                 # csv | ris | bibtex | rtf | txt
    style: str = "chicago"              # chicago | apa | mla  (for rtf/txt)


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE entries (
            rowid        INTEGER PRIMARY KEY,
            serial_no    TEXT,
            type         TEXT,
            author1_last TEXT,
            author1_first TEXT,
            author2_last TEXT,
            author2_first TEXT,
            author3_last TEXT,
            author3_first TEXT,
            author4_last TEXT,
            author4_first TEXT,
            editor1_last TEXT,
            editor1_first TEXT,
            editor2_last TEXT,
            editor2_first TEXT,
            editor3_last TEXT,
            editor3_first TEXT,
            title        TEXT,
            city         TEXT,
            publisher    TEXT,
            year         INTEGER,
            abstract     TEXT,
            url          TEXT,
            book_title   TEXT,
            journal      TEXT,
            volume       TEXT,
            issue        TEXT,
            page_start   TEXT,
            page_end     TEXT
        )
    """)

    # Standalone FTS table (not external-content) so we can index a derived
    # `authors` column assembled from the author/editor name fields. Indexing
    # author names is essential for reference-audit matching (a citation's
    # surname must be searchable) and improves search/chat retrieval generally.
    conn.execute("""
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            title,
            abstract,
            authors,
            tokenize='unicode61'
        )
    """)

    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for rec in reader:
            year_raw = rec.get("Year", "").strip()
            try:
                year = int(year_raw)
                if year <= 0:
                    year = None
            except ValueError:
                year = None

            url = (
                rec.get("WebpageMetadata(UpdatedJun2024)", "").strip()
                or rec.get("WebpageMetadata(PreJun2024)", "").strip()
                or ""
            )

            rows.append((
                rec.get("sNo", ""),
                rec.get("Type", ""),
                rec.get("LastName_1stAuthor", ""),
                rec.get("FirstName_1stAuthor", ""),
                rec.get("LastName_2ndAuthor", ""),
                rec.get("FirstName_2ndAuthor", ""),
                rec.get("LastName_3rdAuthor", ""),
                rec.get("FirstName_3rdAuthor", ""),
                rec.get("LastName_4thAuthor", ""),
                rec.get("FirstName_4thAuthor", ""),
                rec.get("LastName_1stEditor", ""),
                rec.get("FirstName_1stEditor", ""),
                rec.get("LastName_2ndEditor", ""),
                rec.get("FirstName_2ndEditor", ""),
                rec.get("LastName_3rdEditor", ""),
                rec.get("FirstName_3rdEditor", ""),
                rec.get("Title", ""),
                rec.get("City", ""),
                rec.get("Publisher", ""),
                year,
                rec.get("Abstract", ""),
                url,
                rec.get("Title_Book", ""),
                rec.get("Title_Journal", ""),
                rec.get("Vol_Journal", ""),
                rec.get("Issue_Journal", ""),
                rec.get("Page_Start", ""),
                rec.get("Page_End", ""),
            ))

    conn.executemany("""
        INSERT INTO entries (
            serial_no, type,
            author1_last, author1_first,
            author2_last, author2_first,
            author3_last, author3_first,
            author4_last, author4_first,
            editor1_last, editor1_first,
            editor2_last, editor2_first,
            editor3_last, editor3_first,
            title, city, publisher, year, abstract, url,
            book_title, journal, volume, issue, page_start, page_end
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)

    conn.execute("""
        INSERT INTO entries_fts (rowid, title, abstract, authors)
        SELECT rowid, title, abstract,
            trim(
                coalesce(author1_last,'')  || ' ' || coalesce(author1_first,'') || ' ' ||
                coalesce(author2_last,'')  || ' ' || coalesce(author2_first,'') || ' ' ||
                coalesce(author3_last,'')  || ' ' || coalesce(author3_first,'') || ' ' ||
                coalesce(author4_last,'')  || ' ' || coalesce(author4_first,'') || ' ' ||
                coalesce(editor1_last,'')  || ' ' || coalesce(editor1_first,'') || ' ' ||
                coalesce(editor2_last,'')  || ' ' || coalesce(editor2_first,'') || ' ' ||
                coalesce(editor3_last,'')  || ' ' || coalesce(editor3_first,'')
            )
        FROM entries
    """)

    conn.commit()
    return conn


def _entry_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    parts = []
    if d.get("author1_last"):
        name = d["author1_last"]
        if d.get("author1_first"):
            name += f", {d['author1_first']}"
        parts.append(name)
    if d.get("author2_last"):
        parts.append(d["author2_last"])
    if d.get("author3_last"):
        parts.append(d["author3_last"])
    if d.get("author4_last"):
        parts.append(d["author4_last"])
    d["author_display"] = "; ".join(parts) if parts else ""

    abstract = d.get("abstract") or ""
    d["abstract_excerpt"] = abstract[:ABSTRACT_EXCERPT_LEN] + ("…" if len(abstract) > ABSTRACT_EXCERPT_LEN else "")
    return d


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db
    _db = _build_db()
    yield


app = FastAPI(lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/favicon.ico")
def favicon():
    logo = STATIC_DIR / "nti_logo.png"
    if logo.is_file():
        return FileResponse(logo)
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/stats")
def stats():
    row = _db.execute(
        "SELECT COUNT(*) as total, MIN(year) as year_min, MAX(year) as year_max FROM entries WHERE year IS NOT NULL"
    ).fetchone()
    total_all = _db.execute("SELECT COUNT(*) as cnt FROM entries").fetchone()["cnt"]
    return {
        "total": total_all,
        "year_min": row["year_min"],
        "year_max": row["year_max"],
        "last_updated": CORPUS_LAST_UPDATED,
        # Number of configured Gemini keys (count only — never the key values).
        # Lets the deployment confirm multi-key rotation took effect without
        # reading Railway logs.
        "ai_keys": len(_clients),
    }


@app.get("/api/types")
def types():
    rows = _db.execute(
        "SELECT DISTINCT type FROM entries WHERE type != '' ORDER BY type"
    ).fetchall()
    return [r["type"] for r in rows]


# ── Search core (shared by plain /api/search and AI /api/smart-search) ────────

def _filter_conditions(year_from, year_to, type_):
    """Build the column-filter WHERE fragments common to every search path."""
    conditions: list[str] = []
    params: list = []
    if year_from is not None:
        conditions.append("e.year >= ?")
        params.append(year_from)
    if year_to is not None:
        conditions.append("e.year <= ?")
        params.append(year_to)
    if type_:
        conditions.append("e.type = ?")
        params.append(type_)
    return conditions, params


def _search_core(fts_match: str, year_from, year_to, type_, page, per_page) -> dict:
    """Run a search given an already-compiled FTS5 MATCH string (or "" for a
    filter-only browse). Raises sqlite3.OperationalError if the MATCH syntax is
    invalid — the caller decides how to fall back."""
    conditions, params = _filter_conditions(year_from, year_to, type_)
    offset = (page - 1) * per_page

    if fts_match:
        where = ("AND " + " AND ".join(conditions)) if conditions else ""
        count_sql = f"SELECT COUNT(*) as cnt FROM entries_fts f JOIN entries e ON e.rowid = f.rowid WHERE entries_fts MATCH ? {where}"
        data_sql = f"SELECT e.*, rank FROM entries_fts f JOIN entries e ON e.rowid = f.rowid WHERE entries_fts MATCH ? {where} ORDER BY rank LIMIT ? OFFSET ?"
        mp = [fts_match] + params
    else:
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        count_sql = f"SELECT COUNT(*) as cnt FROM entries e {where}"
        data_sql = f"SELECT e.* FROM entries e {where} ORDER BY e.year DESC, e.title LIMIT ? OFFSET ?"
        mp = params[:]

    total = _db.execute(count_sql, mp).fetchone()["cnt"]
    rows = _db.execute(data_sql, mp + [per_page, offset]).fetchall()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [_entry_to_dict(r) for r in rows],
    }


def _like_search(q: str, year_from, year_to, type_, page, per_page) -> dict:
    """Last-resort LIKE search used when an FTS MATCH string fails to parse."""
    conditions, params = _filter_conditions(year_from, year_to, type_)
    like_q = f"%{q}%"
    conditions.append("(e.title LIKE ? OR e.abstract LIKE ?)")
    params += [like_q, like_q]
    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * per_page
    total = _db.execute(f"SELECT COUNT(*) as cnt FROM entries e {where}", params).fetchone()["cnt"]
    rows = _db.execute(
        f"SELECT e.* FROM entries e {where} ORDER BY e.year DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [_entry_to_dict(r) for r in rows],
    }


def _plain_fts_match(q: str) -> str:
    """Tokenise on whitespace and AND the terms together (each quoted so FTS5
    special characters can't break the query). Empty/whitespace -> "" (browse)."""
    if not q or not q.strip():
        return ""
    terms = [t.replace('"', '""') for t in q.split() if t.strip()]
    return " ".join(f'"{t}"' for t in terms) if terms else f'"{q.strip()}"'


def _plain_search(q: str, year_from, year_to, type_, page, per_page) -> dict:
    """The classic keyword search: whitespace-AND FTS, with LIKE fallback."""
    try:
        return _search_core(_plain_fts_match(q), year_from, year_to, type_, page, per_page)
    except sqlite3.OperationalError:
        return _like_search(q or "", year_from, year_to, type_, page, per_page)


@app.get("/api/search")
def search(
    q: str = Query(default=""),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    return _plain_search(q, year_from, year_to, type, page, per_page)


# ── AI smart search: natural language -> structured query -> corpus ───────────

_SMART_SEARCH_PROMPT = """\
You convert a researcher's natural-language query into a STRUCTURED search over a \
Humanistic Buddhism (HB) research bibliography. The corpus is bilingual \
(English + Chinese) and each entry has a title, abstract, and author names.

Return STRICT JSON ONLY — no markdown fences, no commentary — with EXACTLY this shape:
{{
  "must":    [{{"term": "<keyword or phrase>", "alts": ["<synonym/translation>", ...]}}],
  "any":     [{{"term": "<keyword or phrase>", "alts": [...]}}],
  "exclude": ["<keyword>", ...],
  "author":  "<surname or full name>" or null,
  "year_from": <int> or null,
  "year_to":   <int> or null,
  "type": <one of the allowed types below, exactly> or null,
  "summary": "<one short plain-English restatement of the search>"
}}

Allowed "type" values (use one VERBATIM or null): {types}

Rules:
- "must" = concepts that must ALL appear (ANDed). "any" = a group where matching \
ANY one is enough; use it only when the user explicitly lists alternatives. Most \
queries use only "must".
- "alts": add high-value English synonyms, spelling variants, and ROMANIZED \
forms for HB-specific terms, people, and organisations. Examples: compassion -> \
["karuna","karuṇā"]; Fo Guang Shan -> ["Foguangshan","FGS"]; Sheng Yen -> \
["Shengyan"]; Tzu Chi -> ["Ciji"]; Humanistic Buddhism -> ["Renjian Fojiao"]. \
DO NOT output Chinese characters (Han / Japanese / Korean script) anywhere — this \
interface serves English-language users and must show only Latin-script terms. \
Only add alts you are confident about; 2–5 per concept maximum.
- Use "author" when the person is named as the WRITER ("work by Reinke"). If the \
person is the SUBJECT ("studies about Sheng Yen"), put them in "must" instead.
- Infer year filters from phrases: "after/since 2015" -> year_from 2015; "before \
2000" -> year_to 1999; "in the 1990s" -> year_from 1990, year_to 1999; "between \
2010 and 2020" -> both.
- Set "type" only if the user clearly restricts the format (books, journal \
articles, theses, chapters) AND it matches an allowed value exactly; else null.
- Put negated concepts ("not", "excluding", "without") into "exclude".
- Drop filler words. Use at most 8 must+any concepts total.

Examples:
Query: work by Reinke on Fo Guang Shan globalization after 2015, not the secular stuff
{{"must":[{{"term":"Fo Guang Shan","alts":["Foguangshan","FGS"]}},{{"term":"globalization","alts":["globalisation"]}}],"any":[],"exclude":["secular"],"author":"Reinke","year_from":2015,"year_to":null,"type":null,"summary":"Reinke on Fo Guang Shan globalization since 2015, excluding secular"}}

Query: books about compassion and social engagement
{{"must":[{{"term":"compassion","alts":["karuna","karuṇā"]}},{{"term":"social engagement","alts":["engaged Buddhism","socially engaged"]}}],"any":[],"exclude":[],"author":null,"year_from":null,"year_to":null,"type":"Book","summary":"books on compassion and social engagement"}}

Query: {query}
"""


def _norm_concept_list(value) -> list[dict]:
    """Coerce a 'must'/'any' field into [{term, alts}], accepting strings or
    objects and dropping malformed items."""
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value:
        if isinstance(item, str):
            term, alts = item.strip(), []
        elif isinstance(item, dict):
            term = str(item.get("term", "")).strip()
            alts = [str(a).strip() for a in (item.get("alts") or []) if str(a).strip()][:5]
        else:
            continue
        # English-facing UI: never surface CJK-script synonyms even if the model
        # produces them. The user's own term is left as-typed.
        alts = [a for a in alts if not _CJK_RE.search(a)]
        if term:
            out.append({"term": term, "alts": alts})
    return out[:8]


def _normalize_spec(spec: dict, allowed_types: list[str]) -> Optional[dict]:
    """Validate/clean the model's structured-query JSON. Returns None when there
    is nothing positive to search for (no terms and no author)."""
    must = _norm_concept_list(spec.get("must"))
    any_ = _norm_concept_list(spec.get("any"))
    exclude = [str(x).strip() for x in (spec.get("exclude") or []) if str(x).strip()][:8]

    author = spec.get("author")
    author = str(author).strip() if author else None

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    year_from, year_to = _int(spec.get("year_from")), _int(spec.get("year_to"))

    type_ = spec.get("type")
    type_ = str(type_).strip() if type_ else None
    if type_:
        type_ = next((t for t in allowed_types if t.lower() == type_.lower()), None)

    summary = str(spec.get("summary") or "").strip()[:200]

    if not (must or any_ or author):
        return None
    return {
        "must": must, "any": any_, "exclude": exclude, "author": author,
        "year_from": year_from, "year_to": year_to, "type": type_, "summary": summary,
    }


# Cache structured specs by query so paginating / repeating a search doesn't
# re-hit Gemini (also keeps us well under the free-tier RPM limit). Stores the
# normalized spec, or None for "the model couldn't structure this" — both are
# worth not recomputing. Simple FIFO cap; the corpus/prompt are process-stable.
_SPEC_CACHE: "dict[str, Optional[dict]]" = {}
_SPEC_CACHE_MAX = 256
_spec_cache_lock = threading.Lock()


def _structure_query(nl: str, allowed_types: list[str]) -> Optional[dict]:
    """Ask Gemini to turn a natural-language query into a structured spec.
    Returns None on any failure so the caller can fall back to plain search.
    Results are cached per query string."""
    if not _clients or not nl.strip():
        return None

    key = nl.strip().lower()
    with _spec_cache_lock:
        if key in _SPEC_CACHE:
            return _SPEC_CACHE[key]

    prompt = _SMART_SEARCH_PROMPT.format(
        types=", ".join(allowed_types) or "Book, Journal Article",
        query=nl.strip(),
    )
    try:
        resp = _generate_with_rotation(model=GEMINI_MODEL, contents=prompt)
        spec = _parse_json(resp.text)
    except Exception:  # noqa: BLE001 — any failure -> fall back to plain search
        logger.exception("smart-search structuring failed")
        return None  # not cached: a transient quota error may clear on retry

    result = _normalize_spec(spec, allowed_types) if isinstance(spec, dict) else None
    with _spec_cache_lock:
        if len(_SPEC_CACHE) >= _SPEC_CACHE_MAX:
            _SPEC_CACHE.pop(next(iter(_SPEC_CACHE)))
        _SPEC_CACHE[key] = result
    return result


def _q(term: str) -> str:
    """Quote a term as an FTS5 phrase (handles multi-word terms and specials)."""
    return '"' + term.replace('"', '""') + '"'


def _term_match(term: str) -> str:
    """FTS expression for a single topic term. A multi-word term matches either
    as an exact phrase OR as all of its words in any order — so word-order
    differences in the corpus (e.g. author names stored "Surname Firstname",
    so "Stefania Travagnin" still finds "Travagnin, Stefania") don't cause
    misses. A single word (or CJK token) is just the quoted token."""
    toks = [t for t in re.split(r"\s+", term.strip()) if t]
    if len(toks) <= 1:
        return _q(term)
    conj = "(" + " AND ".join(_q(t) for t in toks) + ")"
    return f"({_q(term)} OR {conj})"


def _compile_fts(spec: dict) -> str:
    """Compile a normalized spec into an FTS5 MATCH string."""
    clauses: list[str] = []
    for c in spec["must"]:
        group = [c["term"]] + c["alts"]
        clauses.append("(" + " OR ".join(_term_match(t) for t in group) + ")")
    if spec["any"]:
        group = []
        for c in spec["any"]:
            group.extend([c["term"]] + c["alts"])
        if group:
            clauses.append("(" + " OR ".join(_term_match(t) for t in group) + ")")
    if spec["author"]:
        toks = [t for t in re.split(r"\s+", spec["author"]) if t]
        if toks:
            clauses.append("authors : (" + " OR ".join(_q(t) for t in toks) + ")")
    positive = " AND ".join(clauses)
    if not positive:
        return ""
    if spec["exclude"]:
        neg = " OR ".join(_q(t) for t in spec["exclude"])
        return f"({positive}) NOT ({neg})"
    return positive


@app.get("/api/smart-search")
def smart_search(
    q: str = Query(default=""),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Natural-language search: structure the query with Gemini, run it against
    the corpus, and return the interpretation alongside the results. Falls back
    to plain keyword search whenever the AI step is unavailable or fails."""
    allowed_types = [
        r["type"] for r in _db.execute(
            "SELECT DISTINCT type FROM entries WHERE type != '' ORDER BY type"
        ).fetchall()
    ]
    spec = _structure_query(q, allowed_types)

    if spec is None:
        result = _plain_search(q, year_from, year_to, type, page, per_page)
        result["interpretation"] = None
        result["fallback"] = True
        return result

    # Explicit UI filters, when set, override the values the model inferred.
    eff_year_from = year_from if year_from is not None else spec["year_from"]
    eff_year_to = year_to if year_to is not None else spec["year_to"]
    eff_type = type if type else spec["type"]

    try:
        result = _search_core(_compile_fts(spec), eff_year_from, eff_year_to, eff_type, page, per_page)
    except sqlite3.OperationalError:
        logger.exception("smart-search FTS compile failed; falling back to plain")
        result = _plain_search(q, year_from, year_to, type, page, per_page)
        result["interpretation"] = None
        result["fallback"] = True
        return result

    result["interpretation"] = {
        "must": spec["must"], "any": spec["any"], "exclude": spec["exclude"],
        "author": spec["author"], "year_from": eff_year_from, "year_to": eff_year_to,
        "type": eff_type, "summary": spec["summary"],
    }
    result["fallback"] = False
    return result


@app.post("/api/structured-search")
def structured_search(req: StructuredQuery):
    """Run a user-edited interpretation directly (no LLM). Powers the removable
    chips: drop a term/synonym in the UI and re-run to see the difference."""
    page = max(1, req.page)
    per_page = min(100, max(1, req.per_page))

    allowed_types = [
        r["type"] for r in _db.execute(
            "SELECT DISTINCT type FROM entries WHERE type != '' ORDER BY type"
        ).fetchall()
    ]

    def _concepts(items):
        out = []
        for c in items[:8]:
            term = (c.term or "").strip()
            if term:
                out.append({"term": term, "alts": [a.strip() for a in (c.alts or []) if a.strip()][:5]})
        return out

    author = (req.author or "").strip() or None
    type_ = (req.type or "").strip() or None
    if type_:
        type_ = next((t for t in allowed_types if t.lower() == type_.lower()), None)

    spec = {
        "must": _concepts(req.must),
        "any": _concepts(req.any),
        "exclude": [x.strip() for x in req.exclude if x.strip()][:8],
        "author": author,
    }

    try:
        result = _search_core(_compile_fts(spec), req.year_from, req.year_to, type_, page, per_page)
    except sqlite3.OperationalError:
        logger.exception("structured-search FTS compile failed")
        return JSONResponse(status_code=400, content={"error": "Could not run this search."})

    result["interpretation"] = {
        "must": spec["must"], "any": spec["any"], "exclude": spec["exclude"],
        "author": spec["author"], "year_from": req.year_from, "year_to": req.year_to,
        "type": type_, "summary": "",
    }
    result["fallback"] = False
    return result


# ── Export selected results (citation formats, CSV, Word/RTF) ─────────────────

def _export_entries(ids: list[str]) -> list[dict]:
    """Fetch raw entry rows for the given serial numbers, preserving the order
    the user selected them in. Capped to keep exports sane."""
    ids = [str(i) for i in ids][:1000]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = _db.execute(
        f"SELECT * FROM entries WHERE serial_no IN ({placeholders})", ids
    ).fetchall()
    by_id = {str(r["serial_no"]): dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _people(e: dict, kind: str) -> list[tuple[str, str]]:
    """Extract (last, first) name pairs for authors (1–4) or editors (1–3)."""
    n = 4 if kind == "author" else 3
    out = []
    for i in range(1, n + 1):
        last = (e.get(f"{kind}{i}_last") or "").strip()
        first = (e.get(f"{kind}{i}_first") or "").strip()
        if last or first:
            out.append((last, first))
    return out


def _pages(e: dict) -> str:
    s = (e.get("page_start") or "").strip()
    t = (e.get("page_end") or "").strip()
    if s and t:
        return f"{s}–{t}"
    return s or t


# Italic markers used inside formatted citations; rendered per output format.
_I0, _I1 = "\x01", "\x02"
def _it(s: str) -> str:
    return f"{_I0}{s}{_I1}"
def _strip_markers(s: str) -> str:
    return s.replace(_I0, "").replace(_I1, "")


def _inv(last: str, first: str) -> str:      # "Last, First"
    return ", ".join(p for p in (last, first) if p)
def _plain(last: str, first: str) -> str:    # "First Last"
    return " ".join(p for p in (first, last) if p)
def _initials(first: str) -> str:
    return " ".join(f"{p[0]}." for p in re.split(r"[\s\-]+", first) if p)


def _cite_chicago(e: dict) -> str:
    people = _people(e, "author") or _people(e, "editor")
    names = [_inv(*p) if i == 0 else _plain(*p) for i, p in enumerate(people)]
    if not names:
        author = ""
    elif len(names) == 1:
        author = names[0]
    elif len(names) == 2:
        author = f"{names[0]} and {names[1]}"
    else:
        author = ", ".join(names[:-1]) + f", and {names[-1]}"
    yr = e.get("year") or "n.d."
    title = (e.get("title") or "").strip().rstrip(".")
    parts = []
    if author:
        parts.append(f"{author}.")
    parts.append(f"{yr}.")
    if e.get("journal"):
        parts.append(f"“{title}.”")
        seg = _it((e["journal"]).strip().rstrip("."))
        if (e.get("volume") or "").strip():
            seg += f" {e['volume'].strip()}"
        if (e.get("issue") or "").strip():
            seg += f", no. {e['issue'].strip()}"
        seg += f" ({yr})"
        if _pages(e):
            seg += f": {_pages(e)}"
        parts.append(seg + ".")
    elif e.get("book_title"):
        parts.append(f"“{title}.”")
        eds = _people(e, "editor")
        inb = f"In {_it(e['book_title'].strip().rstrip('.'))}"
        if eds:
            inb += ", edited by " + ", ".join(_plain(*p) for p in eds)
        if _pages(e):
            inb += f", {_pages(e)}"
        parts.append(inb + ".")
        loc = ", ".join(p for p in [(e.get("city") or "").strip(), (e.get("publisher") or "").strip()] if p)
        if loc:
            parts.append(loc + ".")
    else:
        parts.append(f"{_it(title)}.")
        if (e.get("type") or "").strip() == "Thesis":
            pub = (e.get("publisher") or "").strip()
            parts.append(f"PhD diss., {pub}." if pub else "Thesis.")
        else:
            loc = ", ".join(p for p in [(e.get("city") or "").strip(), (e.get("publisher") or "").strip()] if p)
            if loc:
                parts.append(loc + ".")
    url = (e.get("url") or "").strip()
    if url.startswith("http"):
        parts.append(url + ".")
    return " ".join(parts)


def _cite_apa(e: dict) -> str:
    people = _people(e, "author") or _people(e, "editor")
    names = [(_inv(last, _initials(first)) if (last or first) else "") for last, first in people]
    names = [n for n in names if n]
    if not names:
        author = ""
    elif len(names) == 1:
        author = names[0]
    else:
        author = ", ".join(names[:-1]) + f", & {names[-1]}"
    yr = e.get("year") or "n.d."
    title = (e.get("title") or "").strip().rstrip(".")
    parts = []
    if author:
        parts.append(author)
    parts.append(f"({yr}).")
    if e.get("journal"):
        parts.append(f"{title}.")
        seg = _it(e["journal"].strip().rstrip("."))
        if (e.get("volume") or "").strip():
            seg += f", {_it(e['volume'].strip())}"
        if (e.get("issue") or "").strip():
            seg += f"({e['issue'].strip()})"
        if _pages(e):
            seg += f", {_pages(e)}"
        parts.append(seg + ".")
    elif e.get("book_title"):
        parts.append(f"{title}.")
        eds = _people(e, "editor")
        inb = "In "
        if eds:
            inb += ", ".join(f"{_initials(f)} {l}".strip() for l, f in eds) + " (Eds.), "
        inb += _it(e["book_title"].strip().rstrip("."))
        if _pages(e):
            inb += f" (pp. {_pages(e)})"
        parts.append(inb + ".")
        if (e.get("publisher") or "").strip():
            parts.append(e["publisher"].strip() + ".")
    else:
        parts.append(f"{_it(title)}.")
        if (e.get("publisher") or "").strip():
            parts.append(e["publisher"].strip() + ".")
    url = (e.get("url") or "").strip()
    if url.startswith("http"):
        parts.append(url)
    return " ".join(parts)


def _cite_mla(e: dict) -> str:
    people = _people(e, "author") or _people(e, "editor")
    if not people:
        author = ""
    elif len(people) == 1:
        author = _inv(*people[0])
    elif len(people) == 2:
        author = f"{_inv(*people[0])}, and {_plain(*people[1])}"
    else:
        author = f"{_inv(*people[0])}, et al"
    yr = e.get("year") or ""
    title = (e.get("title") or "").strip().rstrip(".")
    parts = []
    if author:
        parts.append(f"{author}.")
    if e.get("journal"):
        parts.append(f"“{title}.”")
        seg = _it(e["journal"].strip().rstrip("."))
        if (e.get("volume") or "").strip():
            seg += f", vol. {e['volume'].strip()}"
        if (e.get("issue") or "").strip():
            seg += f", no. {e['issue'].strip()}"
        if yr:
            seg += f", {yr}"
        if _pages(e):
            seg += f", pp. {_pages(e)}"
        parts.append(seg + ".")
    elif e.get("book_title"):
        parts.append(f"“{title}.”")
        seg = _it(e["book_title"].strip().rstrip("."))
        eds = _people(e, "editor")
        if eds:
            seg += ", edited by " + ", ".join(_plain(*p) for p in eds)
        if (e.get("publisher") or "").strip():
            seg += f", {e['publisher'].strip()}"
        if yr:
            seg += f", {yr}"
        if _pages(e):
            seg += f", pp. {_pages(e)}"
        parts.append(seg + ".")
    else:
        parts.append(f"{_it(title)}.")
        tail = ", ".join(p for p in [(e.get("publisher") or "").strip(), str(yr) if yr else ""] if p)
        if tail:
            parts.append(tail + ".")
    url = (e.get("url") or "").strip()
    if url.startswith("http"):
        parts.append(url + ".")
    return " ".join(parts)


_CITERS = {"chicago": _cite_chicago, "apa": _cite_apa, "mla": _cite_mla}
_RIS_TYPE = {"Journal Article": "JOUR", "Book": "BOOK", "Book Chapter": "CHAP",
             "Conference Paper": "CPAPER", "Paper": "CPAPER", "Thesis": "THES"}
_BIB_TYPE = {"Journal Article": "article", "Book": "book", "Book Chapter": "incollection",
             "Conference Paper": "inproceedings", "Paper": "inproceedings", "Thesis": "phdthesis"}


def _export_ris(entries: list[dict]) -> str:
    out = []
    for e in entries:
        out.append(f"TY  - {_RIS_TYPE.get((e.get('type') or '').strip(), 'GEN')}")
        for l, f in _people(e, "author"):
            out.append(f"AU  - {_inv(l, f)}")
        for l, f in _people(e, "editor"):
            out.append(f"ED  - {_inv(l, f)}")
        for tag, key in [("TI", "title"), ("PY", "year"), ("JO", "journal"),
                         ("T2", "book_title"), ("VL", "volume"), ("IS", "issue"),
                         ("SP", "page_start"), ("EP", "page_end"),
                         ("PB", "publisher"), ("CY", "city"), ("AB", "abstract")]:
            val = str(e.get(key) or "").strip()
            if val:
                out.append(f"{tag}  - {val}")
        url = (e.get("url") or "").strip()
        if url.startswith("http"):
            out.append(f"UR  - {url}")
        out.append("ER  - ")
        out.append("")
    return "\r\n".join(out)


def _export_bibtex(entries: list[dict]) -> str:
    blocks = []
    for e in entries:
        bt = _BIB_TYPE.get((e.get("type") or "").strip(), "misc")
        people = _people(e, "author") or _people(e, "editor")
        keylast = re.sub(r"[^A-Za-z]", "", people[0][0]) if people and people[0][0] else "ref"
        key = f"{keylast or 'ref'}{e.get('year') or ''}_{(e.get('serial_no') or '').strip()}"
        fields = []
        au = " and ".join(_inv(l, f) for l, f in _people(e, "author"))
        if au:
            fields.append(("author", au))
        ed = " and ".join(_inv(l, f) for l, f in _people(e, "editor"))
        if ed:
            fields.append(("editor", ed))
        for name, k in [("title", "title"), ("year", "year"), ("journal", "journal"),
                        ("booktitle", "book_title"), ("volume", "volume"), ("number", "issue"),
                        ("publisher", "publisher"), ("address", "city")]:
            val = str(e.get(k) or "").strip()
            if val:
                fields.append((name, val))
        if _pages(e):
            fields.append(("pages", _pages(e).replace("–", "--")))
        url = (e.get("url") or "").strip()
        if url.startswith("http"):
            fields.append(("url", url))
        body = ",\n".join(f"  {k} = {{{str(v).replace('{', '').replace('}', '')}}}" for k, v in fields)
        blocks.append(f"@{bt}{{{key},\n{body}\n}}")
    return "\n\n".join(blocks)


def _export_csv(entries: list[dict]) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["serial_no", "type", "authors", "editors", "year", "title", "journal",
                "book_title", "volume", "issue", "pages", "publisher", "city", "url"])
    for e in entries:
        w.writerow([
            e.get("serial_no", ""), e.get("type", ""),
            "; ".join(_inv(l, f) for l, f in _people(e, "author")),
            "; ".join(_inv(l, f) for l, f in _people(e, "editor")),
            e.get("year") or "", e.get("title", ""), e.get("journal", ""),
            e.get("book_title", ""), e.get("volume", ""), e.get("issue", ""),
            _pages(e), e.get("publisher", ""), e.get("city", ""), e.get("url", ""),
        ])
    return buf.getvalue()


def _export_txt(entries: list[dict], style: str) -> str:
    cite = _CITERS.get(style, _cite_chicago)
    return "\r\n\r\n".join(_strip_markers(cite(e)) for e in entries)


def _rtf_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == _I0:
            out.append("{\\i ")
        elif ch == _I1:
            out.append("}")
        elif ord(ch) < 128:
            out.append(ch)
        else:
            code = ord(ch)
            code = code if code <= 0x7FFF else code - 0x10000
            out.append(f"\\u{code}?")
    return "".join(out)


def _export_rtf(entries: list[dict], style: str) -> str:
    cite = _CITERS.get(style, _cite_chicago)
    head = r"{\rtf1\ansi\deff0{\fonttbl{\f0 Times New Roman;}}\fs24 "
    title = ("{\\b Humanistic Buddhism Research Bibliography \\u8212? Selected References}"
             "\\par\\pard\\par ")
    body = " ".join("\\li360\\fi-360 " + _rtf_escape(cite(e)) + "\\par\\pard" for e in entries)
    return head + title + body + "}"


@app.post("/api/export")
def export(req: ExportRequest):
    entries = _export_entries(req.ids)
    if not entries:
        return JSONResponse(status_code=400, content={"error": "No entries selected."})
    fmt = (req.format or "csv").lower()
    style = (req.style or "chicago").lower()

    if fmt == "ris":
        content, media, ext, enc = _export_ris(entries), "application/x-research-info-systems", "ris", "utf-8"
    elif fmt == "bibtex":
        content, media, ext, enc = _export_bibtex(entries), "application/x-bibtex", "bib", "utf-8"
    elif fmt == "csv":
        content, media, ext, enc = _export_csv(entries), "text/csv", "csv", "utf-8-sig"
    elif fmt == "rtf":
        content, media, ext, enc = _export_rtf(entries, style), "application/rtf", "rtf", "ascii"
    elif fmt == "txt":
        content, media, ext, enc = _export_txt(entries, style), "text/plain", "txt", "utf-8"
    else:
        return JSONResponse(status_code=400, content={"error": "Unknown export format."})

    data = content.encode(enc, errors="replace")
    return Response(
        content=data,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="hb-bibliography.{ext}"'},
    )


@app.get("/api/cite")
def cite(id: str = Query(default="")):
    """Citation strings for a single entry — powers the per-record 'Cite' button.
    Returns formatted citations (copy-ready) plus RIS/BibTeX (download-ready)."""
    entries = _export_entries([id])
    if not entries:
        return JSONResponse(status_code=404, content={"error": "Entry not found."})
    e = entries[0]
    return {
        "chicago": _strip_markers(_cite_chicago(e)),
        "apa": _strip_markers(_cite_apa(e)),
        "mla": _strip_markers(_cite_mla(e)),
        "ris": _export_ris([e]),
        "bibtex": _export_bibtex([e]),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── Grounded Q&A ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a research assistant specialising in Humanistic Buddhism (HB) scholarship, \
serving researchers at Nan Tien Institute. Answer questions EXCLUSIVELY from the \
bibliography entries listed below. Do not draw on any outside knowledge.

Rules (follow strictly):
1. Write in flowing academic prose. No bullet points, numbered lists, or headers.
2. Place an inline citation [N] immediately after any factual claim, where N is \
the entry number from the list below. Multiple citations may follow one sentence: \
e.g. "...text. [2][5]"
3. Cite only entry numbers that appear in the list below.
4. If the entries do not contain enough information to answer, respond ONLY with: \
"The HB corpus does not appear to contain sufficient information to answer this question."

HB corpus entries retrieved for this query ({n} entries):

{context}\
"""


_STOPWORDS = {
    'a','an','the','and','or','but','in','on','at','to','for','of','with','by',
    'from','is','are','was','were','be','been','have','has','had','do','does',
    'did','will','would','could','should','may','might','what','which','who',
    'when','where','why','how','say','says','said','about','tell','me','us',
    'its','this','that','these','those','i','you','we','they','it','according',
    'can','please','give','get','find','show','list','explain','describe',
}


def _retrieve_for_query(query: str, limit: int = 50) -> list[dict]:
    words = re.findall(r'\b[a-zA-Z]{3,}\b', query)
    terms = [w for w in words if w.lower() not in _STOPWORDS]
    if not terms:
        return []
    # OR across all terms — BM25 ranking handles relevance ordering
    fts_query = ' OR '.join(f'"{t}"' for t in terms)
    try:
        rows = _db.execute(
            """
            SELECT e.* FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            [fts_query, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        like_params = [p for t in terms for p in (f'%{t}%', f'%{t}%')]
        conditions = ' OR '.join('(e.title LIKE ? OR e.abstract LIKE ?)' for _ in terms)
        rows = _db.execute(
            f"SELECT e.* FROM entries e WHERE {conditions} LIMIT ?",
            like_params + [limit],
        ).fetchall()
    return [_entry_to_dict(r) for r in rows]


def _build_system_prompt(entries: list[dict]) -> str:
    parts = []
    for i, e in enumerate(entries, 1):
        author = e.get("author_display") or "Unknown Author"
        year = e.get("year") or "n.d."
        title = e.get("title") or "Untitled"
        venue = e.get("journal") or e.get("book_title") or e.get("publisher") or ""
        abstract = e.get("abstract") or ""
        line = f"[{i}] {author} ({year}). {title}."
        if venue:
            line += f" {venue}."
        if abstract:
            line += f"\nAbstract: {abstract}"
        parts.append(line)
    context = "\n\n".join(parts)
    return _SYSTEM_PROMPT.format(n=len(entries), context=context)


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not _clients:
        return JSONResponse(status_code=503, content={"error": "AI service not configured."})

    entries = _retrieve_for_query(req.message)
    sources_count = len(entries)

    system_prompt = _build_system_prompt(entries)

    gemini_history = [
        genai_types.Content(role=m.role, parts=[genai_types.Part(text=m.content)])
        for m in req.history
    ]
    try:
        response = _chat_with_rotation(system_prompt, gemini_history, req.message)
        answer = response.text
    except Exception:
        logger.exception("Gemini chat generation failed")
        return JSONResponse(status_code=502, content={"error": "AI generation failed. Please try again."})

    used_nums = sorted(set(int(n) for n in re.findall(r"\[(\d+)\]", answer)))
    citations = [
        {"number": n, "entry": entries[n - 1]}
        for n in used_nums
        if 1 <= n <= len(entries)
    ]

    return {"answer": answer, "citations": citations, "sources_count": sources_count}


# ── Reference Audit ──────────────────────────────────────────────────────────

_AUDIT_SYSTEM_PROMPT = """\
You are a reference-audit assistant for the Humanistic Buddhism (HB) research \
bibliography maintained by Nan Tien Institute. You receive (A) a numbered list of \
HB corpus entries retrieved as potentially relevant, and (B) a bibliography \
pasted by a user in any citation format.

The pasted text is often MESSY — copied from a PDF, web page, or app interface. \
Before classifying, normalise it:
- Strip interface noise and citation markers, never treating them as content: \
bracketed reference numbers like "[25]", bullet/middot separators ("·"), and \
label text such as "Show abstract", "Hide abstract", and "View source" (with or \
without arrows like "↗").
- Entries may run together with no line breaks. Reconstruct each distinct work, \
keeping its title bound to its own author(s) and year even when concatenated with \
neighbouring entries. A fragment that is ONLY an author + year (no title), or \
ONLY a title (no author), is part of an adjacent entry — merge it; never emit a \
title-only or author-only fragment as its own citation.
- Identify each work by BOTH its title and its author.

Classify using ONLY the numbered corpus entries provided. Never invent entries \
and never use an index number that is not in the list.

Return STRICT JSON ONLY (no markdown fences, no commentary) with exactly this shape:
{{
  "verified":     [{{"index": <int>, "confidence": "high"|"probable", "reason": "<=15 words"}}],
  "not_in_corpus":[{{"citation": "<pasted citation trimmed to title, author, year>", "reason": "<=12 words"}}],
  "missing":      [{{"index": <int>, "reason": "<=15 words"}}],
  "suggested":    [{{"index": <int>, "reason": "<=15 words"}}]
}}

Definitions:
- verified: a pasted citation that clearly refers to one of the numbered corpus \
entries. Use "high" for a near-exact title+author match, "probable" for a likely \
but imperfect match.
- not_in_corpus: COMPLETE pasted works (title + author) that match none of the \
numbered entries. Most general or non-HB citations belong here. Never put a \
parsing fragment (author-only or title-only) here — reconstruct it into its full \
citation first.
- missing: numbered corpus entries NOT cited in the pasted list that are CENTRAL \
to the bibliography's core topic — works that a serious, well-read treatment of \
this subject would be expected to engage (foundational, highly relevant, or \
directly on-point). Include ONLY genuinely important gaps, ordered most-important \
first. Do NOT pad to reach a quota: returning few, or even none, is correct when \
there are no important omissions. Quality over quantity.
- suggested: other RELEVANT but more peripheral corpus entries — useful adjacent \
or further reading, not already counted as verified or missing. When unsure \
whether an entry is central (missing) or merely peripheral (suggested), put it in \
suggested. List as many or as few as are genuinely relevant.

Each index may appear in at most one of verified / missing / suggested. If the \
pasted text contains no parseable citations, return all four arrays empty.
"""


def _parse_json(raw: str):
    """Tolerantly parse a JSON object from a model response."""
    if not raw:
        return None
    txt = raw.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


_CJK_RE = re.compile(r"[㐀-鿿豈-﫿぀-ヿ]")


def _extract_terms(text: str) -> list[str]:
    """Extract searchable terms from arbitrary text. Unlike a bare
    [a-zA-Z]{3,} scan, this keeps Unicode letters — so accented Latin and
    Pali/Sanskrit diacritics (ü, ñ, ā, Ś) survive — and keeps short CJK runs
    (e.g. 佛教, 人間佛教), which the unicode61 FTS index stores as whole tokens.
    Without this, Chinese-language citations yield no terms and cannot be
    matched against the bilingual corpus. Latin tokens still require length ≥ 3
    to avoid noise ("et", "al", "de"); CJK runs are kept at length ≥ 2."""
    raw = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    seen_terms: set[str] = set()
    terms: list[str] = []
    for w in raw:
        is_cjk = bool(_CJK_RE.search(w))
        if not is_cjk and len(w) < 3:
            continue
        if is_cjk and len(w) < 2:
            continue
        lw = w.lower()
        if lw in _STOPWORDS or lw in seen_terms:
            continue
        seen_terms.add(lw)
        terms.append(w)
    return terms[:120]  # cap query size


def _fts_rows(text: str, limit: int):
    """Token-level OR retrieval over title+abstract+authors, ranked by BM25,
    with a LIKE fallback. Returns raw sqlite rows."""
    terms = _extract_terms(text)
    if not terms:
        return []
    fts_query = " OR ".join(f'"{t}"' for t in terms)
    try:
        return _db.execute(
            """
            SELECT e.* FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            [fts_query, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        like_params = [p for t in terms for p in (f"%{t}%", f"%{t}%")]
        conditions = " OR ".join("(e.title LIKE ? OR e.abstract LIKE ?)" for _ in terms)
        return _db.execute(
            f"SELECT e.* FROM entries e WHERE {conditions} LIMIT ?",
            like_params + [limit],
        ).fetchall()


_POOL_BASE = 40          # floor pool size (breadth for missing/suggested on tiny bibs)
_POOL_PER_CITATION = 4   # extra slots granted per cited work
_POOL_MAX = 150          # ceiling — ~15K classify tokens, well within 250K TPM
_MAX_CITATIONS = 40      # citations processed for targeted retrieval
_PER_CHUNK = 6           # targeted matches retrieved per citation


def _retrieve_audit_pool(chunks: list[str]) -> list[dict]:
    """Build a deduped candidate pool combining:
    (1) targeted per-citation retrieval — each parsed citation gets its own FTS
        query so its best matches are present even when the title is
        short/generic and would be crowded out of a single combined ranking; and
    (2) a global topic pool over all citations, filling remaining slots with
        topically-related entries (for missing/suggested).

    The pool size is **adaptive** — it grows with the number of cited works
    (``base + per_citation * n``, capped at ``_POOL_MAX``) rather than a flat 80,
    so small bibliographies stay lean (faster, less noise) while large review
    bibliographies get the room they need.

    Targeted matches are merged **round-robin by rank** (every citation's #1
    before any citation's #2, …). This guarantees each citation contributes its
    best matches regardless of its position in the list and regardless of how
    many citations there are — eliminating the earlier order bias where a flat
    cap silently dropped citations near the end of a long bibliography.

    `chunks` are parsed citation strings (preferred) or raw lines as a fallback —
    so retrieval is robust even to pastes with no line breaks."""
    eligible = [c for c in chunks[:_MAX_CITATIONS] if len(c.strip()) >= 8]
    limit = min(_POOL_MAX, _POOL_BASE + _POOL_PER_CITATION * len(eligible)) if eligible else _POOL_BASE

    pool: list[dict] = []
    seen_rowids: set[int] = set()

    def _add(d) -> bool:
        rid = d.get("rowid")
        if rid is None or rid in seen_rowids or len(pool) >= limit:
            return False
        seen_rowids.add(rid)
        pool.append(d)
        return True

    # (1) Targeted per-citation retrieval, merged round-robin by rank so every
    # citation's best matches enter before any citation's lower-ranked ones.
    per_lists = [[_entry_to_dict(r) for r in _fts_rows(c, _PER_CHUNK)] for c in eligible]
    for depth in range(_PER_CHUNK):
        if len(pool) >= limit:
            break
        for lst in per_lists:
            if depth < len(lst):
                _add(lst[depth])

    # (2) Global topic pool fills any remaining slots (candidates for
    # missing/suggested), never displacing the protected targeted matches above.
    if len(pool) < limit:
        for r in _fts_rows(" ".join(chunks), limit):
            if not _add(_entry_to_dict(r)) and len(pool) >= limit:
                break

    return pool[:limit]


def _format_audit_pool(entries: list[dict]) -> str:
    parts = []
    for i, e in enumerate(entries, 1):
        author = e.get("author_display") or "Unknown Author"
        year = e.get("year") or "n.d."
        title = e.get("title") or "Untitled"
        venue = e.get("journal") or e.get("book_title") or e.get("publisher") or ""
        excerpt = e.get("abstract_excerpt") or ""
        line = f"[{i}] {author} ({year}). {title}."
        if venue:
            line += f" {venue}."
        if excerpt:
            line += f" — {excerpt}"
        parts.append(line)
    return "\n".join(parts)


def _attach_entries(items, entries, seen, cap=None):
    """Map model-returned {index, ...} items to full corpus entries, dropping
    out-of-range or duplicate indices."""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        idx = it.get("index")
        if not isinstance(idx, int) or not (1 <= idx <= len(entries)) or idx in seen:
            continue
        seen.add(idx)
        out.append({**it, "entry": entries[idx - 1]})
        if cap and len(out) >= cap:
            break
    return out


_PARSE_SYSTEM_PROMPT = """\
You extract bibliographic references from messy pasted text — often copied from a \
PDF, web page, or app interface, frequently with NO line breaks. Return STRICT \
JSON ONLY: {{"citations": ["author(s), year, title", ...]}} — one string per \
distinct work.

Rules:
- Strip interface noise; never treat it as content: bracketed numbers like \
"[25]", middot separators "·", and labels such as "Show abstract", "Hide \
abstract", "View source", and arrows "↗".
- Keep each title bound to its own author(s) and year, even when works run \
together with no separators. Never split one work into two, nor merge two into \
one. Never emit an author-only or title-only fragment.
- Preserve original wording of titles and names; do not translate or abbreviate.
- If there are no references, return {{"citations": []}}.
"""


def _parse_citations(text: str) -> list[str]:
    """First-pass parse: turn messy pasted text into clean citation strings so
    retrieval can run per-citation regardless of input formatting."""
    try:
        resp = _generate_with_rotation(
            model=GEMINI_MODEL,
            contents=text,
            config=genai_types.GenerateContentConfig(
                system_instruction=_PARSE_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        data = _parse_json(resp.text)
    except Exception:
        logger.exception("Gemini citation parse failed")
        return []
    if not isinstance(data, dict):
        return []
    return [str(c).strip() for c in (data.get("citations") or []) if str(c).strip()]


@app.post("/api/audit")
def audit(req: AuditRequest):
    if not _clients:
        return JSONResponse(status_code=503, content={"error": "AI service not configured."})

    bib = (req.bibliography or "").strip()
    if not bib:
        return {"verified": [], "not_in_corpus": [], "missing": [], "suggested": [], "pool_size": 0}

    # Parse first so retrieval and classification work on clean citations even
    # when the paste has UI noise or no line breaks.
    parsed = _parse_citations(bib)
    chunks = parsed if parsed else [ln.strip() for ln in bib.splitlines() if ln.strip()]
    entries = _retrieve_audit_pool(chunks)
    pool_text = _format_audit_pool(entries)
    clean_bib = "\n".join(f"- {c}" for c in parsed) if parsed else bib
    user_content = (
        f"HB corpus entries ({len(entries)}):\n\n{pool_text}\n\n"
        f"--- Pasted bibliography to audit ---\n\n{clean_bib}"
    )

    try:
        response = _generate_with_rotation(
            model=GEMINI_MODEL,
            contents=user_content,
            config=genai_types.GenerateContentConfig(
                system_instruction=_AUDIT_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        data = _parse_json(response.text)
    except Exception:
        logger.exception("Gemini audit generation failed")
        return JSONResponse(status_code=502, content={"error": "AI analysis failed. Please try again."})

    if not isinstance(data, dict):
        logger.error("Audit response was not valid JSON")
        return JSONResponse(status_code=502, content={"error": "Could not parse AI response. Please try again."})

    # Counts are driven by genuine importance via the prompt; caps are only a
    # defensive backstop against a pathological response flooding the UI.
    seen: set[int] = set()
    verified = _attach_entries(data.get("verified", []), entries, seen)
    missing = _attach_entries(data.get("missing", []), entries, seen, cap=15)
    suggested = _attach_entries(data.get("suggested", []), entries, seen, cap=15)
    not_in_corpus = [
        {"citation": str(it.get("citation", "")).strip(), "reason": str(it.get("reason", "")).strip()}
        for it in (data.get("not_in_corpus") or [])
        if isinstance(it, dict) and str(it.get("citation", "")).strip()
    ]

    return {
        "verified": verified,
        "not_in_corpus": not_in_corpus,
        "missing": missing,
        "suggested": suggested,
        "pool_size": len(entries),
    }
