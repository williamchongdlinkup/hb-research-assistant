# Milestone 3 — Reference Audit: Complete

**Date completed:** 2026-06-15
**Status:** Built and locally verified. Live audit returns correct four-bucket classification in ~2.2s (target: <30s). Uses the same `GEMINI_API_KEY` already configured in Railway.

---

## What was built

### Files modified

| File | Change |
|---|---|
| `main.py` | Added `AuditRequest` model, `_AUDIT_SYSTEM_PROMPT`, `_parse_json`, `_retrieve_audit_pool`, `_format_audit_pool`, `_attach_entries`, and `POST /api/audit`. Also cleared M2 tech debt: removed dead `StaticFiles` import (TD-01) and stopped leaking raw exceptions in `/api/chat` and `/api/audit` (TD-10), now logged server-side via a module `logger`. |
| `index.html` | Added "Reference Audit" tab (third tab), generalised `switchTab` to 3 tabs, audit input/results UI, and all audit JS (`runAudit`, `renderAudit`, `auditSection`, `auditItem`, `apaFromEntry`, `copyAuditApa`). |

### New API route

| Route | Description |
|---|---|
| `POST /api/audit` | Body `{bibliography: str}`. Retrieves a 60-entry corpus pool from the pasted text, then a **single** `gemini-3.1-flash-lite` call (structured JSON, `response_mime_type=application/json`) parses + classifies. Returns `{verified, not_in_corpus, missing, suggested, pool_size}`. |

### Frontend features (Reference Audit tab)

- Paste textarea (any citation format) + "Audit" button; Ctrl/⌘+Enter to run
- Loading state while analysing; graceful error + network-error cards
- Summary bar: counts of verified / outside-corpus / missing / suggested + pool size
- Four result sections:
  - ✅ **Verified** — pasted citations matched to corpus entries, each with a `high`/`probable` confidence badge, one-line reason, and `View source ↗`
  - ⚠️ **Missing** — up to 5 key HB papers absent from the pasted list, with reasons
  - 💡 **Suggested** — up to 5 other relevant HB entries, with reasons
  - 📄 **Not in HB corpus** — pasted citations with no HB match (the 4th section, see decisions)
- "Copy suggestions as APA" → copies Missing + Suggested as best-effort APA to clipboard

---

## Decisions made during implementation

These three were confirmed with William before building:

**1. Added a 4th "Not in HB corpus" section (beyond the PRD's 3).**
An HB paper's bibliography contains many non-HB citations that will never match the corpus. Without a home for them, a 40-item bibliography showing only 3 Verified and nothing else is confusing. The 4th section gives editors a full accounting. *(Deviation from PRD — see table below.)*

**2. "Verified" uses probable matches, confidence-flagged.**
Close matches (title/author/format variations) count as Verified but are flagged `high` vs `probable`, so citation-format noise doesn't hide real matches while users can still see match certainty.

**3. Missing and Suggested capped at ~5 each.**
Tight, high-relevance lists; fastest and safest on the 30s budget and free-tier rate limit. Caps enforced server-side in `_attach_entries` as a defensive backstop even if the model returns more.

Other implementation decisions (not pre-specified):

**4. Single Gemini call, not one-per-citation.**
A per-citation matching loop would blow the free-tier rate limit (15 req/min) on any real bibliography. Instead, `_retrieve_audit_pool` retrieves one 60-entry pool from the *whole* pasted text — the titles of cited HB papers surface their own corpus entries for matching, while topic terms surface related entries for Missing/Suggested. One structured-JSON call then does parse + classify. Result: 1 API call per audit, ~2.2s observed.

**5. Structured JSON output via `response_mime_type="application/json"`.**
The model returns strict JSON keyed by corpus **index** (`[N]` into the pool). `_parse_json` tolerantly strips markdown fences and falls back to a `{...}` regex extract. `_attach_entries` maps indices → full entry dicts, drops out-of-range/duplicate indices, and enforces single-bucket membership (verified → missing → suggested precedence).

**6. APA generation is frontend-only, best-effort.**
`apaFromEntry()` assembles `Author (Year). Title. Venue, Vol(Issue), pages.` from corpus metadata. The corpus `author_display` is `Last, First; Last2; …`, so this is best-effort APA, not strict APA 7 — acceptable per PRD scope.

**7. Reused, not modified, the M2 retrieval.**
`_retrieve_audit_pool` is a separate helper (dedupes terms, caps at 120, includes abstract excerpts in the pool) so M2's chat retrieval path is untouched. Falls back to `_retrieve_for_query` on FTS error.

---

## Tech debt addressed (from M2 evaluation)

| # | Item | Status |
|---|---|---|
| TD-01 | Dead `StaticFiles` import | ✅ Removed |
| TD-10 | Raw exception leaked to client in `/api/chat` | ✅ Fixed — now `logger.exception(...)` server-side + generic client message; same pattern in `/api/audit` |
| TD-04 | `javascript:` URL guard | ✅ Applied in new audit code (`/^https?:\/\//i` test before rendering `View source`); search/chat paths still pending (M4) |

---

## What Milestone 4 needs to know

- **Three tabs now exist** (`tab-search`, `tab-qa`, `tab-audit`); `switchTab(tab)` is generalised over the array `['search','qa','audit']`. M4's landing page should route into these.
- **`/api/audit` is stateless** like the rest — no server session state; all UI state is browser-only.
- **Audit matching quality is bounded by the 60-entry pool.** If a bibliography cites an HB paper whose title ranks past position 60 in FTS retrieval, it can be missed as "not in corpus." Acceptable for the demo; flagged for M4 end-to-end testing.
- **Single shared `GEMINI_MODEL` constant** drives chat and audit — M4 model references should read it, not hardcode.
- **APA output is best-effort** — if M4 wants strict APA 7, the corpus author fields need first/middle initial parsing.

---

## Deviations from PRD

| PRD spec | Actual |
|---|---|
| Three result sections (Verified / Missing / Suggested) | Added a 4th **Not in HB corpus** section for unmatched pasted citations (confirmed with William) — needed so editors get a complete accounting |
| (implied) per-citation matching | Single pooled retrieval + one Gemini call, to respect free-tier rate limits |
| "Copy suggestions as APA" | Best-effort APA from corpus metadata (corpus lacks parsed first/middle initials for strict APA 7) |
