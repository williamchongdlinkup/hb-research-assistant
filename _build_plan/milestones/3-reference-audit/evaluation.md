# Milestone 3 — Reference Audit: Evaluation Report

**Evaluated:** 2026-06-15
**Commit reviewed:** `13ca539` — "Milestone 3: Reference Audit — paste bibliography, classify against HB corpus"
**Evaluator:** Claude Code (Opus 4.8)

---

## §1 Requirements Compliance

| PRD Requirement | Status | Notes |
|---|---|---|
| Text area to paste a bibliography in any citation format | ✅ Met | `#audit-input` textarea; parsing is AI-driven, not regex |
| "Audit" button that triggers analysis | ✅ Met | `runAudit()`; also Ctrl/⌘+Enter |
| ✅ Verified section — pasted citations matched to corpus entries, with links | ✅ Met | Matched entries with `View source ↗`; confidence badge added |
| ⚠️ Missing section — key HB papers absent, ranked by relevance | ✅ Met | Up to 5, BM25-ordered pool, model-selected with reasons |
| 💡 Suggested section — other relevant corpus entries, ranked | ✅ Met | Up to 5, deduped against verified/missing |
| Each result shows title, author, year, and a one-line reason | ✅ Met | Rendered for all entry-backed sections |
| "Copy suggestions as APA" for Missing + Suggested | ✅ Met | `copyAuditApa()` copies best-effort APA to clipboard |
| Reuse Gemini + SQLite FTS5 from M1/M2 | ✅ Met | Reuses `_gemini_client`, `GEMINI_MODEL`, FTS5; separate `_retrieve_audit_pool` helper |
| Results browser-only, nothing persisted | ✅ Met | Stateless endpoint; all state in the page |

**Compliance score: 9/9 specs met.** Plus one approved addition (4th "Not in HB corpus" section).

Explicit non-goals (saving results, batch audit, citation-error detection, outside-corpus sources) were correctly excluded.

---

## §2 "Done When" Criterion

> *A journal editor can paste a paper's bibliography, click Audit, and within 30 seconds see a three-section report identifying which citations are in the HB corpus and which key HB papers are missing.*

| Condition | Status |
|---|---|
| Paste bibliography → click Audit → report | ✅ |
| Identifies which citations are in the HB corpus | ✅ Verified section + (added) Not-in-corpus section |
| Identifies which key HB papers are missing | ✅ Missing section with reasons |
| Within 30 seconds | ✅ ~2.2s local, ~2.5s live — ~12× faster than target |
| Verified on live deployment | ✅ Production `/api/audit` returned correct 4-bucket classification (1 verified / 5 missing / 2 not-in-corpus) on 2026-06-15 |

**Done-when fully met and verified end-to-end in production.**

---

## §3 Code Quality

### Backend — `main.py` (595 lines, +134 over M2)

**Strengths:**

- **Single-call architecture respects the free tier.** A per-citation matching loop would exceed the 15 req/min free-tier limit on any real bibliography. Instead `_retrieve_audit_pool` (main.py:477) pulls one 60-entry pool from the *whole* pasted text — cited HB titles surface their own entries for matching while topic terms surface related entries for Missing/Suggested — and a single `generate_content` call does parse + classify. One API call per audit; ~2.5s observed.
- **Structured JSON output.** `response_mime_type="application/json"` (main.py:566) plus an explicit schema in the system prompt makes the model return machine-readable output. `_parse_json` (main.py:457) is defensively tolerant: strips ```` ```json ```` fences, then falls back to a `{...}` regex extract before giving up.
- **Defensive index mapping.** `_attach_entries` (main.py:525) validates each model-returned `index` is an `int` in range, drops duplicates via a shared `seen` set, and enforces single-bucket membership with verified → missing → suggested precedence — so a hallucinated or out-of-range `[N]` can never index the pool incorrectly, and the same entry can't appear twice.
- **Server-side caps as a backstop.** The ~5 limit on Missing/Suggested is enforced in code (`cap=5`), not just requested in the prompt — robust to a model that over-returns.
- **Query hygiene in retrieval.** `_retrieve_audit_pool` dedupes terms, removes stopwords, and caps at 120 terms (main.py:490) to bound FTS query size; falls back to `_retrieve_for_query` on `OperationalError`.
- **Tech-debt cleanup.** Removed the dead `StaticFiles` import (M1 TD-01) and replaced the raw-exception leak with `logger.exception(...)` + a generic client message in both `/api/chat` and `/api/audit` (M2 TD-10).

**Issues:**

- **Pool-size ceiling can cause false "not in corpus" (medium, inherent).** Matching is bounded by the 60-entry retrieval pool. If a bibliography cites an HB paper whose title ranks past position 60 in BM25, it is invisible to the model and will be classified "not in corpus." Acceptable for demo-scale bibliographies, but it is a real recall ceiling — a 60-item HB-dense reference list could exceed it. See §7 TD-13.
- **No cap on input size (low).** `bibliography` is unbounded; a very large paste inflates the prompt and latency, and the term extraction runs over the whole string. A length guard (e.g. reject > ~20k chars with a friendly message) would harden it. See §7 TD-14.
- **`temperature=0.2` but no `max_output_tokens` (low).** Output length relies on the ~5 caps in the prompt; pinning a token ceiling would make cost/latency fully predictable.
- **Verified matching trusts the model's title comparison (low).** There is no string-similarity cross-check between the pasted citation and the matched entry. The confidence flag mitigates this, but a `probable` match is only as good as the model's judgement; a future hardening is a server-side fuzzy-title check to downgrade weak matches.

### Frontend — `index.html` (871 lines, +189 over M2)

**Strengths:**

- **Consistent with proven M2 patterns.** `runAudit()` (index.html:720) mirrors `sendChat()`: try/catch, `!res.ok` handling, defensive `.json().catch(() => ({}))`, loading toggled in all paths, button re-enabled in `finally`.
- **XSS-safe throughout.** Every model- and corpus-derived field passes through `escHtml()` before insertion, including the `confidence` value and the not-in-corpus citation text.
- **`https`-only URL guard (clears M1 TD-04 for new code).** `auditItem` (index.html:818) tests `/^https?:\/\//i` before rendering `View source`, blocking a `javascript:` URL — the guard M1/M2 lacked.
- **`switchTab` cleanly generalised** from 2 hard-coded tabs to an array-driven 3-tab toggle — no duplicated branch logic.
- **Graceful empty-result handling.** If all four buckets are empty (no parseable citations), the UI shows an actionable message instead of blank sections.

