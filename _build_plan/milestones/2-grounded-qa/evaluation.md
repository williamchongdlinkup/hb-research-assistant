# Milestone 2 — Grounded Q&A: Evaluation Report

**Evaluated:** 2026-06-15
**Commit reviewed:** `44f3016` — "Milestone 2: Grounded Q&A — Gemini RAG-lite chat with inline citations"
**Evaluator:** Claude Code (Opus 4.8)

---

## §1 Requirements Compliance

| PRD Requirement | Status | Notes |
|---|---|---|
| Gemini API integration using `GEMINI_API_KEY` from environment | ✅ Met | Module-level `genai.Client`; 503 returned when key absent |
| Chat-style interface with text input and conversation thread | ✅ Met | Dedicated Q&A tab; thread grows downward; user/AI bubbles |
| Multi-turn conversations up to 5 turns, full history visible | ✅ Met | `MAX_TURNS=5`; history sent to backend; all turns remain in thread |
| Thinking / loading indicator while generating | ✅ Met | Typing indicator ("Searching corpus and composing response…") + spinner |
| AI response as flowing prose (not bullet points) | ✅ Met | System prompt rule 1 forbids lists; verified prose output live |
| Inline superscript citation numbers linking claims to entries | ✅ Met | `[N]` parsed to `<sup><a>` anchors; verified 8–19 citations per live answer |
| Numbered reference list below each response, expandable to full metadata | ✅ Met | Collapsible "References (N)"; each entry has Show abstract + View source |
| "Based on X entries from the HB corpus" label per response | ✅ Met | Renders `sources_count` (50) below each answer |
| "Start new conversation" button available at any time + on 5-turn limit | ✅ Met | Always-visible button (index.html:160) + limit-reached button (167) |
| Honest "outside corpus" response when ungroundable | ✅ Met | System prompt rule 4; verified live — multi-turn follow-up returned the exact refusal string |

**Compliance score: 10/10 specs met.**

Explicit non-goals (reference audit, save/export, outside-corpus sources) were correctly excluded.

---

## §2 "Done When" Criterion

> *A researcher can ask "What does HB scholarship say about compassion and social action?" and receive a multi-paragraph prose response with numbered superscript citations, each linking to a verifiable corpus entry.*

| Condition | Status |
|---|---|
| Natural-language question accepted | ✅ |
| Multi-paragraph prose response | ✅ 2,198–2,423 chars across test queries, paragraph-broken |
| Numbered superscript citations | ✅ `[N]` → `<sup>` anchors, 8–19 per response |
| Each citation links to a verifiable corpus entry | ✅ Citation objects carry full entry metadata (author, year, title, venue, abstract, url) |
| Verified on live deployment | ✅ Production `/api/chat` returned HTTP 200 with grounded, cited answer on 2026-06-15 after `GEMINI_API_KEY` set in Railway |

**Done-when fully met and verified end-to-end in production.**

---

## §3 Code Quality

### Backend — `main.py` (412 lines, +134 over M1)

**Strengths:**

- **Clean helper decomposition.** `_retrieve_for_query()`, `_build_system_prompt()`, and the `chat()` endpoint each have a single responsibility. Both helpers are reusable by M3's reference audit, as the milestone log intends.
- **Stopword-filtered OR-token retrieval (`_retrieve_for_query`).** This directly fixes M1's TD-03 phrase-lock defect *for the chat path*: queries are tokenised (`\b[a-zA-Z]{3,}\b`), stopwords removed, and joined with `OR`, so BM25 ranks entries that discuss the topics independently — not only adjacent phrases. This is the correct retrieval model for RAG.
- **Citation bounds check.** `if 1 <= n <= len(entries)` (line 408) discards any `[N]` the model emits outside the retrieved set, preventing both `IndexError` and the rendering of a citation that points at nothing.
- **Strong grounding contract.** `_SYSTEM_PROMPT` is explicit: corpus-only, prose-only, cite-only-listed-numbers, and a fixed refusal string when ungroundable. The refusal path was observed working live, which is the single most important property of a "grounded" assistant.
- **Correct HTTP semantics.** 503 for missing key (config), 502 for upstream generation failure (bad gateway). This let the deploy-time "is the key set?" check be a clean status-code probe.
- **FTS→LIKE fallback mirrors the search path**, so a pathological query degrades instead of 500-ing.

**Issues:**

