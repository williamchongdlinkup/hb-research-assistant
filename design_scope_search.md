# Design Scope — Smart Search & Query-Interpretation UI

**Product:** HB Research Assistant (Nan Tien Institute) · Search tab
**Author:** Senior Product/UX review
**Status:** Scoping. No code changes here — this is a build brief.
**Constraint:** Stays a single Tailwind-CDN HTML page (`index.html`) + FastAPI (`main.py`). No framework change. Brand crimson `#b01116` (`brand`), warm paper `#faf8f5` (`paper`). Latin-script, English-only synonyms (the `_CJK_RE` filter in `main.py` already strips CJK from `alts` — keep that).

---

## 0. The trigger for this review

A first-time, non-technical humanities scholar typed a query, saw the panel rendered by `renderInterpretation()` (index.html ~L502–553), and asked:

> "What does 'Interpreted as / Must: Tzu Chi / +Ciji' mean?"

That single question is the whole problem. The feature works mechanically (the LLM → `/api/smart-search` → chips → `/api/structured-search` loop is solid), but its **vocabulary and visual model are Boolean-engineer jargon** ("Must", "Any", "+synonym", chips). The tool must be self-evident to someone who has never read a manual and does not think in AND/OR.

This document scopes the redesign of the **Search bar + Smart-search controls + interpretation panel + states**, ranked for action.

---

## 1. Target user & first-run experience

### Who they are
- A humanities scholar / postgrad / visiting researcher studying Humanistic Buddhism.
- Comfortable with Google Scholar and library catalogues; **not** comfortable with Boolean operators, "facets", "tokens", or chip-based query builders.
- English-reading. May know romanized HB terms (Fo Guang Shan, Tzu Chi) but is *unsettled*, not helped, by Chinese characters — hence the Latin-only rule.
- Arrives via the landing-page "Search" card (index.html L94–106), whose own copy says *"Browse and filter… by keyword, author, year, and publication type"* — which **undersells** and **mis-describes** the new natural-language capability. (Fix in §7.)

### What they see in the first 5 seconds (current state)
1. A search box pre-loaded with results — `init()` calls `doSearch()` on boot (L376–380), so the user lands on page 1 of all 1,833 entries browsed by year. Good: never an empty screen.
2. A placeholder: *"Describe what you're looking for — e.g. "Reinke on Fo Guang Shan globalization after 2015, not secular""* (L181). This is actually a strong cue — keep its spirit.
3. A checkbox **"✨ Smart search (AI)"**, checked, with a hover-only `title` tooltip (L192–196). A non-technical user does **not** know what "Smart search" does, and tooltips are invisible on touch and easy to miss on desktop.
4. Year-from / to / Type filters inline (L198–213).
5. **Nothing tells them what to type or what will happen after they type.** The interpretation panel (`#interpretation`, L221) is empty until after a search.

### The first-run gap
The user must *act blindly first* (type something, hit Search) before the tool reveals its model (chips appear). First impressions of an AI feature should be **front-loaded**, not post-hoc. We need guidance that appears **before** the first query.

### Proposed first-run guidance (all additive, all in the existing card UI)

**a) A one-line "how this works" strip** under the search bar, shown only on the Search tab before the first user-initiated query (hide after first `triggerSearch()`):
> *Ask in plain English — like "books on compassion and social action since 2015." We'll find the right entries and show you exactly how we read your request, so you can fine-tune it.*

Style: `text-xs text-gray-500`, with a small `✨` in `text-brand`. Warm, academic, no jargon.

**b) Example-query chips** (clickable, populate the box and run): three real examples drawn from the corpus's strengths. These double as the **empty-state teacher** — the user learns the input format by clicking one and watching the interpretation panel build.
> Try: [ Compassion and social engagement ] [ Sheng Yen, since 2010 ] [ Fo Guang Shan globalization, not secular ]

Place them in the `#interpretation` slot region on first load (the panel is otherwise empty pre-search).

