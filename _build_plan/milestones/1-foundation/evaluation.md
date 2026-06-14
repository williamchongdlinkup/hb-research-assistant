# Milestone 1 — Foundation: Evaluation Report

**Evaluated:** 2026-06-14  
**Commit reviewed:** `9e3b800` — "Milestone 1: FastAPI + SQLite FTS5 corpus search + Railway config"  
**Evaluator:** Claude Code (Sonnet 4.6)

---

## §1 Requirements Compliance

| PRD Requirement | Status | Notes |
|---|---|---|
| FastAPI project with CSV → SQLite FTS5 ingestion on startup | ✅ Met | Builds in-memory DB via `lifespan`; loads in <2s |
| Keyword search endpoint returning ranked results | ✅ Met | FTS5 BM25 ranking via `rank` column |
| Result cards: title, first author, year, publication type, abstract excerpt | ✅ Met | All fields rendered; `author_display` assembled server-side |
| Year range filter | ✅ Met | `year_from` / `year_to` query params; SQL `WHERE e.year >= ?` |
| Publication type filter | ✅ Met | `type` query param; populated from `/api/types` |
| Expandable entry detail — full abstract on click, source URL in new tab | ✅ Met | Chevron toggle; `target="_blank" rel="noopener noreferrer"` |
| Result count display ("Showing X of N entries") | ✅ Met | Context-aware: shows corpus total when unfiltered, match count when filtered |
| Deployed live to Railway with working public URL | ✅ Met | https://hb-research-assistant-production.up.railway.app/ — verified 2026-06-14 |

**Compliance score: 7/7 functional specs met. 1 deployment prerequisite outstanding.**

---

## §2 "Done When" Criterion

> *A researcher can visit the live Railway URL, type "compassion" in the search bar, and see a filtered list of relevant corpus entries with abstracts, all within 1 second.*

| Condition | Status |
|---|---|
| "compassion" returns relevant results | ✅ 185 results locally at ~49ms |
| Results include abstracts | ✅ Abstract excerpt + expandable full text |
| Within 1 second | ✅ 49ms — 20× faster than target |
| Via live Railway URL | ⚠️ Railway not yet set up — not verifiable |

The performance target is met with substantial margin. All conditions fully verified on 2026-06-14: live URL confirmed at https://hb-research-assistant-production.up.railway.app/, "compassion" returns 185 results. Note: `runtime.txt` was updated from `python-3.11.9` to `python-3.12.9` to resolve a Railway/mise GitHub attestation verification failure (mise 2026.6.1 requires attestations; 3.11.9 predates the attestation system).

---

## §3 Code Quality

### Backend — `main.py` (277 lines)

**Strengths:**

- **`lifespan` context manager** is the correct FastAPI pattern for startup/shutdown resources. The database connection is built once and held for the process lifetime — no per-request reconnection overhead.
- **`_entry_to_dict()` helper** cleanly separates row serialisation from endpoint logic and is well-positioned for reuse in Milestone 2's Gemini integration.
- **`check_same_thread=False`** is correct for FastAPI's async environment; the connection is read-only after startup, so thread-safety is not a concern in M1.
- **UTF-8 BOM handling** via `encoding="utf-8-sig"` is correct and prevents the `﻿sNo` header corruption that would otherwise occur.
- **Year `0` → NULL** is a pragmatic data-cleaning decision that correctly excludes placeholder values from the year range display.

**Issues:**

- **Dead import:** `from fastapi.staticfiles import StaticFiles` (line 9) is imported and never used. Remove when next editing `main.py`.
- **`_db` as a bare module global:** This is acceptable for the current read-only M1 scope. Before M2 introduces any write path (e.g. session logging), this should be explicitly documented as read-only or replaced with a dependency-injected connection factory.
- **FTS5 phrase-lock (medium):** The search wraps all queries in double-quotes: `f'"{safe_q}"'`. This forces FTS5 into phrase-search mode — `"compassion mindfulness"` finds only entries where those words appear adjacently, not entries that discuss both topics independently. A researcher searching "social action" will miss entries indexed as "social engagement" or "collective action." Consider switching to token-level OR matching (`compassion OR mindfulness`) or individual prefix tokens for multi-word queries. See §4 for further detail.
- **`where_clause` string duplication:** The `replace('AND ', 'AND ', 1)` pattern in the no-query branch is fragile and unnecessary — the `AND` prefix logic is already handled by the `where_clause` variable. Minor refactor opportunity.

