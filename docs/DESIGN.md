# askdnd Design Guide

_Last updated 2026-10-22 · Applies to every page in the app. The living component page (**Manage › Design system**, `/manage/design`) shows every token and component with the app's own styles; old mockups are archived in `docs/mockups/archive/`._

askdnd is read before a session and reviewed after one. People open it on a laptop next to Zoom and D&D Beyond, sometimes on a phone. It should feel like a well-kept campaign journal, not an admin panel.

## Principles

1. **Read first, edit on demand.** Saved content shows as finished text. Editing is a deliberate step (an **Edit** link), with **Save** and **Cancel**, and returns to the reading view. A form is never the resting state.
2. **Only what needs a decision stays open.** Once a question is answered or skipped, or a suggestion is accepted or rejected, it moves into a collapsed **Done (n)** drawer at the bottom of its section. Everything in Done can still be opened, edited or undone.
3. **One primary action per step.** Each section has at most one red button. Everything else is a quiet secondary button or a text link.
4. **Status is always visible**, in the same place and the same colors everywhere (Draft, Published, Edited since publishing, Accepted…).
5. **Say what happens next.** Buttons are verbs with outcomes ("Publish to the table", "Redraft"), and anything that costs money or is seen by the table says so in a short line beneath.
6. **Readable first.** Normal-case text everywhere; all-caps only for the logo and divider labels. Story text uses a book-like serif at a comfortable line length.
7. **Calm and roomy.** Generous padding, few divider lines, color only for status and the one primary action.
8. **Works on a phone.** One column on phones (640px and below), tap targets 44px, and the publish action pinned to the bottom of the screen.
9. **Never lose work.** Cancel discards only that edit; a changed published recap shows "Edited since publishing" until republished.
10. **Inform, don't advise** (from the product rules). Copy explains what something is or does. It never tells players what to do in the game.

## Navigation

One top bar for everyone (Brett, 2026-10-22, Option B; `docs/mockups/menu-bar.html`), in two groups that match the data: the campaign (its name, **Story**, **Campaign**), then the people at the table (your character, **Party ▾**), then Live, **Manage ▾** (for those who can manage) and the account menu. The play area (map and combat, VTT) will be one more item in the table group, next to Party.

