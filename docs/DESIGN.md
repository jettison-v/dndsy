# askdnd Design Guide

_Last updated 2026-10-15 · Applies to every page in the app. Mockups live in `docs/mockups/`._

askdnd is read before a session and reviewed after one. People open it on a laptop next to Zoom and D&D Beyond, sometimes on a phone. It should feel like a well-kept campaign journal, not an admin panel.

## Principles

1. **Read first, edit on demand.** Saved content shows as finished text. Editing is a deliberate step (an **Edit** link), with **Save** and **Cancel**, and returns to the reading view. A form is never the resting state.
2. **Only what needs a decision stays open.** Once a question is answered or skipped, or a suggestion is accepted or rejected, it moves into a collapsed **Done (n)** drawer at the bottom of its section. Everything in Done can still be opened, edited or undone.
3. **One primary action per step.** Each section has at most one red button. Everything else is a quiet secondary button or a text link.
4. **Status is always visible**, in the same place and the same colors everywhere (Draft, Published, Edited since publishing, Accepted…).
5. **Say what happens next.** Buttons are verbs with outcomes ("Publish to the table", "Redraft"), and anything that costs money or is seen by the table says so in a short line beneath.
6. **Readable first.** Normal-case text everywhere; no all-caps labels except the logo. Story text uses a book-like serif at a comfortable line length.
7. **Calm and roomy.** Generous padding, few divider lines, color only for status and the one primary action.
8. **Works on a phone.** One column under 800px, tap targets at least 40px, and the publish action pinned to the bottom of the screen.
9. **Never lose work.** Cancel discards only that edit; a changed published recap shows "Edited since publishing" until republished.
10. **Inform, don't advise** (from the product rules). Copy explains what something is or does. It never tells players what to do in the game.

## Navigation

One top bar for everyone (Brett, 2026-10-19, Option 1): story pages on the left, then your table, then Live, **Manage ▾** (for those who can manage) and the account menu.

| Item | Audience | What it is |
|---|---|---|
| **Recap** (home) | Everyone | The pre-session refresher ("Previously on…"): latest recap, key moments, open threads |
| **Sessions** | Everyone | Every published session, newest first |
| **Campaign** | Everyone | People, places, factions, items, quests and the glossary |
| **Map** | Everyone | The Sword Coast, with places marked |
| **Cole ▾** (your character) | Everyone | Switches characters; opens one Character page in the same mode. Modes, switched at the page's top right: **Play** (`/characters/{id}/battle`: options by Action / Bonus action / Reaction, saves, Wild Shape row, On a hit, rolls, Easy to forget, Battle combos), **Sheet** (`/characters/{id}`: numbers strip, abilities and saves, tabs Actions, Spells, Wild Shape, Inventory, Features, Skills & situational, Background) and **Plan** (`/characters/{id}/plan`: tabs Battle combos, Leveling strategy, Personal quests, General notes, Easy to forget, Spell shortlist, Wild Shape shortlist; never the DM) |
| **Party** | Everyone | Party table (names open a short character modal), pooled spells and items |
| **Live** pill | Everyone | When the D&D Beyond copy was last updated; green while Game Mode is on (per browser). Its popover: Game Mode, each character's last refresh and failures, Refresh now, and Refresh everyone (reviewers) |
| **Manage ▾** | Admin and reviewers | Overview and the admin and reviewer pages |

Admin pages say so in their subtitle ("only you can see this page"). Breadcrumbs start at the top-level item (Manage › Review › Session 12). On phones a bottom bar holds Recap, Campaign, Play, Party and More (Sessions, Map, Manage, About, FAQ, sign out), and Play's three columns become Action / Bonus / Reaction tabs. Stars, reminders, shortlists, combos and character notes are never shown to the DM.

## Review workflow (admin)

The session review page is a short checklist, top to bottom:

1. **Claude's questions.** Answer or skip. A "Redraft" prompt appears once there are new answers.
2. **Recap.** Read; edit if needed.
3. **Key moments.** Read the list; edit, retype, delete or add individual events inline.
4. **Suggested updates.** People, places and spellings. Accept, edit, or reject; undo later from Done.
5. **Publish** from the progress panel (sidebar on desktop, bottom bar on phones).

## Visual system

Dark theme, inspired by D&D Beyond (dark chrome, red accents, warm parchment-toned story text) without copying its logo, name or artwork.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#15171a` | Page background |
| `--surface` / `--surface-2` | `#1f2226` / `#272b30` | Sections, panels / buttons, inputs, nested blocks |
| `--line` | `#34383e` | Dividers, borders |
| `--text` / `--muted` / `--faint` | `#ebe7df` / `#a29d93` / `#6f6b64` | Body text / secondary / tertiary |
| `--story-bg` / `--story-text` | `#221f1a` / `#f0e7d4` (border `#3b3428`) | Recaps, answers, proposed text: warm "parchment at night" |
| `--red` | `#d64545` (hover `#e35a5a`) | The one primary button, section numbers, top-bar rule, focus |
| `--amber` | `#e8b34b` | Draft / needs attention |
| `--green` | `#5bbf7f` | Published / accepted / answered / done |
| `--blue` | `#7ea6e0` | Edited since publishing / new |

Status colors are used as text on a 14–15% tint of the same color.

- **Type:** UI in **Inter** (fallback system-ui) at 16px / 1.6; section headings 1.2rem semibold; page titles 1.9rem bold. Story text in `"Iowan Old Style", Palatino, Georgia, serif` at 1.12rem / 1.75. The logo alone uses Roboto Condensed.
- **Shape and space:** 12px radius on sections, 8px on buttons and inputs, pill tags; sections have 28–30px padding and 24px between them.
- **Key-moment types** are colored words, not boxes: Event (muted), Reveal (lavender), Decision (blue), Loot (amber), Theory (italic, muted) so speculation never looks like fact.

## Components

- **Section:** dark surface card with a numbered heading (red number), a one-line hint, then content.
- **Tag:** small rounded pill, status color on a soft tint.
- **Read/Edit block:** reading view plus an **Edit** link in the section header; edit mode swaps in the form with **Save** (primary) and **Cancel**.
- **Question item:** question, then **Answer** / **Skip**. Answered ones move to Done showing the answer in a story-style block, a "Remembered for future drafts" tag when it applies, and **Edit** / **Remove answer**.
- **Suggestion item:** name, kind and "New" tags; Before and Proposed side by side (stacked on phones); **Accept**, **Edit**, **Reject**. In Done, accepted ones show "Now in askdnd" with **Edit** and **Undo** (undo restores the earlier summary).
- **Done drawer:** collapsed "▸ Done (n)" line at the bottom of a section.
- **Progress panel:** checklist with counts and the single **Publish** button; becomes a bottom bar on phones.
- **Toast:** short confirmation near the top ("Answer saved", "Published").

## Implementation notes

- Server-rendered Jinja templates; small interactions (Edit/Cancel, answer, accept, undo) use HTMX partial swaps so the page doesn't jump.
- One shared stylesheet with the tokens above as CSS variables; pages don't define their own colors.
- Every interactive element has a visible focus style and an accessible label.
- Mockups in `docs/mockups/` use made-up content only.

## Section headings (2026-10-18)
Section headings are all-caps, letter-spaced labels in amber with a fading rule (`h3.divider`). Only the action economy is color-coded, the same everywhere: ◆ red **Action**, ▲ amber **Bonus action**, ↺ blue **Reaction**, ● violet **Other** (classes `k-action`, `k-bonus`, `k-reaction`, `k-other`). Don't add more colors for other kinds of sections; the point is that color means "what it costs on your turn".
