# askdnd Design Guide

_Last updated 2026-10-15 · Applies to every page in the app. Mockups live in `docs/mockups/`._

askdnd is read before a session and reviewed after one. People open it on a laptop next to Zoom and D&D Beyond, sometimes on a phone. It should feel like a well-kept campaign journal, not an admin panel.

## Principles

1. **Read first, edit on demand.** Saved content shows as finished text. Editing is a deliberate step (an **Edit** button), with **Save** and **Cancel**, and returns to the reading view. A form is never the resting state.
2. **One primary action per step.** Each section has at most one filled (green) button. Everything else is a quiet secondary button or a text link.
3. **Status is always visible.** Every session, recap, question and suggestion shows where it stands (Draft, Published, Answered, Accepted…), in the same place and the same colors everywhere.
4. **Say what happens next.** Buttons are verbs with outcomes ("Publish to the table", "Redraft with answers"), and anything that costs money or is seen by the table says so in a short line beneath.
5. **Story text is for reading.** Recaps and notes use a book-like serif, comfortable line length (about 70 characters) and generous spacing. Controls use the system font.
6. **Calm by default.** Warm paper background, white cards, few borders, color only for status and the primary action. No walls of boxes.
7. **Works on a phone.** One column under 760px, tap targets at least 44px, and the publish action stays reachable at the bottom of the screen.
8. **Never lose work.** Cancel asks before throwing away edits; a changed published recap shows "Edited since publishing" until republished.
9. **Inform, don't advise** (from the product rules). Copy explains what something is or does. It never tells players what to do in the game.

## Review workflow (admin)

The session review page is a short checklist, top to bottom:

1. **Questions from Claude.** Answer, skip, or mark "remember for future drafts". Redraft when there are new answers.
2. **Recap.** Read; edit if needed.
3. **Story events.** Read the list; edit, retype, delete or add individual events inline.
4. **Suggested updates.** People, places and spellings. Accept, edit then accept, or reject.
5. **Publish.**

A sidebar on wide screens (a sticky bottom bar on phones) shows progress through these steps and holds the single **Publish** button.

## Visual system

| Token | Value | Use |
|---|---|---|
| `--paper` | `#f7f4ec` | Page background |
| `--card` | `#ffffff` | Cards |
| `--ink` | `#23211c` | Body text |
| `--muted` | `#6f6a5f` | Secondary text, hints |
| `--line` | `#e6e0d2` | Card borders, dividers |
| `--primary` | `#2c5e3f` | Primary buttons, links, focus rings |
| `--draft` | `#9a6a12` on `#fbf0d6` | Draft / needs attention |
| `--published` | `#2f7d4f` on `#e2f1e6` | Published / accepted / answered |
| `--edited` | `#2f5e9e` on `#e4ecf8` | Edited since publishing / in progress |
| `--danger` | `#a3342b` on `#fbe7e4` | Errors, delete |

- **Type:** UI in `system-ui`; story text in `"Iowan Old Style", "Palatino", Georgia, serif` at 1.05rem / 1.65 line height. Headings in the UI font, semibold.
- **Spacing:** 4px base; cards have 20–24px padding and 16px between them.
- **Radius:** 10px cards, 8px buttons and inputs, 999px pills.
- **Event types** have consistent badges: event (neutral), reveal (purple), decision (blue), loot (gold), theory (dashed outline, italic text, so speculation never looks like fact).

## Components

- **Status pill:** small rounded label using the status colors above.
- **Card:** white, 1px `--line` border, 10px radius, subtle shadow on hover only for interactive cards.
- **Read/Edit block:** reading view plus a quiet **Edit** button in the card's top-right corner; edit mode swaps in the form with **Save** (primary) and **Cancel**.
- **Question card:** question text, then either the saved answer (with **Edit**) or an **Answer** button that opens a text box. A "Remembered" tag shows when the answer feeds future drafts.
- **Suggestion card:** name, kind and "new" tag; old and proposed summaries side by side (stacked on phones); **Accept**, **Edit**, **Reject**. Decided suggestions collapse into a one-line summary.
- **Progress panel:** the checklist with counts ("2 of 3 questions answered"), version and cost line, and the **Publish** button.
- **Flash message:** a one-line confirmation at the top that fades after a few seconds ("Saved", "Published").

## Implementation notes

- Server-rendered Jinja templates; small interactions (Edit/Cancel, inline saves) use HTMX partial swaps so the page doesn't jump to the top.
- Shared CSS lives in one stylesheet with the tokens above as CSS variables; pages don't define their own colors.
- Every interactive element has a visible focus style and a label for screen readers.