- **Model-name doc mismatch (medium, documentation).** Code uses `GEMINI_MODEL = "gemini-3.1-flash-lite"` (line 22), but the PRD, the M2 prompt, *and the M2 milestone-log* all state `gemini-2.0-flash`. The code is what runs and it is verified working live, so this is not a functional defect — but the milestone-log is now inaccurate and should be reconciled so the record matches reality. See §7 TD-09.
- **Raw exception leaked to client (low, security/info-leak).** Line 402 returns `f"AI generation failed: {exc}"` directly in the 502 body. A Gemini SDK exception can contain quota messages, model identifiers, or key-state hints. Log the detail server-side; return a generic message to the client.
- **Per-turn re-retrieval causes citation-number drift across turns (medium, documented).** Each turn retrieves a fresh top-50 and renumbers `[N]` from 1, while prior AI turns already in `history` carry `[N]` from a *different* retrieval set. For follow-ups on the same topic the sets largely overlap, but the numbers are not guaranteed stable turn-to-turn. The milestone log acknowledges this as an accepted trade-off for a 5-turn demo; it is recorded here as a real correctness limitation, not a blocker.
- **Retrieval ignores conversation history (low).** `_retrieve_for_query(req.message)` keys only on the latest message. Pronoun-style follow-ups ("which authors did *that*?") under-retrieve — this is exactly what produced the (safe) refusal observed during multi-turn testing. Acceptable for the demo; a future improvement is to fold recent user turns into the retrieval query.
- **Dead `StaticFiles` import still present (low).** Line 14 — M1's TD-01 was expected to be cleared "next time main.py is edited"; main.py was heavily edited in M2 but the import remains.
- **No generation config limits (low).** No `max_output_tokens` / temperature set; relies on SDK defaults. Fine for the demo; worth pinning for cost/latency predictability.

### Frontend — `index.html` (~682 lines, +466/−73 over M1)

**Strengths:**

- **Fetch error handling on the chat path (resolves M1 TD-02 for chat).** `sendChat()` wraps the request in try/catch, checks `!res.ok`, parses the error body defensively (`.catch(() => ({}))`), and renders a visible error card. The typing indicator is removed in every exit path and the input is re-enabled in `finally`. This is the robust pattern M1 was missing.
- **XSS-safe citation rendering.** `parseCitationsToHtml()` calls `escHtml()` *before* injecting `<sup>` anchors and paragraph tags, so model output cannot inject markup. All entry fields in `renderCitationEntry()` are escaped.
- **History snapshot before await.** `const historySnapshot = [...chatHistory]` is captured before the network call, avoiding a race if state changes mid-flight.
- **Correct Gemini role mapping.** History is stored with `role: 'model'` (line 483), matching the role name the Gemini SDK expects — not the OpenAI-style `assistant`. This is a subtle correctness point handled right.
- **Complete turn lifecycle.** Turn counter, 5-turn lockout, limit message, and `newConversation()` reset (including intro-hint restore and counter reset) are all handled cleanly.

**Issues:**

- **Citation anchor does not auto-expand collapsed references (low, UX).** Clicking a `[N]` superscript targets `#chat-ref-{msgId}-{n}`, which lives inside the `hidden` references container. If the user hasn't expanded "References (N)", the anchor target is `display:none` and the jump silently does nothing. A polish fix: have the citation click expand the refs panel before scrolling. See §7 TD-12.
- **`escAttr` is still an alias for `escHtml` + no `javascript:` URL guard (low, carry-forward).** M1's TD-04 now also applies to the citation "View source ↗" link (line 600): a corpus URL is HTML-escaped but not scheme-validated. Risk remains very low (curated NTI corpus) but the one-line `^https?://` guard should be applied in M4.
- **`year` interpolated unescaped (very low).** Lines 580/592 insert `${year}` without escaping. It originates as an `int` from the DB (or the literal `'n.d.'`), so it is not attacker-controlled — safe in practice, noted for completeness.
- **No response streaming (acceptable).** The full answer arrives after one round-trip (~3–8s); the typing indicator covers the wait. Streaming is out of scope for the demo.

---

## §4 Security Assessment

| Surface | Finding | Severity | Status |
|---|---|---|---|
| Chat message → FTS retrieval | Tokenised, quoted, OR-joined, parameterised; `OperationalError` → LIKE fallback | — | ✅ Safe |
| Chat message → Gemini prompt | User text embedded in prompt context; prompt-injection possible but impact bounded (corpus is public; worst case is an off-corpus answer) | Low | ⚠️ Accept for demo |
| Gemini answer → DOM | `escHtml()` applied before `[N]`→`<sup>` transform; all fields escaped | — | ✅ Safe |
| Citation URL → `href` | `escAttr` = HTML-escape only; no `javascript:` scheme guard | Low | ⚠️ Flag for M4 (TD-04) |
| `/api/chat` error body | Raw `exc` string returned to client | Low | ⚠️ Fix recommended (TD-10) |
| Missing API key | Returns 503, no stack trace, no secret echoed | — | ✅ Safe |
| `.env` / secret handling | `.env` gitignored; key only in local env + Railway dashboard; never committed | — | ✅ Safe |

No high-severity findings. The corpus is curated public academic data, which bounds the practical impact of both prompt injection and URL-scheme risks.

---

## §5 Performance

