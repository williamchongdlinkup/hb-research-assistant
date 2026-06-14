# HB Research Assistant

> **About these build-plan files:** Everything in `_build_plan/` (this PRD and the per-milestone folders) is a **temporary documentation and guidance artifact** for the initial build-out of this codebase. These files are not functional — no code, configuration, runtime logic, tests, or deployment process should import, read, reference, or depend on anything in `_build_plan/`. Once the initial milestones are built and shipped, the entire `_build_plan/` folder is expected to be deleted from the codebase. Do not treat it as long-living documentation.

## What we're building

A focused web app that transforms the Humanistic Buddhism Research Bibliography — a curated corpus of 1,833 scholarly entries maintained by Nan Tien Institute — into a live AI research assistant. The first release delivers two capabilities no existing tool offers for this corpus: a multi-turn grounded Q&A interface where every AI response cites specific bibliography entries, and a reference audit tool where journal editors and researchers paste a bibliography and instantly see what key HB literature is missing.

Built for HB scholars, journal editors, and PhD students — initially debuted at the 12th HB Symposium on 20–21 June 2026. The tech stack is Python + FastAPI backend, SQLite with full-text search for the corpus, Gemini 3.1 Flash Lite (free tier) for AI reasoning, a single-file HTML/Tailwind/vanilla JS frontend, and Railway for deployment. The build is structured across 4 milestones, each delivering testable functionality.

---

### What the app does

- Presents a landing page that introduces the tool, displays corpus stats, and provides three clear entry points: Search, Q&A, and Reference Audit
- Lets researchers search the full 1,833-entry corpus by keyword, filtered by year range and publication type, with results shown as expandable cards
- Answers natural-language research questions in multi-turn conversation (up to 5 turns), with every AI claim linked via inline superscript to a specific corpus entry
- Displays a numbered reference list below each AI response, each entry expandable to full metadata
- Honestly declines to answer when a question falls outside what the corpus can ground
- Accepts a pasted bibliography in any citation format and audits it against the HB corpus in three sections: Verified, Missing, and Suggested
- Provides a one-line relevance reason for each Missing and Suggested entry, and a "Copy as APA" button for those sections

---

### Already provided by the existing corpus CSV

- 1,833 curated bibliography entries (HBBiblio_Dec2025_Complete.csv)
- Abstracts for most entries — the primary source for AI retrieval
- Full author, editor, journal, publisher, and page metadata
- Source URLs for most entries
- Publication year range spanning 2000–2025

---

### Out of scope

- **User accounts / login** — no sign-in, no saved sessions, no personal history; the tool is open and stateless
- **Semantic / vector search** — keyword + full-text search only; embeddings and a vector database come in Phase 2
- **Gap mapping & research question refinement** — powerful but needs more AI scaffolding than this sprint allows
- **Literature review generator** — Phase 2
- **Teaching / syllabus builder** — Phase 2
- **Corpus contribution workflow** — researchers cannot submit new entries yet; CSV is the source of truth
- **Citation export (BibTeX, Zotero, APA)** — Phase 2
- **Saving conversations or audit results** — sessions are browser-only and reset on close
- **Multiple AI models or user-supplied API keys** — one model (Gemini 3.1 Flash Lite), one server-side key
- **Admin panel / in-app corpus editing** — corpus is read-only; updated via CSV replacement
- **Multi-corpus / Direction B architecture** — HB corpus only; open-source engine is a later phase

---

### Data model

#### Bibliography Entry
Read-only. Loaded from CSV at startup. 1,833 records (December 2025 snapshot).

> **Corpus update pending:** The current CSV (`HBBiblio_Dec2025_Complete.csv`, 1,833 entries) is a snapshot. An updated corpus is expected in a few days and will replace this file when available, changing the entry count. All UI copy must read the count **dynamically from `/api/stats`** rather than hardcoding it, so the swap is a drop-in CSV replacement with no code or copy changes.

- **serial_no** — unique identifier from the original CSV
- **type** — publication type: journal article, book, conference paper, etc.
- **authors** — up to 4 authors, each stored as last name + first name
- **editors** — up to 3 editors, each stored as last name + first name
- **title** — title of the work
- **book_title** — title of the containing book (for book chapters)
- **journal** — journal name (for journal articles)
- **volume / issue** — journal volume and issue number
- **pages** — page start and end of the work
- **city / publisher** — publication city and publisher name
- **year** — publication year
- **abstract** — full abstract text; primary source for AI retrieval and keyword matching
- **url** — link to the online source

Referenced by Audit Session results.

#### Audit Session
Browser-only. Not stored on the server. Resets when the tab closes.