| Item | Audience | What it is |
|---|---|---|
| Campaign name | Everyone | Always shown, right of the logo. A plain label with one campaign; with two or more, the switcher (your role in each other campaign beside its name) |
| **Story** (home) | Everyone | Tabs **Previously on…** (the pre-session refresher: questions for you, then the latest recap, key moments, open threads) and **All sessions** (every published session, newest first); `?tab=sessions` picks the second. The old `/sessions` address redirects |
| **Campaign** | Everyone | Tabs **World** (the Reader for people, places, factions, items and creatures; `?open=<id>` is an entry's address), **Quests** (the quest log: Open or Done down the left, one quest's journal on the right), **Relationships** (family trees, other ties, anyone's connections), **Glossary** and **Map** (the Sword Coast; `?tab=map&at=<place>` centers it, which is where **Show on map** goes; the old `/map` redirects); `?tab=` picks one |
| **Cole** (your character) | Anyone with a character in this campaign (not the DM) | Portrait and name, one click to your character in the mode you used last (kept in the session). Modes, switched at the page's top right: **Battle** (`/characters/{id}/battle`: options by Action / Bonus action / Reaction, saves, Wild Shape row, On a hit, rolls, Reminders, Battle combos), **Sheet** (`/characters/{id}`: numbers strip, abilities and saves, tabs Actions, Spells, Wild Shape, Inventory, Features, Skills & situational, Background) and **Plan** (`/characters/{id}/plan`: tabs Battle combos, Leveling strategy, Personal quests, General notes, Reminders, Spell shortlist, Wild Shape shortlist; never the DM) |
| **Party ▾** | Everyone | A menu: each character with portrait, class and level, and HP when known ("You" on yours); a character opens in the mode you're in. Then **Everyone at a glance**: the Party page (party table, names open a short character modal; pooled spells and items) |
| **Live** pill | Everyone | When the D&D Beyond copy was last updated; green while Game Mode is on (per browser). Its popover: Game Mode, each character's last refresh and failures, Refresh now, and Refresh everyone (reviewers) |
| **Manage ▾** | Admin and reviewers | Overview and the admin and reviewer pages |
| **Table rolls** sidebar | Everyone, while Game Mode is on | Left sidebar on every page (`_table_rolls.html`, 340 px): open on Battle, a 64 px rail elsewhere and below 1100 px, a bottom sheet on phones; remembered per device. Newest activity first, a roll and its damage / reroll / added die as one entry; a dice tray and your character's quick checks at the bottom. Others' rolls as fading notices while it's collapsed |
| **Roll window** | Everyone | Opens next to any roll button (bottom of the screen on phones): Normal / Advantage / Disadvantage with the reasons, situational bonuses, who sees it; then the result with the d20 tumble and its follow-ups |

Admin pages say so in their subtitle ("only you can see this page"). Breadcrumbs start at the top-level item (Manage › Review › Session 12). On phones the top bar keeps the logo, the campaign's name and Live, and a bottom bar holds Story, Campaign, your character, Party (the same menu, from the bottom) and More (other campaigns, Your suggestions, Manage, About, FAQ, sign out), and Battle's three columns become Action / Bonus / Reaction tabs. Pins, reminders, shortlists, notes, combos and character notes are never shown to the DM.

## Review workflow (admin)

The session review page is a short checklist, top to bottom:

1. **Claude's questions.** Answer or skip. A "Redraft" prompt appears once there are new answers.
2. **Recap.** Read; edit if needed.
3. **Key moments.** Read the list; edit, retype, delete or add individual events inline.
4. **Suggested updates.** People, places and spellings. Accept, edit, or reject; undo later from Done.
5. **Publish** from the progress panel (sidebar on desktop, bottom bar on phones).

## Visual system

Dark only (Brett, 2026-10-22), inspired by D&D Beyond (dark chrome, red accents, warm parchment-toned story text) without copying its logo, name or artwork. Every value below is a token in `app/static/app.css` `:root`; pages use the names, never the values. `tests/test_design_system.py` fails on a text size, color or screen width outside the tokens. Sizes in `em` are allowed (they scale a parent that uses a token).

**Colors**

| Token | Use |
|---|---|
| `--bg` · `--surface` · `--surface-2` | Page · sections and panels · buttons, inputs, nested blocks |
| `--line` · `--line-strong` · `--chrome` | Dividers and borders · stronger rules, swatch edges · the top bar |
| `--text` · `--text-strong` · `--muted` · `--faint` · `--link` | Body · white on red and headings that need it · secondary · tertiary · links |
| `--story-bg` · `--story-line` · `--story-text` | Recaps, answers, proposed text: warm "parchment at night" |
| `--red` (`--red-hover`, `--red-soft`) | The one primary button, the top-bar rule, focus |
| `--amber` · `--green` · `--blue` (each with `-soft`) | Draft or needs attention · published, done · edited since publishing, new |
| `--violet` (`--violet-soft`) | Reminders (the bell) |
| `--k-action` · `--k-bonus` · `--k-reaction` · `--k-other` | The action economy, the only colored headings (see Section headings) |

Status colors are text on their `-soft` tint.

**Text sizes** (Brett, 2026-10-22): `--fs-xs` 12px labels, secondary lines and tags · `--fs-sm` 14px list cells, chips, controls · `--fs-md` 16px body and a row's name · `--fs-lg` 19px section headings · `--fs-xl` 26px the character's name · `--fs-2xl` 30px page titles. UI in **Inter** (fallback system-ui) at 16px / 1.6; story text in `"Iowan Old Style", Palatino, Georgia, serif` at `--fs-lg` / 1.75. The logo alone uses Roboto Condensed.

**Space:** a 4px scale, `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 24 · `--sp-6` 32. Prefer `gap` on flex and grid over margins between siblings.

**Corners:** `--r-sm` 6px small chips and inner boxes · `--r-md` 8px buttons and inputs · `--r-lg` 12px sections, cards, panels · `--r-pill` tags, chips, counts.

**Controls:** search boxes, selects and regular buttons are `--control-h` tall (32px on desktop, 44px on phones; Brett, 2026-10-22); small buttons `--control-h-sm` (26 / 36px); chips `--chip-h` (28 / 36px). Fields use 16px text on phones so iPhones don't zoom in.

**Panels and modals** (four sizes, chosen by what's inside): side panel `--panel-w` 420px (details for one thing; also inside a modal) · modal `--modal-w` 720px (a form or short content) · large `--modal-lg-w` 1180px (rich content in columns: a Wild Shape form, a combo, a leveling plan) · full window `--modal-full-w` 95% (a whole tool with its own list, the Spell Book). On phones each is a sheet from the bottom.

**Screen widths:** phone ≤ 640px, tablet ≤ 900px, wide ≥ 1100px (media queries can't use variables; the test allows only these).

- **Key-moment types** are colored words, not boxes: Event (muted), Reveal (lavender), Decision (blue), Loot (amber), Theory (italic, muted) so speculation never looks like fact.

## Rules for every page (Brett's reviews, 2026-10-23)

Read these before designing or building any page; sessions that skipped them produced rework.

- **Mock up first** (`docs/mockups/`, made-up names: the repo is public), get Brett's OK, then build one piece at a time.
- **Reuse the components below; no one-off layouts or inline spacing.** If something new is needed, add it to the
  design system (and Manage › Design system) first.
- **Full width.** Pages use their standard width (`.page`, or `.page.wide` for Story, Campaign, Party, Help). No
  narrow reading columns on their own.
- **One tab style:** the underline tabs (`.tabbar`) on the page itself, as on Story. Never a band wider than the content.
- **Lists get filters.** Anything people browse (names, spells, items, quests) has search and chip filters with live
  counts, not just a scroll.
- **Size to the content.** Diagrams, windows and cards are as big as what's in them; no large empty frames.
- **Quiet actions.** One primary (red) button per screen; repeated per-item actions (Edit, Mark done) are small
  secondary buttons.
- **Buttons say where they go** in plain words ("More about Alea"), not how the app works ("Read in World").
- **Terse game words** ("1st-level", never "1st-level slot"); players know the terms.
- **Check both widths** (desktop and phone) and every role (admin, DM, player; Manage › View as) before calling it done.

## Components

Each one is on Manage › Design system with its class or macro. Use these; don't invent a near-copy.

- **Buttons** (`.btn`): four styles, **Primary** (`.primary`, red, one per screen), **Secondary** (plain `.btn`), **Quiet** (`.link`, text only) and **Danger** (`.link.danger`, always confirms), each in two sizes (regular and `.small`). Labels are verbs with outcomes.
- **Pills**, four kinds (Brett, 2026-10-22): **Tag** (`.tag`) labels something and is never clickable (Conc., Ritual, Draft); **Chip** is clickable, one look with a blue on state (filters, Wild Shape forms, spells to cast, conditions, the roll window's choices: `.ls-chip`, `.ws-chip`, `.spell-chip`, `.cond-pill`, `.chip`), `--chip-h` tall; **Count** (`.count`) is a number by a tab or heading; **Roll chip** (`.roll-chip`, `.roll-hit`) rolls dice and turns amber on hover.
- **Headings:** page title (`main h1`), section heading (`.section h2`), divider label (`h3.divider`), action-economy heading (`.econ-head` + `.k-*`). A heading's own action ("+ Add") is a red link for a section's action (Reminders, Battle combos) and the quiet `.head-add` inside busy columns (Action, Bonus action, Reaction). Rules from classes and feats that change a Battle column sit in a **Rules (n)** chip at its top right, shown on hover or tap (Brett, 2026-10-22).
- **Section** (`.section`): a card on the page background with a heading, an optional help line, then content. **Stat** (`.stats > .stat`, `.attention` for a red edge), **number tiles** (`.strip.compact`, Battle's header) and the **resources row** (`.res-row`).
- **Lists** (Lists and filters below): search box (`search_box()`), toolbar (`.ls-toolbar` with `view_switch()`, `.ls-select`, `.ls-check`), filter group (`chip_group()`), row (`ri()`, or `.ls-row` in the shared list), empty state.
- **Marks** (`.pick.star`, `.fav`, `.remind`): Pin, Shortlist, Remind me. Every icon button shows its label on hover, keyboard focus or a long press (app.js, from `data-tip`, `aria-label` or `title`). **Pips** (`pips()`) and **what it uses up** (`spends()`).
- **Help line** (`_help.html` `help()`): one short line, **More** to the FAQ answer and **Got it** to hide it for that person on every device (`users.dismissed_help`; keys in `help_pages.HELP`) (Brett, 2026-10-22). **Note** (`.note`) for dates and footnotes. **Empty state** (`.muted`): every list says what goes there and how to add the first one.
- **Side panel** (`data-panel-url`) from the right edge (the bottom on phones): head with what it belongs to, its name and ✕; a scrolling body; an optional foot. **Modal** (`data-modal-url`; `data-modal-size` `large` or `full`). Sizes under Visual system › Panels and modals.
- **Story block** (`.story`) for recaps, descriptions and answers.
- **Tuning slider** (`.tn-row`, Manage › Dice tuning; Brett 2026-10-24): a name and one help line, a slider with its value, a tick and "now …" for the saved value, the value amber once changed with its own Reset; a sticky save bar (`.tn-save`) counts unsaved changes, with Undo changes and Save. Use it for any setting that's a number to dial in, next to a preview that shows it.
- **Reader** (`.reader`, Campaign › World; Brett 2026-10-22, option E in `docs/mockups/campaign-reading.html`): for reading rather than deciding. A name list on the left (`.reader-nav`, the shared list engine with **All · Last session** and search pinned at its top, kind headings; a blue dot `.rd-dot` marks the last session, so no name is listed twice) and one entry on the page (`.reader-article`, `_peek.html` with `where="reader"`: **Part of** quest chips `.chip-link`, its connections, then two columns, key moments as a timeline `.moment-line`). ↑ ↓ move through the names.
- **Quest board** (`.quest-board-card`, Campaign › Quests; Q1 in `docs/mockups/campaign-tabs.html`): every open quest at full size, an amber edge, Given by and Since, Progress (the last three key moments, **earlier** for the rest), Who and where, What the table knows; a quiet line after three sessions without a key moment. Done quests are one line each (`.qb-done-row`).
- **Family tree** (`.ft`, Campaign › Relationships; R1): one card per family, generations in rows split by a dashed rule, children grouped under "Children of A and B", ⚭ for spouses. People are `.ft-p` buttons. The other ties are plain lists (`.ties`).
- **Connections** (`_connections.html`, `.cx`; R2): one entry in the middle (`.cx-hub`), family keeping its shape around it (parents above, spouse and siblings beside, children below), allies and enemies on the left, factions, service and quests on the right. Lines are SVG; names are HTML placed in percent. Line styles by kind of tie (`.e-family`, `.e-allegiance`, `.e-ally`, `.e-enemy`, `.e-quest`). On phones it's a plain list. Embedded in the Reader; in a large window from the Relationships tab, where a name moves to the middle.
- **Toast:** a short confirmation near the top ("Answer saved", "Published").
- **Manage pages** (Brett, 2026-10-23): built only from these, with no inline spacing (a test checks; Manage › Design system › Manage pages shows each). **Page head** (`.title-row h1`, one `.title-action` button, `.subtitle`); **Section** (`.section > h2 + .hint`, fixed gaps on `main.manage-page`); **Records** (`.records` with `.cols-3`, `.cols-3-even` or `.cols-4`, `.records-head` for column names, each `.record` = `.record-main` (bold name, then notes), fields, `.record-actions`; `.faded` for removed): every list of people, characters, campaigns, rules, corrections and top-ups; **Inline edit** (`_manage.html` `inline_edit()`); **Form row** (`.form-row`, `.field.grow`); **Narrow form** (`.form-narrow`); **Fold** (`details.fold`); **Section pair** (`.section-pair`, two sections side by side); data tables (`table.list`, `td.end` for buttons).
- **Review pieces:** **Read/Edit block** (reading view plus an **Edit** link; edit mode swaps in the form with **Save** and **Cancel**), **Question item** (Answer / Skip; answered ones move to Done with **Edit** / **Remove answer**), **Suggestion item** (Before and Proposed side by side, stacked on phones; **Accept**, **Edit**, **Reject**; Done shows "Now in askdnd" with **Undo**), **Done drawer** ("▸ Done (n)") and **Progress panel** (checklist with the single **Publish** button; a bottom bar on phones).

## Implementation notes

- Server-rendered Jinja templates; small interactions (Edit/Cancel, answer, accept, undo) use HTMX partial swaps so the page doesn't jump.
- One shared stylesheet with the tokens above as CSS variables; pages don't define their own colors or sizes, and `tests/test_design_system.py` checks it.
- Every interactive element has a visible focus style and an accessible label.
- Mockups (archived in `docs/mockups/archive/`) and the living component page use made-up content only.

## Section headings (2026-10-18)
Section headings are all-caps, letter-spaced labels in amber with a fading rule (`h3.divider`). Only the action economy is color-coded, the same everywhere: ◆ red **Action**, ▲ amber **Bonus action**, ↺ blue **Reaction**, ● violet **Other** (classes `k-action`, `k-bonus`, `k-reaction`, `k-other`). Don't add more colors for other kinds of sections; the point is that color means "what it costs on your turn".

## Words (glossary, Brett 2026-10-21)
Use these words, and only these, in the app, the docs and the About and FAQ pages.

| Word | Icon | What it means |
|---|---|---|
| **Battle** | | The fight page (`/characters/{id}/battle`). Never "Play". |
| **Sheet** | | The holistic reference about the character: everything, organized. |
| **Plan** | | Strategy: combos, leveling, quests, notes, the shortlist and reminders. Never shown to the DM. |
| **Pin** / **Pinned to Battle** | 📌 (SVG pin) | Puts something with a turn cost (Action, Bonus action, Reaction) on Battle. Pinning also adds it to the Shortlist. |
| **Shortlist** | Bookmark (SVG) | Things the player is considering or wants close at hand. Anything with a side panel can be shortlisted; a list only offers it once that list has a Shortlist view. |
| **Reminders** / **Remind me** | Bell | Things that are easy to forget. Any item, plus free-text reminders. Never "Easy to forget". |
| **Note** | ✎ | One note per thing, written by the player; it shows wherever that thing appears (one line under a row, full text in the side panel). |
| **Ready · Shortlist · All** | | The three views on a list. "Ready" takes the list's own word: Prepared (spells), Known forms (Wild Shape), Equipped (inventory). |

## Lists and filters (Brett 2026-10-21)
Every list of game things (spells, Wild Shape forms, inventory, features) follows one pattern. The Campaign page is for reading, not deciding, so it uses the Reader (Components) with the same engine and no filter column. Desktop first; phones get the same list with a **Filters (N)** sheet and no phone-only features.

- **Main view decides across many items; the side panel shows one item.** Clicking a row opens the side panel from the right edge; inside a modal such as the Spell Book it slides out from the modal's own right edge, inside it. The Spell Book fills the window so rows aren't cramped. Pin, Shortlist, Remind me and the note are always available in the side panel; Sheet may also offer them inline on rows.
- **Views:** Ready · Shortlist · All, above the list. The Spell Book is the exception: it shows only Prepared spells (castable now).
- **Filters:** a left column of chip groups, then a **More filters** fold. Chips are OR within a group, AND across groups; a second click turns a chip off; no "Any" chip. Each chip shows a live count; zero-count chips are greyed out but stay clickable (to be judged once live). An active-filter row above the list shows what's on, with **Clear all**; the filter column itself has no Clear all.
- **Search overrides filters** and says so (the filters dim while searching).
- **Sort and lenses are separate from filters.** Spells sort by level, then name. A lens (the Spell Book's **Cast at**: Base, 1st, 2nd…) changes numbers, not which rows show; its column is **Damage / Healing**, with healing in green. Sort options are single words (Level, Name, Amount).
- **Remembered per page, per browser**, never shared across pages, and cleared after a day without use.
- **Rows are compact**, one line plus an optional note line. Wild Shape rows get a thumbnail.
- **Spell filters:** visible Level, Effect (damage, heal, control, support, utility), Casting time, Concentration. Under More: Ritual, Save type, On a successful save (half, nothing, damage still lands), Attack roll, Area or single target, Damage type, Range. Save spells always say what a successful save does.
- **The DM** sees only the All view: no Ready, Shortlist or pins, and no notes.
- **Build order:** 1) words and one note per thing, 2) Spell Book, 3) Sheet spells, 4) Plan, 5) Wild Shape; later Inventory, Features and Campaign. Each step ships on its own, and Brett reviews it before the next.
