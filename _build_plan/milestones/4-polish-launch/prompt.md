# Milestone 4 — Polish & Launch

You are entering plan mode to plan and then build milestone 4 of this project.

## Context

- Read `@_build_plan/prd.md` for the full project context, scope, data model, and tech stack.
- Read all previous milestone logs (`@_build_plan/milestones/1-foundation/milestone-log.md`, `@_build_plan/milestones/2-grounded-qa/milestone-log.md`, `@_build_plan/milestones/3-reference-audit/milestone-log.md`) to understand the full current state of the codebase.

## Your task

1. Plan the implementation for **only** milestone 4 as defined in the PRD. Do not add features beyond what is scoped.
2. After the user confirms the plan, build only what is in milestone 4's scope.
3. Verify your work against the "Done when" criteria for milestone 4 in the PRD.
4. When complete, write a `milestone-log.md` in this folder (`_build_plan/milestones/4-polish-launch/milestone-log.md`) summarizing:
   - What was built or changed
   - Any decisions made during implementation
   - The final public URL of the deployed app
   - Any known issues or deferred items for Phase 2

## Key inputs

- Landing page must include: NTI logo, 2–3 sentence description, three entry points (Search / Q&A / Audit), corpus stats (entry count read **live from `/api/stats`** — currently 1,833 — and last-updated date), a citation request ("If you use this tool in your research, please cite: Nan Tien Institute HB Research Bibliography, visualiser.nantien.edu.au"), and a link to the existing visualiser at https://visualiser.nantien.edu.au/HBbiblio/.
- The visual design should feel clean, professional, and appropriate for an academic research audience — not like a generic SaaS product.
- Run end-to-end tests with at least 20 real research queries spanning diverse HB topics before declaring done.
- The app debuts at the 12th HB Symposium on 20–21 June 2026 — the final deploy must be stable and the URL must be shareable.
- The AI model in use is `gemini-3.1-flash-lite` (via the `GEMINI_MODEL` constant in `main.py`). Ensure any model references in landing-page copy, about text, or documentation state this model, not an older one.
- **Corpus update pending:** the current `HBBiblio_Dec2025_Complete.csv` (1,833 entries) is a snapshot that will be replaced by an updated corpus expected within a few days. Do NOT hardcode the entry count anywhere in the landing page or copy — read it live from `/api/stats` so the corpus swap requires no code change. Likewise keep the "last updated" date data-driven or trivially editable.

Ask me any clarifying questions using the AskUserQuestion tool to lock in the implementation plan for this milestone.