**c) Placeholder** — keep the current example-driven placeholder; it is the single best existing cue. Minor: curly quotes render oddly in some fonts — keep but verify.

**d) Empty/zero-results state** already exists (`renderResults()` L614–624) but is generic. Upgrade it to *recover* (see §5).

---

## 2. Heuristic critique of the current Search UI

Grounded in the actual elements. Using Nielsen's heuristics.

### H2 — Match between system and the real world (the core failure)
- **"Must:" / "Any:" labels** (`renderInterpretation`, L522 & L529). These are Boolean quantifiers. A scholar reads "Must: Tzu Chi" and asks "must… what?" The mental model (AND-group vs OR-group) is invisible.
- **"+Ciji" synonym sub-tags** (L519–521, L526–528). The bare `+` prefix is symbolic shorthand with zero affordance explaining it means "we also searched this related spelling". The user's literal question proves it fails.
- **"Interpreted as"** (L545) is passable but cold/technical; "interpreted" implies the user said something ambiguous that needed decoding.
- **"Search literally instead"** (L547) — "literally" is a power-user distinction (NL vs keyword). A layperson doesn't know they did a *non*-literal search.

### H1 — Visibility of system status
- **Loading:** `showInterpreting()` (L496–500) shows "Interpreting your query…" with a tiny spinner — good, this covers the 1–2s LLM latency. The results-area spinner `#loading-spinner` (L229, `showSpinner`) is separate and small/top-right; on a fresh smart search both fire. Acceptable but the two spinners aren't visually unified.
- **"Results updated" feedback:** when a chip is removed, `runStructured()` → `fetchStructured()` re-renders silently (L556–593). The result count changes but there is **no transient confirmation** that *the removal caused it*. The instruction text says "results update instantly" (L551) but nothing visibly *announces* the update. Low discoverability of cause→effect.

### H3 — User control & freedom
- Chips are **removable but not addable**. A user who sees we missed "globalization" cannot add a term except by rewriting the whole query. One-directional editing.
- Removing the **last** term lands in an "all terms removed" state (L549–550) showing *everything* matching filters — correct logic, but the message is buried.
- No undo after removing a chip.

### H4 — Consistency & standards
- The interpretation chips use **six different colour families** (indigo author, brand must, blue any, rose exclude, gray years/type — L516, L522, L529, L533, L538, L540). That's a lot of unexplained colour semantics for a novice. Meanwhile result-card type badges use *yet another* palette (`TYPE_COLORS`, L629–636). Colour is doing semantic work with no legend.

### H5 — Error prevention / H9 — Recover from errors
- **Silent AI fallback** (the big one). When Gemini is unavailable, `_structure_query()` returns `None`, `/api/smart-search` sets `fallback: true` and `interpretation: null` (main.py L667–671, L680–685). The UI does show an amber line — *"AI interpretation was unavailable — showing a literal keyword search instead"* (L504–506) — which is good and honest. **But** the toggle stays checked, so the next query silently tries AI again, and the user has no idea their "smart" results were actually dumb keyword results unless they read the small amber text. The message is correct; its **prominence is too low** for a trust-critical event.
- The empty-query smart case is handled well: `doSearch()` only uses smart mode when `state.q.trim()` is non-empty (L409) — filters-only browse never calls the LLM. Good.

### H6 — Recognition over recall
- The user must **recall** what they typed to understand the chips, because the original query text isn't echoed near the interpretation. There's no "You asked: …" line.

### H8 — Aesthetic & minimalist design
- The interpretation block crams: "Interpreted as" + N chips + "Search literally instead" link + a second helper paragraph (L543–551), all at `text-xs`. Dense, low-contrast (`text-gray-400`), and the actionable "Search literally instead" link sits *between* content and helper text where it reads like a chip.

