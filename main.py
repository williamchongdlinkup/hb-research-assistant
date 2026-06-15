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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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


@app.get("/api/search")
def search(
    q: str = Query(default=""),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    params: list = []
    conditions: list[str] = []

    if year_from is not None:
        conditions.append("e.year >= ?")
        params.append(year_from)
    if year_to is not None:
        conditions.append("e.year <= ?")
        params.append(year_to)
    if type:
        conditions.append("e.type = ?")
        params.append(type)

    where_clause = ("AND " + " AND ".join(conditions)) if conditions else ""

    if q.strip():
        # Tokenise on whitespace and AND the terms together (each term quoted so
        # FTS5 special characters can't break the query). This matches entries
        # that contain ALL terms anywhere, rather than only the exact adjacent
        # phrase — so "environment ecology" or "gender women" return results
        # instead of zero. A single whitespace-free token (incl. a CJK string)
        # collapses to one quoted term, preserving prior behaviour.
        terms = [t.replace('"', '""') for t in q.split() if t.strip()]
        fts_match = " ".join(f'"{t}"' for t in terms) if terms else f'"{q.strip()}"'
        count_sql = f"""
            SELECT COUNT(*) as cnt
            FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ?
            {where_clause}
        """
        data_sql = f"""
            SELECT e.*, rank
            FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ?
            {where_clause}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """
        match_params = [fts_match] + params
    else:
        count_sql = f"""
            SELECT COUNT(*) as cnt
            FROM entries e
            WHERE 1=1
            {where_clause.replace('AND ', 'AND ', 1) if conditions else ''}
        """
        data_sql = f"""
            SELECT e.*
            FROM entries e
            WHERE 1=1
            {where_clause.replace('AND ', 'AND ', 1) if conditions else ''}
            ORDER BY e.year DESC, e.title
            LIMIT ? OFFSET ?
        """
        match_params = params[:]

    try:
        total = _db.execute(count_sql, match_params).fetchone()["cnt"]
        offset = (page - 1) * per_page
        rows = _db.execute(data_sql, match_params + [per_page, offset]).fetchall()
    except sqlite3.OperationalError:
        # Fall back to simple LIKE search if FTS syntax fails
        like_q = f"%{q}%"
        like_conditions = list(conditions) + [
            "(e.title LIKE ? OR e.abstract LIKE ?)"
        ]
        like_where = "AND " + " AND ".join(like_conditions)
        like_params = params + [like_q, like_q]
        count_sql = f"SELECT COUNT(*) as cnt FROM entries e WHERE 1=1 {like_where}"
        data_sql = f"SELECT e.* FROM entries e WHERE 1=1 {like_where} ORDER BY e.year DESC LIMIT ? OFFSET ?"
        total = _db.execute(count_sql, like_params).fetchone()["cnt"]
        offset = (page - 1) * per_page
        rows = _db.execute(data_sql, like_params + [per_page, offset]).fetchall()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [_entry_to_dict(r) for r in rows],
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