### Frontend — `index.html` (363 lines)

**Strengths:**

- **Parallel API initialisation:** `Promise.all([loadStats(), loadTypes()])` before the first search is correct — both calls are independent and should not be serialised.
- **350ms debounce + Enter shortcut:** Appropriate balance between search-as-you-type responsiveness and API call volume.
- **Smart pagination with ellipsis:** The `pageRange()` algorithm handles edge cases (total ≤ 7, current near start/end) correctly.
- **XSS prevention:** `escHtml()` is applied consistently to all data-derived strings inserted into the DOM. `innerHTML` is used for structured card rendering, not `textContent`, but all interpolated values are escaped — correct approach.
- **Empty state design:** Clear illustration + actionable suggestion ("Try different keywords or broaden the year range") is good UX.
- **Type colour map:** `TYPE_COLORS` provides semantic visual differentiation for common publication types; unknown types fall back gracefully to grey.

**Issues:**

- **No fetch error handling (medium):** `doSearch()`, `loadStats()`, and `loadTypes()` do not handle HTTP errors or network failures. If the server returns a 500 or the network is unavailable, `await r.json()` will throw and the UI will silently freeze in the loading state with no feedback. At minimum, a try/catch with a visible error message should be added before M2 introduces more API calls.
- **`escAttr` is an alias for `escHtml`:** This means a URL containing `&` is rendered as `&amp;` in the `href` attribute. Browsers handle `&amp;` in URLs correctly, but the function name implies URL-safe encoding, which `escHtml` does not provide. This is a naming correctness issue, not a functional bug.
- **Year filter input constraints hardcoded:** `min="1990" max="2030"` is hardcoded in HTML. The actual corpus year range is fetched dynamically from `/api/stats` but is never applied to update the `<input min>` and `<input max>` attributes. Low-priority; address in M4.
- **`toggleCard()` class management:** The `card-expanded` class is toggled on the article element in CSS but `toggleCard()` never applies it — it manually toggles `hidden` and the excerpt instead. The `.card-expanded .abstract-excerpt` CSS rule in `<style>` is therefore unreachable dead CSS.

---

## §4 Security Assessment

| Surface | Finding | Severity | Status |
|---|---|---|---|
| Search input → FTS5 query | Parameterised throughout; `"` escaped to `""` before wrapping | — | ✅ Safe |
| Year / type filter inputs | Parameterised SQL; FastAPI validates `int` types at the boundary | — | ✅ Safe |
| Corpus data → HTML render | `escHtml()` applied to all fields before DOM insertion | — | ✅ Safe |
| Corpus URL → `href` attribute | `escAttr()` = HTML-escaping only; a `javascript:` URL would not be blocked | Low | ⚠️ Flag for M4 |
| FTS5 phrase injection | Wrapping in `"..."` limits FTS5 operator injection; `OperationalError` caught and falls back to LIKE | — | ✅ Adequate |

**URL injection detail:** The corpus is a curated academic dataset maintained by NTI — the practical risk of a `javascript:` URL appearing in the corpus is very low. However, the correct defensive fix is a one-line validation before rendering the link:

```js
const safeUrl = /^https?:\/\//i.test(e.url) ? e.url : null;
```

Apply in `renderCard()` for M4 polish.

**FTS5 phrase-lock as a UX security note:** Forcing phrase-search mode limits the damage of adversarial FTS5 operator injection (e.g. a user typing `* OR *` to dump all records), since the entire query is treated as a literal phrase. However, this is not a principled security boundary — it is a side-effect of the phrase-search choice. If switching to token-level queries in a future milestone, FTS5 operator injection must be addressed explicitly.

---

## §5 Performance

| Metric | Result | Target | Assessment |
|---|---|---|---|
| Startup / CSV ingest | <2s for 1,833 rows | No explicit target | Acceptable for Railway cold start |
| FTS5 "compassion" query | ~49ms | <1,000ms | ✅ 20× faster than target |
| In-memory DB size | 2.5MB CSV → SQLite in RAM | — | Negligible on any Railway instance |
| Per-request DB overhead | Zero reconnection cost | — | ✅ |