**Issues:**

- **APA output is best-effort, not strict APA 7 (low, documented).** `apaFromEntry` (index.html:754) emits `Author (Year). Title. Venue, Vol(Issue), pages.` from `author_display` (`Last, First; Last2; …`). Without parsed first/middle initials per author, true APA 7 author formatting (`Last, F. M., & Last2, F.`) isn't possible from the current corpus fields. Acceptable per PRD; flagged if strict APA is wanted. See §7 TD-15.
- **Clipboard API has no non-secure-context fallback (low).** `navigator.clipboard.writeText` requires a secure context; it works on the Railway HTTPS URL and localhost, but the `.catch` only sets the button label to "Copy failed" with no manual-copy fallback. Fine for the deployed demo.
- **Confidence badge only on verified (by design).** Not an issue — noted so M4 doesn't "fix" it.

---

## §4 Security Assessment

| Surface | Finding | Severity | Status |
|---|---|---|---|
| Pasted bibliography → FTS retrieval | Tokenised, deduped, quoted, OR-joined, parameterised; `OperationalError` → fallback | — | ✅ Safe |
| Pasted bibliography → Gemini prompt | User text embedded as content; prompt-injection possible, impact bounded (public corpus, JSON-constrained output) | Low | ⚠️ Accept for demo |
| Model JSON → response mapping | Indices range-checked and de-duplicated in `_attach_entries`; bad indices dropped | — | ✅ Safe |
| Audit fields → DOM | `escHtml()` on all fields incl. `confidence` and citation text | — | ✅ Safe |
| Corpus URL → `href` | `^https?://` scheme guard before render | — | ✅ Safe (improved over M1/M2) |
| `/api/audit` error body | Generic message; detail logged server-side via `logger` | — | ✅ Safe |
| Input size | No upper bound on pasted text | Low | ⚠️ Flag (TD-14) |
| Clipboard | Secure-context API; no exfiltration risk | — | ✅ Safe |

No high-severity findings. The audit notably **improves** on M1/M2 security by adding the URL scheme guard and removing the exception leak.

---

## §5 Performance

| Metric | Result | Target | Assessment |
|---|---|---|---|
| Audit round-trip — local | ~2.2s | <30s | ✅ ~14× margin |
| Audit round-trip — live (Railway) | ~2.5s | <30s | ✅ ~12× margin |
| Gemini calls per audit | 1 | — | ✅ Free-tier safe (15 req/min) |
| FTS pool retrieval | sub-millisecond | — | ✅ Negligible |
| Pool / prompt size | 60 entries × (citation line + abstract excerpt) | — | ⚠️ Largest prompt in the app; fine for flash-lite |

Single-call design keeps both latency and rate-limit pressure low. The audit prompt is the app's largest (pool + pasted text), but well within model limits at the demo scale.

---

## §6 Data Quality Findings

No new data-layer changes — ingestion and schema are unchanged from M1. Two corpus characteristics surface specifically through the audit feature:

| Finding | Impact | Recommended action |
|---|---|---|
| Abstract-less entries are weakly retrievable | An HB paper cited in a paste may not enter the 60-pool if it has only a title and ranks low → false "not in corpus" | Corpus maintainer: prioritise abstracts; mitigated partly by raising pool size |
| `author_display` lacks parsed first/middle initials | Blocks strict APA 7 output | Data: split author given-names into initials if strict APA is required |

---

## §7 Technical Debt Register

**Carried forward:**