### Mobile / responsive
- Filters row (L191–218) is `flex flex-wrap` — on narrow screens the year inputs, type select, and toggle wrap into a tall stack; the `Clear all` button uses `ml-auto` (L214) which on a wrapped line floats oddly.
- Chips wrap (`flex-wrap`, L544) — OK — but the tiny `×` buttons (`opacity-60`, font-size from `text-xs`, L512/L520) are **below the ~44px touch target** and hard to tap precisely, especially the per-synonym `×`.
- Pagination buttons (L707–722) are fine-sized; result cards are responsive.

### Summary of worst offenders
1. "Must / Any" labels (jargon, no model).
2. "+synonym" bare-plus tags (the literal confusion).
3. Silent/low-prominence AI fallback.
4. No echo of the user's query; no add-term affordance; weak update feedback.
5. Tooltip-only explanation of the Smart-search toggle.

---

## 3. Plain-language relabeling (before → after)

| Current (jargon) | Recommended microcopy | Rationale |
|---|---|---|
| `Interpreted as` | **Here's how I read your request:** | Conversational, first-person assistant; frames it as the AI explaining itself, not a system label. |
| `Must: Tzu Chi` | Part of a sentence: **"…about **Tzu Chi**…"** rendered as a highlighted term inside a readable sentence (see §4). If chips are retained: **"Topic: Tzu Chi"** (no "Must"). | "Must" → the everyday idea of "what it's about". |
| `Any: globalization` (OR group) | **"…about either **globalization** or **localization**…"** — joined by the word *or* in the sentence. If chips: group them visually under **"Any of these:"**. | Replace the Boolean OR with the literal word "or". |
| `+Ciji` (synonym sub-tag) | **"Tzu Chi *(also searched: Ciji)*"** — spelled out, italic, in parentheses; the × becomes "remove this spelling". | Kills the cryptic `+`. States plainly we expanded the search. |
| `Exclude: secular` | **"…but not **secular**."** or chip **"Leaving out: secular"** | "Exclude" → "leaving out / not". |
| `Author: Reinke` | **"…written by **Reinke**…"** or chip **"Author: Reinke"** (author is the one term laypeople *do* understand — safe to keep). | Keep, but fold into the sentence. |
| `Years: since 2015` | **"…published since 2015."** | Already plain — fold into sentence. |
| `Type: Book` | **"…(books only)."** | Already plain. |
| `Search literally instead` | **"Search my exact words instead"** (+ tiny helper: *"turn off smart reading"*). | "Literally" is confusing; "my exact words" is concrete. |
| `✨ Smart search (AI)` toggle | **"✨ Understand my question"** with persistent helper *"(reads plain English — turn off to match exact words)"* — not tooltip-only. | Tells the user what it *does*, visibly. |
| Helper: *"Remove any term or synonym (×) to refine"* | **"Not quite right? Remove anything below (×) and I'll update the results."** | Friendly, action-led. |
| `Interpreting your query…` | **"Reading your request…"** | Warmer; "query" is technical. |
| Fallback: *"AI interpretation was unavailable…"* | **"Smart reading is offline right now — I searched your exact words instead."** (see §5 for prominence) | Honest, plain, no "AI interpretation". |
| Empty state: *"All search terms removed…"* | **"No topics left — showing everything that fits your filters. Add a topic by searching again."** | Tells them how to recover. |

---

## 4. The interpretation panel — redesign

**Goal:** make "here's how I understood you, and you can adjust it" self-evident, with no Boolean words and no `+`.

### Principle: a sentence first, chips second
Lead with a **plain-English restatement** — and we already have it for free. The model returns a `summary` field (main.py L486, L568, surfaced as `interpretation.summary`). The current UI **ignores `summary` entirely**. Use it as the headline.

```
Here's how I read your request:
  "Work written by Reinke about Fo Guang Shan globalization,
   published since 2015, leaving out anything secular."
                                          [ Search my exact words instead ]
```

