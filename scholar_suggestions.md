# Scholar Suggestions — HB Research Assistant

**App:** https://hb-research-assistant-production.up.railway.app/
**Purpose:** Curated, living backlog of suggestions scholars have made *about this app* (the Search / Q&A Chat / Reference Audit tool), each mapped to the app's current state and a next action. This is a tracker — it is not the corpus-content to-do list (article additions live with the bibliography CSV).
**Last updated:** 2026-06-21

## Scope
Drawn from the **engaged researcher cohort** the project prioritises for feature validation — Makransky, Reinke, Gleig, Laliberté, Lancaster (per `researcher_cohort.md`) — **plus live feedback from the 12th HB Symposium (June 20–21, 2026)** in `project_symposium_feedback.md`.

**Sources:**
- `../outreach_responses.md` — Wave 2/3 email feedback (Dec 2024 – Jul 2025)
- `project_symposium_feedback.md` (memory) — symposium attendee feedback, June 2026
- `project_directions.md` (memory) — locked Direction-A Phase 1 scope & priority stack

## Status legend
| Status | Meaning |
|---|---|
| ✅ Done | Live in the deployed app |
| 🟡 Partial | Partially addressed; a concrete gap remains |
| ⬜ Open | Not built; actionable within current direction |
| 🔵 Deferred | Out of Phase 1 scope (Direction B / data-model change) |

---

## Summary table

| # | Scholar | Suggestion (app-specific) | Status | Next action |
|---|---|---|---|---|
| 1 | Makransky | Simple search by author last name / topic | ✅ Done | — |
| 2 | Makransky | App is invisible on Google (SEO) | ⬜ Open | Add SEO meta + sitemap (see §1) |
| 3 | Reinke | HBot missed his own work; fewer hits than a library search | 🟡 Partial | Confirm recall on his corpus; decide on library-link stance |
| 4 | Gleig | Opening/about page: what it is, sponsor, update frequency, author contact | 🟡 Partial | Add funder line + "suggest an addition" contact (see §3) |
| 5 | Gleig | Clarify how the resource is organized / navigation | ✅ Done | — |
| 6 | Gleig | Editor-written descriptions for entries lacking abstracts | ⬜ Open | Editorial pipeline — out of app code, track separately |
| 7 | Laliberté | Thematic / association-based filtering (welfare, philanthropy, Tzu Chi, Soka Gakkai, FGS) | ⬜ Open | Build thematic facets — converges with #9 |
| 8 | Laliberté | Static link — couldn't see his publications | ✅ Done | — |
| 9 | Jack & Stefania (symposium) | Curated thematic lists within HB (environmentalism, management, education…), a few key works each | ⬜ Open | Decide curation method, then build thematic landing lists |
| 10 | Yi (symposium) | Primary vs secondary source classification + primary→primary (canonical lineage) traversal, on one united interface | 🔵 Deferred | Data-model decision needed (see §5) |
| 11 | Lancaster | Make AI help make best use of massive data | ✅ Done | Q&A + Audit deliver this in spirit |
| 12 | Danny Wong & Fon Sim (symposium) | Let other fields host their own bibliographies; append related HB works | 🔵 Deferred | Direction B — but test the "related HB" cross-link cheaply |