- **raw_text** — the bibliography text the user pasted in
- **verified** — pasted citations matched to corpus entries
- **missing** — key HB papers absent from the pasted list, each with a one-line relevance reason
- **suggested** — other relevant corpus entries not in the pasted list, ranked by relevance

References Bibliography Entries.

---

## Milestone 1 — Foundation

Sets up the entire project skeleton, loads the CSV corpus into a searchable database, and gets the app live on a public URL. Everything later builds on this.

### What gets built

- FastAPI project structure with CSV → SQLite FTS5 ingestion on startup
- Keyword search endpoint returning ranked results
- Result cards showing title, first author, year, publication type, and abstract excerpt
- Year range and publication type filters
- Expandable entry detail — full abstract visible on click; source URL opens in new tab
- Result count display ("Showing X of N entries", where N is the live corpus count from `/api/stats` — currently 1,833)
- Deployed live to Railway with a working public URL

### What Milestone 1 explicitly does NOT include

- Gemini API or any AI features
- Landing page (comes in Milestone 4)
- Final visual polish

### Done when

A researcher can visit the live Railway URL, type "compassion" in the search bar, and see a filtered list of relevant corpus entries with abstracts, all within 1 second.

---

## Milestone 2 — Grounded Q&A

Adds the AI research conversation layer. Researchers ask questions in natural language and receive grounded, cited answers drawn from the HB corpus — not from the open internet.

### What gets built

- Gemini API integration using GEMINI_API_KEY loaded from environment
- Chat-style interface with text input and conversation thread
- Multi-turn conversations up to 5 turns, with full history visible in the thread
- Thinking / loading indicator while the response is being generated
- AI response rendered as flowing prose — not bullet points
- Inline superscript citation numbers (e.g. ¹ ² ³) linking each claim to a specific corpus entry
- Numbered reference list below each response; each entry expandable to full metadata
- "Based on X entries from the HB corpus" label on each response
- "Start new conversation" button available at any time; automatically prompted when the 5-turn limit is reached
- Honest "outside corpus" response when the question cannot be grounded in available entries

### What Milestone 2 explicitly does NOT include

- Reference audit feature (Milestone 3)
- Saving or exporting conversations
- Sources or knowledge outside the HB corpus

### Done when

A researcher can ask "What does HB scholarship say about compassion and social action?" and receive a multi-paragraph prose response with numbered superscript citations, each linking to a verifiable corpus entry.

---

## Milestone 3 — Reference Audit

Adds the journal editor tool. A researcher or editor pastes any bibliography and instantly learns what's verified in the HB corpus, what's missing, and what else is relevant.

### What gets built

- Text area where the user pastes a bibliography in any citation format (APA, Chicago, etc.)
- "Audit" button that triggers the analysis
- Results displayed in three clearly labelled sections:
  - ✅ **Verified** — pasted citations matched to specific HB corpus entries, with links
  - ⚠️ **Missing** — key HB papers on the same topic absent from the pasted list, ranked by relevance
  - 💡 **Suggested** — other relevant corpus entries not in the pasted list, ranked
- Each result shows: title, author, year, and a one-line reason why it's relevant or missing
- "Copy suggestions as APA" button for the Missing and Suggested sections

### What Milestone 3 explicitly does NOT include

- Saving audit results
- Batch auditing multiple papers at once
- Detecting citation formatting errors (wrong year, misspelled author)
- Sources outside the HB corpus

### Done when

A journal editor can paste a paper's bibliography, click Audit, and within 30 seconds see a three-section report identifying which citations are in the HB corpus and which key HB papers are missing.

---

## Milestone 4 — Polish & Launch

Adds the landing page, unifies the visual design across all views, and prepares the app for its debut at the 12th HB Symposium on 20–21 June 2026.

### What gets built

- Landing page with: NTI logo, 2–3 sentence description of the tool, three labelled entry points (Search / Q&A / Audit), corpus stats (live entry count from `/api/stats` — currently 1,833, last updated date), citation request ("please cite your use"), and a link to the existing visualiser at visualiser.nantien.edu.au
- Unified visual design across all pages — clean, professional, academic tone
- End-to-end testing with 20+ real research queries across all three features
- Final Railway deploy with stable public URL ready to demo at the symposium

### What Milestone 4 explicitly does NOT include

- New features — scope is frozen for the symposium build
- Mobile app or browser extension
- Phase 2 features (vector search, gap mapping, literature review generator, etc.)

### Done when

A first-time visitor lands on the page, understands what the tool does within 10 seconds, navigates to Q&A, asks a real research question, and gets a grounded cited response — all without instruction.