Below the sentence, show the **adjustable pieces** as labelled, grouped, removable tags — but relabeled and grouped so AND vs OR is conveyed by **layout + connective words**, not colour codes the user must decode.

### Conveying AND vs OR without Boolean words
- **AND (must group):** stack each topic on the idea of *"all of these"*. Header: **"Must mention all of these:"** Each topic is one tag. Visually a vertical/inline list — items read as a checklist (all required).
- **OR (any group):** only render when present. Header: **"…and at least one of these:"** Tags sit inside a single bordered pill-group so they visually cohere as alternatives. The header word "one of" carries the OR meaning.
- This mirrors natural language ("all of these AND one of these") without ever printing "AND"/"OR".

### Showing synonyms without "+"
Render expansions inline, spelled out, de-emphasised:
> **Fo Guang Shan**  ·  *also searching: Foguangshan, FGS*  ✕

The "✕" on the parent removes the topic; each synonym gets a subtle individual "remove" on hover/focus (keep the `removeAlt` capability, L557) but label it **"don't search this spelling"** via `title`/`aria-label`, and make the control a real ≥44px tap target.

### Editing / removal that feels safe
- Each tag's remove control: a clear ✕ inside a padded button, `aria-label="Remove '<term>'"`. On removal, animate the tag out (fade), and show a **transient inline toast**: *"Removed 'secular' — updated to 412 results"* near the result count for ~2.5s. This closes the cause→effect gap (H1).
- Add an **"+ Add a topic"** affordance (the missing inverse of removal). Clicking reveals a tiny text input; on Enter it pushes a `{term, alts:[]}` into `state.interpretation.must` and calls `runStructured()`. This reuses the existing structured-search path (no new endpoint) and fixes the one-directional-editing flaw (H3).
- Keep **"Search my exact words instead"** but move it to the top-right of the panel as a quiet secondary action, not mid-content.

### Echo the query (recognition over recall)
Because the `summary` *is* a restatement, an explicit "You asked:" echo is optional. If `summary` is empty (e.g. on `/api/structured-search`, which returns `summary: ""` — main.py L738), fall back to showing the raw query the user typed.

### Colour discipline
Collapse the six chip palettes to **two roles**: brand-tinted for *topics you're searching for* (must/any/author), and a muted gray-with-strikethrough motif for *excluded* ("leaving out"). Years/Type as plain gray "filter" tags. This is learnable at a glance and consistent with the result-card aesthetic.

---

## 5. States

### Loading (LLM adds 1–2s)
- Keep `showInterpreting()` but relabel to **"Reading your request…"** and make it visually the *same* spinner+panel that will hold the answer, so the panel doesn't jump. Disable the Search button (`#search-btn` already has `disabled:opacity-50`, L187) during the call to prevent double-fires.
- Consider a one-line skeleton (gray shimmer where the summary sentence will land) so the layout is stable.

### Zero results (recover / broaden)
Current `renderResults()` empty state (L614–624) is generic. Make it **active**:
> **No entries matched.** This can happen when several required topics are combined.
> Try: remove a topic above · widen the year range · or [Search my exact words].

When in structured mode with multiple `must` concepts, specifically suggest *"Your search requires all of: X, Y, Z — try removing one."* (We know the concepts client-side from `state.interpretation`.)

### Error / AI-unavailable fallback (must be visible)
Today the fallback message (L504–506) is a small amber line *inside* the interpretation panel. Elevate it:
- Render a distinct, full-width **notice banner** above results (amber, like the chat 503 styling already in the codebase, e.g. `bg-amber-50 border-amber-200`, used at L276): **"Smart reading is offline right now — I searched your exact words instead. Results may be less precise."**
- Auto-flip the toggle label or add a small "Retry smart reading" link, so the user understands subsequent searches and can re-attempt.
- Distinguish the two failure modes the backend produces: (a) `fallback:true` with `interpretation:null` from `/api/smart-search` (L667–685), vs (b) hard fetch error in `doSearch()`'s catch (L436–441). Today (b) shows a red "Could not load results" box and hides interpretation — fine — but the copy could match the new voice.

