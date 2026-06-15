# Milestone 4 — Polish & Launch: Complete

**Date completed:** 2026-06-15
**Status:** Built, locally verified end-to-end (24 real queries across all three tools), and deployed.
**Live URL:** https://hb-research-assistant-production.up.railway.app/

---

## What was built

### Files changed

| File | Change |
|---|---|
| `index.html` | Added a **Home / landing view** (`tab-home`), shown first on load; generalised `switchTab` over `['home','search','qa','audit']` (home highlights no tab); re-skinned the whole app to the **NTI crimson** palette via one Tailwind token change; added a global footer; added Search fetch-error handling; closed the `javascript:` URL guard on Search + Q&A "View source" links; copy fix (search now matches authors). |
| `main.py` | Added `CORPUS_LAST_UPDATED` constant surfaced via `/api/stats` as `last_updated`; mounted `/static` (StaticFiles) and a `/favicon.ico` route to serve the bundled NTI logo; **fixed the multi-word search phrase-lock** (tokenise + AND instead of a single quoted phrase). |
| `static/nti_logo.png` | **New** — official NTI logo downloaded from nantien.edu.au and bundled locally (600×132 PNG) so the demo has no external image dependency. |

### Landing page (Home view)

Everything the PRD/key-inputs require:
- **NTI logo** (header — clickable Home link — and hero).
- **2–3 sentence description** of the tool.
- **Three labelled entry-point cards** (Search / Q&A / Audit), each with icon, one-line description, and CTA → opens that tool.
- **Live corpus stats** read from `/api/stats`: entry count + year range + "Updated {last_updated}". **Nothing is hardcoded** — the pending corpus swap needs no template change.
- **Citation request**: "If you use this tool in your research, please cite: Nan Tien Institute HB Research Bibliography, visualiser.nantien.edu.au".
- **Link to the existing visualiser** (hero card + footer).
- **Footer**: NTI attribution, citation line, visualiser link, AI model note (`gemini-3.1-flash-lite`).

### Unified visual design

- Brand colour changed from indigo `#4f46e5` → **NTI crimson `#b01116`** (sourced from nantien.edu.au's own stylesheet; `brand-dark #8a0d11`, `brand-light #d14a4f`). Because all three existing tools already used the `brand`/`brand-dark` Tailwind classes, this single token change unified Search / Q&A / Audit instantly.
- Warm "paper" page background (`#faf8f5`) for an academic, print-like feel; spinner + citation superscripts recoloured; indigo intro hints re-tinted to brand.
- Semantic status colours retained in the audit (emerald=verified, amber=missing, indigo=suggested, gray=outside) — a deliberate four-way distinction, not brand elements.

---

## Decisions made during implementation

1. **Branding via the official NTI logo, bundled locally.** Confirmed with William. The logo is downloaded into `static/` and served by the app rather than hot-linked to NTI's WordPress upload — a stability requirement for the symposium debut (no external dependency mid-demo).
2. **Palette taken from NTI's actual site**, not invented. Confirmed with William ("consult NTI's colour scheme"). Their dominant brand colour is crimson `#b01116`; the Divi-default `#2ea3f2` blue was correctly ignored as theme boilerplate.
3. **Landing as an in-SPA Home screen that routes to the tools** (confirmed with William), rather than an always-on banner or a separate page — first-time visitors get orientation; returning users are one click from any tool. The header logo/title is the Home link.
4. **`last_updated` is a single editable constant** (`CORPUS_LAST_UPDATED = "December 2025"`) surfaced via `/api/stats` — data-driven per the corpus-swap constraint.

### In-scope fixes beyond the literal landing-page work

These were the "still-open search-path debt" the sprint plan explicitly assigned to M4, surfaced by end-to-end testing:

5. **Multi-word search phrase-lock (demo-breaking) — fixed.** `/api/search` wrapped the entire query in quotes as one FTS5 *phrase*, so "environment ecology", "gender women", "education pedagogy" all returned **0 results** — only exact adjacent phrases matched. Now the query is tokenised on whitespace and the terms are AND-ed (each quoted to neutralise FTS special chars). A single whitespace-free token (incl. a CJK string) collapses to one quoted term, preserving prior behaviour and CJK handling.
   - After fix: environment ecology → 8, gender women → 20, education pedagogy → 5, social engagement → 85, Buddhist modernity → 59. **No regression**: compassion → 185, meditation → 137, Tzu Chi → 67, Fo Guang Shan → 145 (all unchanged).
6. **Search fetch error handling — added.** `doSearch` now shows a friendly error card on failure; `init()` uses `Promise.allSettled` so a stats/types failure can't block search from loading.
7. **`javascript:` URL guard (TD-04) — completed.** Search and Q&A "View source" links now apply the `^https?://` test (Audit already had it). This closes the last paths flagged in the M3 log.

---

## End-to-end testing (24 queries; PRD requires 20+)

Run locally against `uvicorn` with the production `GEMINI_API_KEY`.

- **Search (15):** compassion, mindfulness, Yinshun, Tzu Chi, Fo Guang Shan, engaged Buddhism, meditation, Taixu, social welfare, + multi-word (environment ecology, gender women, education pedagogy, social engagement, Buddhist modernity) + author (Gleig=3, Makransky=4) + year filter (compassion 2015–2020=44). All correct; FTS responses 4–360 ms.
- **Q&A (7):** six real HB research questions (compassion & social action, Buddhism & modernity, FGS & education, Tzu Chi & charity, critiques of HB, environmental ethics) — all answered in grounded prose with 6–17 resolving citations over 50 retrieved sources, 3–14 s each. The out-of-corpus control ("capital of France?") correctly returned the honest "does not contain sufficient information" reply with 0 citations.
- **Audit (2):** a clean 4-ref APA list (correctly verified the two HB works at `high` confidence and flagged the Gleig monograph + a quantum-physics paper as outside-corpus, plus 2 missing/2 suggested) and a messy paste with UI noise (`[N]`, `·`, `↗`, no clean breaks) — the parse-first pipeline verified 2 works and flagged 1 outside. ~2–4 s each, well under the 30 s budget.

Two transient test-only failures were diagnosed and dismissed: one Gemini-side `503 UNAVAILABLE "high demand"` (our 502 handler worked; retry succeeded) and one PowerShell-5.1 request-body unicode encoding artifact (browsers send UTF-8 correctly).

---

## Known issues / deferred to Phase 2

- **Audit recall is bounded by an 80-entry candidate pool** (per the free-tier rate-limit design from M3). A genuinely-in-corpus work can occasionally be flagged "outside" if it doesn't surface in the pool (e.g. Gleig's *American Dharma* in testing). Acceptable for the demo; a vector-retrieval pass is Phase 2.
- **APA output remains best-effort** (corpus lacks parsed first/middle initials for strict APA 7).
- **No mobile-specific layout pass** — the design is responsive (Tailwind), but small-screen polish wasn't a milestone goal.
- Phase 2 scope (vector search, gap mapping, literature-review generator) remains out of scope, as frozen for the symposium build.

---

## Done when (PRD) — met

> A first-time visitor lands on the page, understands what the tool does within 10 seconds, navigates to Q&A, asks a real research question, and gets a grounded cited response — all without instruction.

The Home view leads with the logo, a one-line value proposition, and three self-describing entry-point cards; clicking **Q&A Chat** opens the chat, where a real question (verified above) returns grounded prose with resolving citations. The five-day sprint build (M1–M4) is complete and deployed for the 12th HB Symposium, 20–21 June 2026.