| Metric | Result | Target | Assessment |
|---|---|---|---|
| FTS retrieval (top-50) | sub-millisecond (in-memory FTS5) | — | ✅ Negligible vs. model latency |
| Chat round-trip — local, warm | ~3.1s (single turn), ~1.2s (multi-turn) | No explicit PRD target | ✅ Acceptable for interactive Q&A |
| Chat round-trip — production, first call post-redeploy | ~8s (cold) | — | ⚠️ Cold-start; warm calls faster |
| Chat round-trip — production, fresh query | ~7.8s | — | ✅ Model latency dominates; acceptable |
| Prompt size | 50 entries × (citation line + full abstract) | — | ⚠️ Large but within flash-lite limits |

Gemini generation latency dominates end-to-end time; retrieval is effectively free. The 50-entry context includes full abstracts, which is the main lever on prompt size — fine for the chosen lightweight model and demo scale. **Railway cold-start caveat from M1 still applies:** warm the app before any live symposium demo.

---

## §6 Data Quality Findings

No new data-layer changes in this milestone — the ingestion path and schema are unchanged from M1. M1's findings (1,833 actual entries, 12 year-`0`→NULL rows, 30 inconsistent publication-type strings, some abstract-less entries) carry forward unchanged. Note that abstract-less entries are also invisible to chat retrieval, since FTS indexes only `title` + `abstract`.

---

## §7 Technical Debt Register

**Carried forward from M1:**

| # | Item | File | Severity | Status after M2 |
|---|---|---|---|---|
| TD-01 | Remove dead `StaticFiles` import | `main.py:14` | Low | ❌ Still open (main.py edited, import remains) |
| TD-02 | Fetch error handling | `index.html` | Medium | ⚠️ Partial — added to chat path; **search path (`doSearch`/`loadStats`/`loadTypes`) still unguarded** |
| TD-03 | FTS5 phrase-lock → token search | `main.py` | Medium | ⚠️ Partial — **fixed for chat retrieval (OR tokens); `/api/search` still phrase-locks** (`main.py:253`) |
| TD-04 | `javascript:` URL guard | `index.html:600` | Low | ❌ Still open (now also on citation links) — M4 |
| TD-05 | Apply API year range to `<input min/max>` | `index.html` | Low | ❌ Still open — M4 |
| TD-06 | Remove dead `.card-expanded` CSS | `index.html` | Low | ❌ Still open — M4 |
| TD-07 | Publication-type normalisation | data / ingest | Medium | ❌ Still open — data pass |
| TD-08 | Document `_db` read-only constraint | `main.py` | Medium | ✅ Effectively resolved — M2 introduced no write paths; `_db` remains read-only |

**New in M2:**

| # | Item | File | Severity | Target milestone |
|---|---|---|---|---|
| TD-09 | Reconcile model-name doc: code runs `gemini-3.1-flash-lite`, milestone-log says `gemini-2.0-flash` | `main.py:22` / M2 log | Medium | Immediate (doc fix) |
| TD-10 | Stop leaking raw `exc` in `/api/chat` 502 body; log server-side, return generic message | `main.py:402` | Low | M3 (next main.py edit) |
| TD-11 | Multi-turn citation-number drift from per-turn re-retrieval/renumbering | `main.py:384,404` | Medium | Post-demo (architectural) |
| TD-12 | Citation `[N]` click should auto-expand collapsed references before scrolling | `index.html:529,625` | Low | M4 polish |

---

## §8 Deployment Readiness

| Artefact | Status | Notes |
|---|---|---|
| `requirements.txt` | ✅ Correct | `google-genai`, `python-dotenv` added |
| Committed to git | ✅ | `44f3016` on `master`, pushed to `main` |
| Railway build | ✅ | New `/api/chat` route live after push |
| `GEMINI_API_KEY` on Railway | ✅ | Set in dashboard; live `/api/chat` returns 200 (was 503 before) |
| Secret hygiene | ✅ | `.env` gitignored; key never committed |
| Local `.env` for dev | ✅ | Present and working |
| Live verification | ✅ | Production grounded answer with citations confirmed 2026-06-15 |

---

## Overall Assessment

Milestone 2 meets every functional requirement (10/10) and the "Done when" criterion is verified end-to-end in production. The implementation is well-structured: the RAG-lite retrieval correctly fixes M1's phrase-lock defect for the chat path, the grounding contract is strong and observably enforced (the refusal path works), and the frontend adds the robust fetch error handling M1 lacked. The highest-priority item is purely documentary — the running model is `gemini-3.1-flash-lite`, not the `gemini-2.0-flash` recorded in the milestone log (TD-09) — and should be reconciled so the project record is accurate. The remaining issues (raw-exception leak, multi-turn citation drift, citation anchor UX) are low-to-medium and none block Milestone 3.

**Milestone 2 verdict: APPROVED.** All requirements met, deployed, and live-verified. Recommended before/at M3 start: reconcile the model-name documentation (TD-09) and suppress the raw-exception leak (TD-10) while `main.py` is open.