### "All terms removed"
Handled logically (L542, L549–550) but reframe per §3: **"No topics left — showing everything that fits your filters. Search again to add a topic."** Offer a one-click **"Restore my search"** (re-run `triggerSearch()` with the original `state.q`) so an accidental over-removal is reversible (addresses the no-undo gap).

---

## 6. Low-fidelity wireframes (ASCII)

### (a) Search bar + controls + first-run guidance

```
┌──────────────────────────────────────────────────────────────────────────┐
│  🔍  Describe what you're looking for — e.g. "compassion and social     │  ← #search-input
│      action since 2015"                                      [  Search ]  │  ← #search-btn (brand)
├──────────────────────────────────────────────────────────────────────────┤
│  ✨ Understand my question        Year from [    ] to [    ]  Type [▼]    │
│     (reads plain English — turn off to match exact words)      Clear all  │  ← persistent helper, not tooltip
├──────────────────────────────────────────────────────────────────────────┤
│  ✨ Ask in plain English and I'll find the right entries — and show you    │  ← one-line "how this works"
│     exactly how I read your request, so you can fine-tune it.              │     (first run only)
│                                                                            │
│  Try:  [ Compassion & social engagement ]  [ Sheng Yen, since 2010 ]      │  ← clickable example chips
│        [ Fo Guang Shan globalization, not secular ]                       │
└──────────────────────────────────────────────────────────────────────────┘
```

### (b) Interpretation / refinement panel — redesigned

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Here's how I read your request:            [ Search my exact words ↩ ]   │
│  ──────────────────────────────────────────────────────────────────────  │
│  "Work written by Reinke about Fo Guang Shan globalization, published     │  ← summary sentence (plain English)
│   since 2015, leaving out anything secular."                              │
│                                                                            │
│  Must mention all of these:                                               │
│   ┌───────────────────────────────────────────┐  ┌──────────────────┐    │
│   │ Fo Guang Shan   also searching: Foguangshan, FGS            ✕ │  │ globalization  ✕ │  │
│   └───────────────────────────────────────────┘  └──────────────────┘    │
│                                                                            │
│   …and at least one of these:   ┌─────────────┐ ┌─────────────┐           │  ← only if `any` present
│                                 │ diaspora  ✕ │ │ overseas ✕ │           │
│                                 └─────────────┘ └─────────────┘           │
│                                                                            │
│   Written by:  [ Reinke ✕ ]     Since: [ 2015 ✕ ]    [ + Add a topic ]    │
│   Leaving out:  s̶e̶c̶u̶l̶a̶r̶  ✕                                                  │
│                                                                            │
│   Not quite right? Remove anything above (✕) and I'll update instantly.   │
└──────────────────────────────────────────────────────────────────────────┘
        ↓ (on removal)
   ╭ Removed "secular" — updated to 412 results ╮   ← transient toast by the count
```

### (c) Result item (largely keep current `renderCard`, L642–689)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [Journal Article]  2018                                            ⌄     │  ← type badge + year + expand chevron
│  Fo Guang Shan and the Globalisation of Humanistic Buddhism                │  ← title (font-semibold)
│  Reinke, J.  · Journal of Global Buddhism                                  │  ← author_display · venue
│                                                                            │
│  Excerpt: This article examines how Fo Guang Shan's transnational …       │  ← abstract_excerpt (collapsed)
│  ▸ expands to full abstract + "View source ↗"                             │
└──────────────────────────────────────────────────────────────────────────┘
```
Result cards are already well-designed; the only suggested change is **highlighting matched terms** in title/excerpt (bold the `must` terms) so the user sees *why* an entry matched — reinforcing the interpretation. Optional, medium effort.

---

## 7. Prioritized recommendations (impact × effort)

Each tied to the first-time-user goal: *understand what to type, understand what came back, and trust it.*

