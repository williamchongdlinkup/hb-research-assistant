# Milestone 2 — Grounded Q&A

You are entering plan mode to plan and then build milestone 2 of this project.

## Context

- Read `@_build_plan/prd.md` for the full project context, scope, data model, and tech stack.
- Read `@_build_plan/milestones/1-foundation/milestone-log.md` to understand what was built in milestone 1 and any decisions that affect this milestone.

## Your task

1. Plan the implementation for **only** milestone 2 as defined in the PRD. Do not plan or build anything from later milestones.
2. After the user confirms the plan, build only what is in milestone 2's scope.
3. Verify your work against the "Done when" criteria for milestone 2 in the PRD.
4. When complete, write a `milestone-log.md` in this folder (`_build_plan/milestones/2-grounded-qa/milestone-log.md`) summarizing:
   - What was built (files created or modified, routes added, etc.)
   - Any decisions made during implementation that weren't pre-specified in the PRD
   - Anything milestone 3 will need to know
   - Any deviations from the PRD and why

## Key inputs

- GEMINI_API_KEY is available as an environment variable (set in Railway and in a local `.env` file).
- The Gemini model to use is `gemini-2.0-flash` (free tier).
- The RAG-lite approach: use SQLite FTS5 to pre-filter the corpus to the most relevant ~50 entries per query, then pass those entries + conversation history to Gemini for synthesis. Do not pass the full 1,969-entry corpus in a single context call.
- Responses must be in flowing prose, not bullet lists.
- Every factual claim must be followed by an inline superscript citation number that links to the corpus entry it draws from.
- All AI responses must be grounded in the corpus only — the system prompt must make clear that Gemini should not draw on outside knowledge.

Ask me any clarifying questions using the AskUserQuestion tool to lock in the implementation plan for this milestone.
