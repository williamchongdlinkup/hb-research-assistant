import csv
import json
import logging
import sqlite3
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger("hb_research_assistant")

CSV_PATH = Path(__file__).parent / "data" / "HBBiblio_Dec2025_Complete.csv"
ABSTRACT_EXCERPT_LEN = 250
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"

_gemini_client: genai.Client | None = None
if GEMINI_API_KEY:
    _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

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


@app.get("/api/stats")
def stats():
    row = _db.execute(
        "SELECT COUNT(*) as total, MIN(year) as year_min, MAX(year) as year_max FROM entries WHERE year IS NOT NULL"
    ).fetchone()
    total_all = _db.execute("SELECT COUNT(*) as cnt FROM entries").fetchone()["cnt"]
    return {"total": total_all, "year_min": row["year_min"], "year_max": row["year_max"]}


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
        # Escape FTS5 special characters to avoid query syntax errors
        safe_q = q.replace('"', '""')
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
        match_params = [f'"{safe_q}"'] + params
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
    if not _gemini_client:
        return JSONResponse(status_code=503, content={"error": "AI service not configured."})

    entries = _retrieve_for_query(req.message)
    sources_count = len(entries)

    system_prompt = _build_system_prompt(entries)

    gemini_history = [
        genai_types.Content(role=m.role, parts=[genai_types.Part(text=m.content)])
        for m in req.history
    ]
    try:
        chat_session = _gemini_client.chats.create(
            model=GEMINI_MODEL,
            config=genai_types.GenerateContentConfig(system_instruction=system_prompt),
            history=gemini_history,
        )
        response = chat_session.send_message(req.message)
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


def _fts_rows(text: str, limit: int):
    """Token-level OR retrieval over title+abstract, ranked by BM25, with a
    LIKE fallback. Returns raw sqlite rows."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    seen_terms: set[str] = set()
    terms: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS or lw in seen_terms:
            continue
        seen_terms.add(lw)
        terms.append(w)
    terms = terms[:120]  # cap query size
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


def _retrieve_audit_pool(chunks: list[str], limit: int = 80, per_chunk: int = 6) -> list[dict]:
    """Build a deduped candidate pool combining:
    (1) targeted per-citation retrieval — each parsed citation gets its own FTS
        query so its best matches are guaranteed present even when the title is
        short/generic and would be crowded out of a single combined ranking; and
    (2) a global topic pool over all citations, filling remaining slots with
        topically-related entries (for missing/suggested).
    `chunks` are parsed citation strings (preferred) or raw lines as a fallback —
    so retrieval is robust even to pastes with no line breaks."""
    pool: list[dict] = []
    seen_rowids: set[int] = set()

    def _add(rows):
        for r in rows:
            d = _entry_to_dict(r)
            rid = d.get("rowid")
            if rid in seen_rowids:
                continue
            seen_rowids.add(rid)
            pool.append(d)

    # (1) Per-citation targeted retrieval.
    for c in chunks[:40]:  # cap citations processed
        if len(c.strip()) >= 8:
            _add(_fts_rows(c, per_chunk))

    # (2) Global topic pool fills any remaining slots.
    if len(pool) < limit:
        _add(_fts_rows(" ".join(chunks), limit))

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
        resp = _gemini_client.models.generate_content(
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
    if not _gemini_client:
        return JSONResponse(status_code=503, content={"error": "AI service not configured."})

    bib = (req.bibliography or "").strip()
    if not bib:
        return {"verified": [], "not_in_corpus": [], "missing": [], "suggested": [], "pool_size": 0}

    # Parse first so retrieval and classification work on clean citations even
    # when the paste has UI noise or no line breaks.
    parsed = _parse_citations(bib)
    chunks = parsed if parsed else [ln.strip() for ln in bib.splitlines() if ln.strip()]
    entries = _retrieve_audit_pool(chunks, limit=80)
    pool_text = _format_audit_pool(entries)
    clean_bib = "\n".join(f"- {c}" for c in parsed) if parsed else bib
    user_content = (
        f"HB corpus entries ({len(entries)}):\n\n{pool_text}\n\n"
        f"--- Pasted bibliography to audit ---\n\n{clean_bib}"
    )

    try:
        response = _gemini_client.models.generate_content(
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
