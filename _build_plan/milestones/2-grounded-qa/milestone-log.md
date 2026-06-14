# Milestone 2 — Grounded Q&A: Complete

**Date completed:** 2026-06-14
**Status:** Built and locally verified (server starts, search unaffected, /api/chat returns 503 without key as expected). Full AI test pending GEMINI_API_KEY setup.

---

## What was built

### Files modified

| File | Change |
|---|---|
| `requirements.txt` | Added `google-genai>=1.0.0`, `python-dotenv>=1.0.0` |
| `main.py` | Added Gemini client, ChatRequest model, `_retrieve_for_query`, `_build_system_prompt`, `POST /api/chat` |
| `index.html` | Added tab nav (Search / Q&A Chat), full Q&A chat section, all chat JS |

### New API route

| Route | Description |
|---|---|
| `POST /api/chat` | RAG-lite chat: FTS5 retrieves top-50 corpus entries → Gemini `gemini-3.1-flash-lite` generates grounded prose response with `[N]` citations → returns `{answer, citations, sources_count}` |

### Frontend features (Q&A tab)

- Tab bar: Search | Q&A Chat (toggle, Search active by default)
- Intro hint card with example question (hidden after first send)
- Conversation thread grows downward with each turn
- User messages: right-aligned brand-coloured bubble
- Typing indicator while Gemini is generating
- AI response card: flowing prose with superscript `[N]` links
- "Based on N entries from the HB corpus" label per response
- Collapsible "References (N)" section below each response
  - Each citation: `[N]` number, author, year, title, venue
  - "Show abstract" toggle → full abstract inline
  - "View source ↗" link if URL available
- Turn counter ("Turn X of 5") updates after each round
- After turn 5: input hidden, "Start new conversation" button shown
- "New conversation" button resets state and restores intro hint
- Enter key sends (Shift+Enter = new line)
- Graceful error card for network or AI errors

---

## Decisions made during implementation

**1. Switched from `google-generativeai` to `google-genai`**
The `google-generativeai` package (v0.8.x) throws a FutureWarning on import: all support has ended. The new unified SDK is `google.genai` (package: `google-genai>=1.0.0`). Switched to `client.chats.create()` + `genai_types.GenerateContentConfig(system_instruction=...)` pattern.

**2. Gemini client is module-level, not created per-request**
`_gemini_client = genai.Client(api_key=GEMINI_API_KEY)` is initialised at module load time if the key is present. Returns 503 if not. This is safe since the client is stateless and thread-safe.

**3. FTS5 re-retrieval per turn**
Each turn re-runs FTS5 against the new message and retrieves a fresh top-50. Citation numbers `[N]` reset to 1 at each turn; the frontend shows each response with its own scoped reference list. This is simpler and more accurate than fixing the retrieved set for the whole conversation.

**4. History passed verbatim to Gemini**
Previous AI responses in history contain `[N]` notation from a prior retrieval. These are passed to Gemini as-is. The system prompt for each turn lists fresh entries numbered from 1, and in practice conversation follow-ups are on related topics so the top-50 entries largely overlap between turns. Acceptable for a 5-turn demo.

**5. Citation parsing is frontend-only**
The backend returns `answer` (raw text with `[N]` notation) and `citations` (array of `{number, entry}`). The frontend transforms `[N]` → `<sup><a href="#ref">...</a></sup>` and renders the reference list. The backend doesn't produce HTML — this makes the API cleaner and easier to test.

**6. Paragraph rendering**
The frontend converts double-newlines in the answer to `</p><p>` tags so Gemini's natural paragraph breaks render correctly in HTML. Single newlines become `<br>`.

**7. `.env` / `python-dotenv` for local dev**
`load_dotenv()` is called at module level. On Railway, `GEMINI_API_KEY` is injected as an environment variable directly — `load_dotenv()` is a no-op in that context. Locally, a `.env` file in the project root is loaded automatically.

---

## Pre-deployment steps (for William)

### 1. Create local `.env` file

Create `interactiveBibliography/.env` with:
```
GEMINI_API_KEY=your-gemini-api-key-here
```

Get a free key at https://aistudio.google.com → API Keys.

`.env` is already in `.gitignore` — it will NOT be committed.

### 2. Add key to Railway

In Railway dashboard → your project → Variables → Add:
```
GEMINI_API_KEY = your-gemini-api-key-here
```

Or via CLI:
```
railway variables set GEMINI_API_KEY=your-key-here
```

### 3. Deploy

```
git push origin HEAD:main
```

---

## What Milestone 3 needs to know

- **`_retrieve_for_query(query, limit)` is reusable** — M3's reference audit can call this same helper to find relevant corpus entries for a pasted bibliography.
- **`_entry_to_dict(row)`** returns full entry metadata including `author_display`, `abstract_excerpt`, `url`, etc. M3 can reuse this for displaying audit results.
- **No session state on the server** — both M2 chat and M3 audit are stateless; all state lives in the browser.
- **The Gemini client is `_gemini_client`** at module scope. M3 can call `_gemini_client.models.generate_content(...)` for single-turn audit analysis (no chat session needed).
- **Corpus actual size: 1,833 entries** (not 1,969 from PRD estimate).

---

## Deviations from PRD

| PRD spec | Actual |
|---|---|
| `google-generativeai` SDK | Used `google-genai` (new unified SDK) — old package is deprecated with no further updates |
| `gemini-2.0-flash` model | Used `gemini-3.1-flash-lite` — intentional upgrade to a newer, faster lightweight model; verified working live 2026-06-15 |
| Citation numbers link to corpus entries | Citations link to reference list anchors within the response card (not directly to search results page) |