**Railway free-tier cold start:** Railway's free tier may spin down an idle instance. The first request after a sleep will incur the ~2s CSV rebuild on top of the network round-trip. For the symposium demo, the app should be warmed by navigating to it once before any live demonstration begins. This is a known characteristic of the chosen deployment tier, not a code defect.

**Pagination:** Default page size is 20 results. The largest plausible result set is the full 1,833-entry corpus (no filters, empty query). SQLite will scan the full table but return only 20 rows — acceptable. No indexing beyond FTS5 is needed for M1's read pattern.

---

## §6 Data Quality Findings

These are observations about the source corpus, not defects in the code. They are flagged here because they affect what researchers see.

| Finding | Impact | Recommended action |
|---|---|---|
| Actual corpus is 1,833 rows, not ~1,969 as estimated in PRD | PRD references are stale | Update PRD corpus-size references; use dynamic count from DB in all UI copy |
| 12 entries have Year = "0" stored as NULL | Excluded from year range display; still searchable | Flag to corpus maintainer for correction |
| 30 distinct publication type strings, many inconsistent (e.g. "Conference Paper" vs "ConferencePaper", "Master's Dissertation" vs variants) | Type filter dropdown shows all 30 raw values; confusing to users | Requires a data-normalisation decision from corpus maintainer; address in M4 or a dedicated data-cleaning pass |
| Some entries have no abstract | These entries will never surface in FTS5 searches for body text; title-only match via FTS5 still works | No code change needed; worth communicating to corpus maintainer |

---

## §7 Technical Debt Register

Items identified during this review that are not blocking M1 sign-off but should be tracked for resolution:

| # | Item | File | Severity | Target milestone |
|---|---|---|---|---|
| TD-01 | Remove dead `StaticFiles` import | `main.py:9` | Low | M2 (next time `main.py` is edited) |
| TD-02 | Add fetch error handling to frontend | `index.html:141,121,129` | Medium | M2 (before adding more API calls) |
| TD-03 | FTS5 phrase-lock — switch to token-level search for multi-word queries | `main.py:230` | Medium | M2 or M3 (before demo) |
| TD-04 | URL `javascript:` prefix guard in `renderCard()` | `index.html:269` | Low | M4 polish |
| TD-05 | Apply API year range to `<input min/max>` constraints | `index.html:71-77` | Low | M4 polish |
| TD-06 | Remove dead `.card-expanded` CSS rule | `index.html:10` | Low | M4 polish |
| TD-07 | Publication type normalisation in corpus | Data / `main.py` ingest | Medium | M4 or data-cleaning pass |
| TD-08 | Document `_db` read-only constraint before M2 write paths | `main.py:15` | Medium | M2 start |

---

## §8 Deployment Readiness

| Artefact | Status | Notes |
|---|---|---|
| `Procfile` | ✅ Correct | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| `runtime.txt` | ✅ Correct | `python-3.11.9` — Railway Nixpacks-compatible |
| `requirements.txt` | ✅ Correct | Pinned versions: `fastapi==0.136.3`, `uvicorn[standard]==0.49.0` |
| Secrets management | ✅ Correct | `.env` in `.gitignore`; no secrets committed |
| Railway account / project | ⚠️ Not yet created | Instructions provided in `milestone-log.md` |
| Live public URL | ⚠️ Pending Railway setup | Required for PRD "Done when" to be fully met |

**Recommendation:** Complete Railway setup as the first task of the M2 session, before writing any new code. This confirms the deployment pipeline works and gives a stable test URL for all subsequent milestones.

---

## Overall Assessment

**Milestone 1 is code-complete and production-quality for its scope.** The implementation meets every functional requirement in the PRD and exceeds the performance target by 20×. The code is clean, the FTS5 architecture is solid, and the foundation is well-suited for M2's Gemini integration.

The single outstanding item — Railway deployment — is a setup task, not a code defect. It should be resolved before M2 begins.

The technical debt items are minor and appropriately deferred. None of them block M2 development. TD-02 (fetch error handling) and TD-03 (FTS5 phrase-lock) are the highest-priority items to address in M2 while those files are open.

**Milestone 1 verdict: APPROVED. All requirements met. Live at https://hb-research-assistant-production.up.railway.app/**
