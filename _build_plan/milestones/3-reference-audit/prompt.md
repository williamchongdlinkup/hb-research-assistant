# Milestone 3 — Reference Audit

You are entering plan mode to plan and then build milestone 3 of this project.

## Context

- Read `@_build_plan/prd.md` for the full project context, scope, data model, and tech stack.
- Read `@_build_plan/milestones/1-foundation/milestone-log.md` and `@_build_plan/milestones/2-grounded-qa/milestone-log.md` to understand what has already been built.

## Your task

1. Plan the implementation for **only** milestone 3 as defined in the PRD. Do not plan or build anything from milestone 4.
2. After the user confirms the plan, build only what is in milestone 3's scope.
3. Verify your work against the "Done when" criteria for milestone 3 in the PRD.
4. When complete, write a `milestone-log.md` in this folder (`_build_plan/milestones/3-reference-audit/milestone-log.md`) summarizing:
   - What was built (files created or modified, routes added, etc.)
   - Any decisions made during implementation that weren't pre-specified in the PRD
   - Anything milestone 4 will need to know
   - Any deviations from the PRD and why

## Key inputs

- The audit accepts a pasted bibliography in any citation format — the AI should parse it, not a rigid regex parser.
- The three output sections are: ✅ Verified (matched to corpus entries), ⚠️ Missing (key HB papers on the topic that are absent), 💡 Suggested (other relevant entries).
- Each result must include: title, author, year, and a one-line reason for inclusion.
- The "Copy suggestions as APA" button copies the Missing + Suggested entries formatted as APA citations to the clipboard.
- Results are browser-only — nothing is persisted to the server.
- Reuse the Gemini integration and SQLite FTS5 retrieval layer already built in milestones 1 and 2. The model is `gemini-3.1-flash-lite`, exposed as the `GEMINI_MODEL` constant in `main.py` — use that constant, do not hardcode a model name.

Ask me any clarifying questions using the AskUserQuestion tool to lock in the implementation plan for this milestone.