| # | Change | Impact | Effort | Why it matters to a first-timer |
|---|---|---|---|---|
| **Quick wins** |
| Q1 | **Relabel "Must/Any/+/Interpreted as/Search literally"** per §3 in `renderInterpretation()`. | ★★★★★ | Low | Directly removes the jargon that caused the user's confusion. Pure string edits. |
| Q2 | **Lead the panel with the `summary` sentence** (already returned, currently unused). | ★★★★★ | Low | One plain sentence explains the whole search before any tags. Biggest comprehension gain per line of code. |
| Q3 | **Spell out synonyms** as "also searching: Foguangshan, FGS" instead of "+Ciji". | ★★★★☆ | Low | Kills the exact "+Ciji" confusion reported. |
| Q4 | **Persistent helper under the toggle** ("reads plain English — turn off to match exact words") instead of tooltip-only. | ★★★★☆ | Low | Explains the default-on AI mode without a hover. |
| Q5 | **Promote the AI-fallback notice** to a visible banner above results. | ★★★★☆ | Low | Trust: user knows when they're getting keyword (not smart) results. |
| Q6 | **Active zero-results copy** ("remove a topic / widen years / exact words"). | ★★★☆☆ | Low | Turns a dead end into a recovery path. |
| **Larger bets** |
| L1 | **First-run guidance**: one-line "how it works" + clickable example chips in the empty `#interpretation` slot. | ★★★★★ | Med | Teaches the input format *before* the first blind attempt — the single biggest first-run fix. |
| L2 | **AND/OR via grouped layout + connective words** ("must mention all of these" / "at least one of these"). | ★★★★☆ | Med | Conveys the logic model without Boolean vocabulary. |
| L3 | **"+ Add a topic" affordance** + transient "updated to N results" toast. | ★★★★☆ | Med | Two-way editing and visible cause→effect; closes H3/H1 gaps. Reuses `/api/structured-search`. |
| L4 | **Restore/undo** after over-removal; touch-target sizing for ✕ controls; collapse chip palette to 2 roles. | ★★★☆☆ | Med | Safety + mobile usability + less colour to decode. |
| L5 | **Highlight matched terms** in result titles/excerpts. | ★★★☆☆ | Med | Shows *why* each result matched; reinforces the interpretation. |
| L6 | **Fix landing-page Search card copy** (L102) to mention plain-English / smart search, not just "keyword, author, year, type". | ★★★☆☆ | Low | Sets the right expectation before the user even reaches the box. (Quick-win-sized; grouped here as it's content strategy.) |

**Recommended sequence:** ship Q1–Q6 together (one afternoon of microcopy + the `summary` headline + fallback banner — these alone resolve the reported confusion), then L1 (first-run), then L2–L3, then L4–L6.

---

## 8. Brand & consistency notes

- All new copy stays **warm-academic, first-person assistant** ("Here's how I read your request…", "I searched your exact words") — matches the existing chat voice ("Searching corpus and composing response…", L835) and the paper/crimson aesthetic.
- Reuse existing tokens: `text-brand` for emphasis, `bg-brand/5 border-brand/15` panels (as the chat/audit intro cards use, L244, L294), `bg-amber-50 border-amber-200` for the fallback notice (matches L276), `rounded-lg`/`rounded-xl`, `text-xs`/`text-sm` scale. No new colours, no new fonts.
- Keep the **Latin-only synonym rule** — `_CJK_RE` filtering in `_norm_concept_list` (main.py L539) and `_extract_terms` already enforce it; the redesign must not reintroduce CJK in the "also searching:" line.
- Everything proposed is achievable within the single HTML page + the three existing endpoints (`/api/smart-search`, `/api/structured-search`, `/api/search`). No backend contract change is required for Q1–Q6, L1, L2, L4, L5; "+ Add a topic" (L3) reuses `/api/structured-search` as-is.

---

*End of scope.*