> **Cross-cutting design constraint (Jack & Yi, symposium):** Keep everything on **one united interface** — do **not** spin new capabilities (e.g. a primary-source engine, #10) out as separate apps. Jack stated this and Yi explicitly aligned with it. Treat as a standing principle for #9, #10, and #12, not a feature to build. (Symposium "Stefania" = **Travagnin**, SOAS — highest-value AI-adjacent contact per `researcher_cohort.md`; "Jack" = **Jack Meng-Tat Chia**, NUS — confirm.)

---

## Detail

### §1 — Search & discoverability

**1. Author/topic search — Makransky (Dec 2024).** ✅ Done.
> "It would be a big help if there was a simple search mechanism to look for a particular author by last name, or a particular topic."
Search now queries titles, **authors**, and abstracts via FTS5, with year-range and type filters (`index.html:180`, `main.py` search endpoint). His follow-up praised HBot as fulfilling this. No further action.

**2. Google/SEO invisibility — Makransky (Jun 30, 2025).** ⬜ Open.
> "When I googled 'Humanistic and Engaged Buddhism Research Bibliography', the bibliography did not come up… Just FYI."
The deployed app's `<head>` carries only a `viewport` tag (`index.html:1–8`) — **no `meta description`, Open Graph/Twitter cards, canonical URL, `robots`, JSON-LD, or `sitemap.xml`/`robots.txt`.** A crawler sees almost nothing. Makransky's original flag was about the Django visualiser, but the Railway app has the same gap and is now a primary entry point.
**Next action:** add descriptive `<title>`/`meta description`, OG + Twitter tags, canonical link, `Dataset`/`WebSite` JSON-LD, and serve `robots.txt` + `sitemap.xml` from FastAPI. Cheap, high-leverage. Note: this is a *secondary* tool to `visualiser.nantien.edu.au` — confirm canonical/indexing intent with William first.

### §2 — Q&A Chat (HBot) recall

**3. Missed his own work; fewer results than library — Reinke (Apr 25, 2025).** 🟡 Partial.
> "It didn't find any of my own work… searching for specific themes — like the globalization of Fo Guang Shan or Sheng Yen — it returns fewer results than our university library search. Maybe it could be linked to global library datasets?"
Retrieval was hardened post-feedback (author-name indexing, per-citation retrieval, parse-first pipeline — see git log `75ea57d`, `6982690`), and the outreach record notes his work is now represented. His Jul 1 close was positive.
**Two distinct asks remain:** (a) **recall verification** — spot-check that Reinke's authored entries and "FGS globalization / Sheng Yen" themes now surface in both Search and Q&A against the current corpus; (b) **federated library linking** — by design the tool answers *only* from the curated HB corpus (grounded, no outside knowledge, `main.py:_SYSTEM_PROMPT`). Linking to external library datasets conflicts with that guarantee.
**Next action:** run the recall spot-check; record an explicit decision (likely "decline, by design") on external-library federation, with a one-line in-app note that scope is the curated HB corpus.

### §3 — Landing / about page

**4. About page: what it is, sponsor, update frequency, author contact — Gleig (Jan 2, 2025).** 🟡 Partial.
> "Add an opening page explaining what the resource is and who sponsors it; mention update frequency and a contact for authors."
Present: hero explaining the tool (`index.html:80–90`), NTI attribution + citation in footer (`index.html:311–319`), and a dynamic "Updated {date}" from `/api/stats` (`index.html:373`). **Missing: who *funds/sponsors* it, and a contact path for authors to submit additions or corrections.**
**Next action:** add a short "About / Suggest an addition" block to the landing page — funder/sponsor line, update cadence in words, and a `visualiser@nantien.edu.au` (or preferred) contact. Closes the loop with the steady stream of "please add my article" emails.

**5. Organization / navigation unclear — Gleig (Jan 2, 2025).** ✅ Done.
> "Clarify how the resource is organized (not alphabetical by author or topic — navigation was unclear)."
The rebuild replaced the ambiguous network view with a landing page + three labelled tabs (Search / Q&A Chat / Reference Audit), each with descriptive copy (`index.html:56–135`). Structurally resolved.

**6. Editor descriptions for entries lacking abstracts — Gleig (Jan 2, 2025).** ⬜ Open.
> "For articles without abstracts, have an editor provide brief descriptions."
Entries with no abstract render "No abstract"; there is no editorial-description field or generation step. This is a **corpus/editorial** task, not app code — flagged here for visibility but should be tracked against the bibliography CSV. Possible cheap win: AI-drafted one-line descriptions for abstract-less entries, editor-reviewed.

### §4 — Thematic / curated entry points

**7. Thematic & association filtering — Laliberté (Jun–Jul 2025).** ⬜ Open.
> "Adding themes such as 'Buddhism and welfare,' 'Buddhism and philanthropy/charity' and maybe even associations like Tzu Chi, Soka Gakkai, Foguangshan… it would be useful."
Search exposes only **year + type** facets (`index.html:185–201`). No thematic or organisation/association filtering. Maps to Direction-A priority "sub-topic filtering (compassion, wisdom, engaged Buddhism, education)."

**9. Curated thematic lists within HB — Jack & Stefania, symposium (Jun 21, 2026).** ⬜ Open.
> Curate thematic lists by HB sub-topic — environmentalism, management, etc. — each listing a few key works, "for those who might be interested to look into them."
This **converges with #7** and is the symposium's validated pivot (Jack + Stefania pushed back on the cross-field idea in favour of inward, curated lists). Fits William's importance-over-quota preference: short, strong, curated — not exhaustive.
**Combined next action:** design a thematic layer — start with editor-curated lists for a handful of themes (welfare/philanthropy, environmentalism, management, education, Tzu Chi/FGS/Soka Gakkai), surfaced as landing entry points and/or filters. **Open question for William:** who defines the themes and picks "key works" — editorial, citation-count heuristic, or AI clustering over the corpus?

### §5 — Larger / deferred directions

**10. Primary-source classification & lineage traversal — Yi, symposium (Jun 21, 2026).** 🔵 Deferred (data-model decision).
Yi (strict philologist): primary sources dominate; the daily act is traversing **primary→primary** (e.g. VMHY → the canonical source it cites). Wants source-type (primary vs secondary) and within-primary level/lineage as a **first-class data dimension**, on **one united interface** (aligned with Jack).
**Caveat from the feedback:** the current corpus is mostly *secondary* scholarship — serving this need likely requires ingesting/linking primary + canonical sources. Large scope.
**Next action:** William to weigh whether to extend the corpus toward primary/canonical sources + citation links. Keep on one interface; do not spin out a separate app (confirmed by Yi + Jack).

**11. Make AI help use massive data — Lancaster (Dec 2024).** ✅ Done (in spirit).
> "Now that we have AI is it possible to make an arrangement… that makes it possible to make best use of all these entries?"
The grounded Q&A Chat and Reference Audit are direct answers to this open challenge. No specific feature was requested; consider Lancaster a validation target for new AI features.

**12. Multi-field corpus hosting + related-HB cross-link — Danny Wong & Fon Sim, symposium (Jun 21, 2026).** 🔵 Deferred.
Open the platform so other fields host their own bibliographies, appending highly relevant HB research to seed cross-pollination. This is **Direction B** (deferred per `project_directions.md`) — and Jack/Stefania doubt foreign-field uptake (#9 is the agreed pivot). **However**, the cheap, novel piece — "recommend related HB work" — is testable *within* Direction A (e.g. surface related HB entries alongside a result) before any multi-tenant platform exists. Status tentative; William plans to float and gauge response.

---

## Decisions needed from William
1. **SEO (#2):** Should the Railway app be indexed and canonicalised, or stay subordinate to `visualiser.nantien.edu.au`? Determines canonical-URL strategy.
2. **Library federation (#3):** Confirm we decline external-library linking to preserve the grounded-corpus guarantee (and say so in-app).
3. **Thematic curation (#7/#9):** Who defines themes and selects key works — editorial, citation heuristic, or AI clustering?
4. **Primary sources (#10):** Worth extending the corpus toward primary/canonical texts + lineage links, or keep secondary-only and note the limitation?