| # | Item | File | Severity | Status after M3 |
|---|---|---|---|---|
| TD-01 | Dead `StaticFiles` import | `main.py` | Low | ✅ Resolved |
| TD-02 | Fetch error handling on **search** path | `index.html` | Medium | ❌ Still open (chat + audit have it; `doSearch`/`loadStats`/`loadTypes` still unguarded) — M4 |
| TD-03 | FTS phrase-lock on **`/api/search`** | `main.py` | Medium | ❌ Still open (chat + audit use token retrieval; search still phrase-locks) — M4 |
| TD-04 | `javascript:` URL guard | `index.html` | Low | ⚠️ Partial — added in audit; search (`renderCard`) + chat (`renderCitationEntry`) still HTML-escape only — M4 |
| TD-05 | Year `<input min/max>` from API | `index.html` | Low | ❌ Still open — M4 |
| TD-06 | Dead `.card-expanded` CSS | `index.html` | Low | ❌ Still open — M4 |
| TD-07 | Publication-type normalisation | data | Medium | ❌ Still open — data pass |
| TD-09 | Model-name doc reconciliation | docs | Medium | ✅ Resolved (PRD, M2 log, M3/M4 prompts now say `gemini-3.1-flash-lite`) |
| TD-10 | Raw exception leak | `main.py` | Low | ✅ Resolved (chat + audit) |
| TD-11 | Multi-turn citation drift | `main.py` | Medium | ❌ Still open (M2 chat) — post-demo |
| TD-12 | Citation anchor auto-expand | `index.html` | Low | ❌ Still open (M2 chat) — M4 |

**New in M3:**

| # | Item | File | Severity | Target milestone |
|---|---|---|---|---|
| TD-13 | Audit recall bounded by 60-entry pool — HB papers ranking past 60 mislabeled "not in corpus" | `main.py` | Medium | ✅ **Resolved 2026-06-15** (commit `75ea57d`) — root cause was author names absent from FTS; fixed by indexing authors + per-citation retrieval + pool 60→80. See post-evaluation note. |
| TD-14 | No upper bound on pasted bibliography size | `main.py:545` | Low | M4 |
| TD-15 | Best-effort APA, not strict APA 7 (corpus lacks parsed initials) | `index.html:754` | Low | Post-demo / data |

---

## §8 Deployment Readiness

| Artefact | Status | Notes |
|---|---|---|
| Committed to git | ✅ | `13ca539` on `master`, pushed to `main` |
| Railway build | ✅ | `/api/audit` route live after push (~30s build) |
| `GEMINI_API_KEY` on Railway | ✅ | Already set in M2; audit reuses it |
| Dependencies | ✅ | No new deps (reuses `google-genai`); `requirements.txt` unchanged |
| Live verification | ✅ | Production audit returned correct classification 2026-06-15 |

---

## Overall Assessment

Milestone 3 meets every functional requirement (9/9) plus the approved 4th section, and the "Done when" is verified live at ~12× under the time budget. The single-call, pooled-retrieval architecture is the right call for the free tier, and the backend is defensively written — index validation, JSON-parse fallback, server-side caps, and single-bucket dedup all guard against model misbehaviour. M3 also actively reduced the project's debt (TD-01, TD-09, TD-10 resolved; TD-04 improved). The one substantive limitation is the 60-entry pool recall ceiling (TD-13), which can mislabel a cited HB paper as "not in corpus" in a reference-dense list — worth a small pool increase and/or a UI note, and worth exercising in M4's 20-query end-to-end pass. Nothing blocks M4.

**Milestone 3 verdict: APPROVED.** All requirements met, deployed, and live-verified. Recommended before/at M4: address the still-open search-path debt (TD-02/TD-03/TD-04) during the M4 polish pass.

---

## Post-evaluation update (2026-06-15) — TD-13 resolved via manual review

A manual review with the five citations from a prior M2 Q&A response exposed a concrete instance of TD-13: **Gleig, Ann (2021), "Engaged Buddhism"** — a genuine corpus entry — was classified "not in HB corpus" (4/5 verified). Investigation showed the true root cause was deeper than the pool ceiling: **the M1 FTS index covered only `title` + `abstract`, never author names**, so a citation's surname was unmatchable and a short abstract-less title was out-ranked.

Fix (commit `75ea57d`):
- Added an `authors` column to `entries_fts` (assembled from author/editor fields); switched the table from external-content to standalone. This makes author names searchable in audit, `/api/search`, and chat retrieval.
- Rebuilt `_retrieve_audit_pool` with per-citation targeted retrieval (each pasted line gets its own FTS query) unioned with the global topic pool; pool raised 60 → 80; new shared `_fts_rows` helper.

Verification: the same test now returns **5/5 verified, 0 not-in-corpus** (confirmed live); `/api/search "compassion"` unchanged at 185 (no regression); `"Gleig"` returns his 3 works. This also partially mitigates the §6 data finding (abstract-less entries are now reachable via author/title match). The win is that **citation matching is no longer silently bounded by title/abstract text** — the single most important property of the audit tool.
