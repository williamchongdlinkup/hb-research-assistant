import csv
import sqlite3
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

CSV_PATH = Path(__file__).parent / "data" / "HBBiblio_Dec2025_Complete.csv"
ABSTRACT_EXCERPT_LEN = 250

_db: sqlite3.Connection = None


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

    conn.execute("""
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            title,
            abstract,
            content=entries,
            content_rowid=rowid,
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
        INSERT INTO entries_fts (rowid, title, abstract)
        SELECT rowid, title, abstract FROM entries
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
