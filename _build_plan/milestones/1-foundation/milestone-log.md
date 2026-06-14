# Milestone 1 — Foundation: Complete

**Date completed:** 2026-06-14
**Verified against "Done when":** Searching "compassion" returns 185 relevant results with abstracts in ~49ms (target: <1 second). ✅

---

## What was built

### Files created

| File | Description |
|---|---|
| `main.py` | FastAPI backend — CSV ingestion, SQLite FTS5, search + stats + types endpoints |
| `index.html` | Single-file frontend — Tailwind CDN, Vanilla JS, full search UI |
| `requirements.txt` | `fastapi==0.136.3`, `uvicorn[standard]==0.49.0` |
| `Procfile` | `web: uvicorn main:app --host 0.0.0.0 --port $PORT` |
| `runtime.txt` | `python-3.11.9` (Railway Python version pin) |
| `data/HBBiblio_Dec2025_Complete.csv` | Corpus CSV copied into project and committed to git |
| `.gitignore` | Excludes `.env`, `__pycache__`, `.sqlite`, `.db` |

### API routes

| Route | Description |
|---|---|
| `GET /` | Serves `index.html` |
| `GET /api/stats` | `{ total, year_min, year_max }` — corpus overview |
| `GET /api/types` | List of distinct publication types for the filter dropdown |
| `GET /api/search` | Full-text search with year/type filters, pagination (20/page), BM25 ranking |

### Frontend features

- Search bar with 350ms debounce + Enter key for instant submit
- Year from/to filters + publication type dropdown
- "Showing X–Y of N entries" count
- Result cards: type badge (colour-coded), title, author, year, venue, 250-char abstract excerpt
- Expandable cards: click chevron → full abstract + "View Source" link
- Pagination with prev/next and smart page range
- "Clear all" button appears when any filter is active
- Empty state with helpful message

---

## Decisions made during implementation

**1. Actual corpus size is 1,833 (not 1,969)**
The CSV contains 1,833 rows. The PRD's "~1,969" was an estimate. The UI displays the actual count dynamically from the database.

**2. UTF-8 BOM handling**
The CSV has a UTF-8 BOM (`﻿`) at the start. Used `encoding="utf-8-sig"` in Python's CSV reader to strip it automatically.

**3. Year `0` treated as NULL**
12 entries have Year = "0" (likely data entry placeholders). These are stored as NULL and excluded from the `year_min` calculation. They still appear in search results and browse.

**4. In-memory SQLite (not on-disk)**
Rebuilt from CSV at every startup. Startup time is <2 seconds for 1,833 rows. This sidesteps Railway's ephemeral filesystem — no `.db` file to lose on redeploy.

**5. FTS5 with fallback to LIKE search**
If an FTS5 query string contains syntax Railway can't parse (e.g., unbalanced quotes), the endpoint catches `sqlite3.OperationalError` and falls back to a `LIKE` search automatically.

**6. Python 3.14 locally, 3.11 on Railway**
Python 3.14.4 is the only Python available locally (installed via Windows Store). `runtime.txt` pins `python-3.11.9` for Railway since Railway's Nixpacks builder supports 3.11 reliably. The code is compatible with both.

**7. 30 distinct publication types**
The corpus uses inconsistent type strings (e.g., "Conference Paper" vs "ConferencePaper", "Master's Dissertation" vs variations). Not normalised in M1 — this would require a data-cleaning decision from the corpus maintainer.

---

## What Milestone 2 needs to know

- **Python executable path (local dev):** `C:\Users\buddh\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- **No `.env` file needed yet** — M2 will add `GEMINI_API_KEY`. Create `.env` with that key before running M2 locally.
- **The in-memory DB is module-level global `_db`** in `main.py`. M2's Gemini code can call `_db.execute(...)` directly, or we can extract a helper function.
- **FTS5 is already set up** — M2's RAG retrieval should query `entries_fts` with `MATCH` and join to `entries` for full metadata. Limit to ~50 rows for Gemini context.
- **`_entry_to_dict(row)` helper** converts a SQLite Row to a JSON-serialisable dict with `author_display` and `abstract_excerpt`. Reuse it for any endpoint that returns entries.
- **Git is initialised** at `interactiveBibliography/`. First commit is `9e3b800`.

---

## Railway deployment instructions (for William)

Railway was not yet set up at the time of this milestone. Follow these steps once ready to deploy:

1. **Create a Railway account:** https://railway.com — sign up with GitHub for easiest integration.
2. **Install Railway CLI:**
   ```
   npm install -g @railway/cli
   ```
   (requires Node.js — install from https://nodejs.org if needed)
3. **Login:**
   ```
   railway login
   ```
4. **Create a new project and link this repo:**
   ```
   cd interactiveBibliography
   railway init
   ```
   Choose "Empty project" when prompted.
5. **Deploy:**
   ```
   railway up
   ```
   Railway will detect the `Procfile` and `requirements.txt`, install deps, and start the server.
6. **Get your public URL:**
   ```
   railway open
   ```
   Or find it in the Railway dashboard under your project → Settings → Public URL.

No environment variables are needed for Milestone 1. Milestone 2 will add `GEMINI_API_KEY` via `railway variables set GEMINI_API_KEY=...`.

---

## Deviations from PRD

| PRD spec | Actual |
|---|---|
| ~1,969 entries | 1,833 entries (actual CSV count) |
| Deployed live on Railway | Code is git-committed and ready; Railway setup pending (account not yet created) |
| `serial_no` field | Stored correctly — CSV BOM fixed with `utf-8-sig` encoding |
