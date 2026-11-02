# askdnd Design Guide

_Last updated 2026-10-31 · Applies to every page in the app. The living component page (**Manage › Design system**, `/manage/design`) shows every token and component with the app's own styles; old mockups are archived in `docs/mockups/archive/`._

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

One top bar for everyone (Brett, 2026-10-22, Option B; `docs/mockups/menu-bar.html`), in two groups that match the data: the campaign (its name, **Story**, **Campaign**), then **Table ↗**, then the people at the table (your character, **Party ▾**), then Live, **Manage ▾** (for those who can manage) and the account menu. **Table ↗** is the way to the play area: D&D Beyond's VTT today, askdnd's own later, in the same place.

| Item | Audience | What it is |
|---|---|---|
| Campaign name | Everyone | Always shown, right of the logo. A plain label with one campaign; with two or more, the switcher (your role in each other campaign beside its name) |
| **Story** (home) | Everyone | Tabs **Previously on…** (the pre-session refresher: questions for you, then the latest recap, key moments, open threads) and **All sessions** (every published session, newest first); `?tab=sessions` picks the second. The old `/sessions` address redirects |
| **Campaign** | Everyone | Tabs **World** (the Reader for people, places, factions, items and creatures; `?open=<id>` is an entry's address), **Quests** (the quest log: Open or Done down the left, one quest's journal on the right), **Relationships** (family trees, other ties, anyone's connections), **Glossary** and **Map** (the Sword Coast; `?tab=map&at=<place>` centers it, which is where **Show on map** goes; the old `/map` redirects); `?tab=` picks one |
| **Cole** (your character) | Anyone with a character in this campaign (not the DM) | Portrait and name, one click to your character in the mode you used last (kept in the session). Modes, switched at the page's top right: **Battle** (`/characters/{id}/battle`: options by Action / Bonus action / Reaction, saves, Wild Shape row, On a hit, rolls, Reminders, Battle combos), **Sheet** (`/characters/{id}`: numbers strip, abilities and saves, tabs Actions, Spells, Wild Shape, Inventory, Features, Skills & situational, Background) and **Plan** (`/characters/{id}/plan`: tabs Battle combos, Leveling strategy, Personal quests, General notes, Reminders, Spell shortlist, Wild Shape shortlist; never the DM) |
| **Party ▾** | Everyone | A menu: **Everyone at a glance** first (Brett, 2026-10-26: the whole party matters more than one character), then each character with portrait, class and level, and HP when known ("You" on yours); a character opens in the mode you're in. Everyone at a glance is the Party page (`docs/mockups/party.html`, Brett 2026-10-26): tabs **At a glance** (a card per character with Battle's number tiles, pips and slots; a card opens a short character modal), **Spells** and **Items** (the shared list, who has each by portrait; a portrait opens that character's) |
| **Table ↗** | Everyone in a linked campaign | Opens where the table plays: D&D Beyond's VTT today, askdnd's own later, in the same place. |
| **Live** pill | Everyone | One question: is your sheet connected? Connected (green), Open your sheet to connect (amber in a fight), Add the askdnd bridge when it isn't in this browser, something to make by hand, or when the copy was last read; someone with no character sees how many of the party's sheets are connected. Its popover: a setup card when the extension isn't here (add it, reload, open your sheet), how each sheet is connected, Refresh now, and Refresh everyone (reviewers) |
| **Manage ▾** | The DM, reviewers and admins | This campaign's (Brett, 2026-10-27, `docs/mockups/manage-menu.html`, round 2 option A), its head in red: **Needs you** and **Inbox** (with waiting counts), **Sessions** and **Table** (`.menu-count`, the counts `.mcount`), its other pages on one line (`.menu-more`: House rules · Settings · History · DM guide), then **Your other campaigns** for anyone who runs more than one (keeping you on the same page) |
| **⚙ Admin ▾** | Admins | askdnd as a whole, the same in every campaign, its head in blue: **Overview**, **Accounts**, **Campaigns**, **Usage**, **Backups and imports**, the rest on one line. Every Manage and Admin page starts with a thin line in its half's colour, with the way to the other half beside the title, then lists its half down the left |
| **Table rolls** sidebar | Everyone at the table; closed until opened, and a fight opens it once | Left sidebar on every page (`_table_rolls.html`, 340 px): open or closed to an edge tab, one choice per device for every page (nothing opens or closes it on its own); below 1100 px it starts closed and opens over the page; a bottom sheet on phones (its bar, the newest rolls, or everything). Newest activity first, a roll and its damage / reroll / added die as one entry; a dice tray and your character's quick checks at the bottom. Others' rolls also land in the corner tray |
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
| `--cond-*` (`--cond-poisoned`…, `--cond-dark`, `--cond-dark-edge`) | Each condition's own color (its pill, emblem, Party icon, menu bar dot and the page's edge), by its `[data-cond]` slug |

Status colors are text on their `-soft` tint.

**Text sizes** (Brett, 2026-10-22): `--fs-xs` 12px labels, secondary lines and tags · `--fs-sm` 14px list cells, chips, controls · `--fs-md` 16px body and a row's name · `--fs-lg` 19px section headings · `--fs-xl` 26px the character's name · `--fs-2xl` 30px page titles. UI in **Inter** (fallback system-ui) at 16px / 1.6; story text in `"Iowan Old Style", Palatino, Georgia, serif` at `--fs-lg` / 1.75. The logo alone uses Roboto Condensed.

**Space:** a 4px scale, `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 24 · `--sp-6` 32. Prefer `gap` on flex and grid over margins between siblings. **Battle's blocks** (numbers, Wild Shape, the Status row, the spell bar, the columns) stack in `#battle-body` with one `--sp-4` gap and no margins of their own (Brett, 2026-10-29: the Status row sat closer to the spell bar than to Wild Shape). Where a block's parent has no gap, a **spacing helper** on the same scale, never an inline style (2026-10-27; `tests/test_design_system.py` checks every page): `.mt-1`…`.mt-5` space above, `.mb-1`…`.mb-3` below, `.m-0` none, `.byline` a note tucked under what it's about (who added it and when), `.push` a button at the far end of its row, `.grow` the part of a row that takes the room left, `.row.tight` small controls that belong together. Small component rules took the rest: `.btn.block` (a card's one action), `label.field.short`, `.callout.ready`, `.title-action`.

**Corners:** `--r-xs` 3px tiny marks (a pip, a bar) · `--r-sm` 6px small chips, menu bar controls and inner boxes · `--r-md` 8px buttons, inputs and number tiles · `--r-lg` 12px sections, cards, panels, windows · `--r-pill` tags, chips, counts · `50%` round things. The test fails on any other corner.

**Shadows:** `--lift` for anything that floats over the page (a menu, a window, a card); the test fails on a near-copy of it. A side panel's shadow falls to the left; a coloured glow belongs to its component.

**Controls:** search boxes, every text, number and date field, selects and regular buttons are `--control-h` tall (32px on desktop, 44px on phones; Brett, 2026-10-22), so a field and the button beside it always match; small buttons `--control-h-sm` (26 / 36px); chips `--chip-h` (28 / 36px); everything in the menu bar `--bar-h` (36 / 44px). A file picker's button looks like a regular button. Fields use 16px text on phones so iPhones don't zoom in.

**The page's scrollbar** (a computer): a 12px lane that's always there, so a page never shifts sideways, drawn as part of the page: the menu bar and its red line run through it to the window's edge (Brett, 2026-10-31). Phones keep their own.

**Tap targets on a phone** (tests/browser/test_layout.py): at least 36px, the regular controls 44px. What sits among words (a pin, a bell, + Add) keeps its size and takes a larger area around it (`::after`).

**Panels and modals** (three sizes, chosen by what's inside): side panel `--panel-w` 420px (details for one thing; also inside a modal) · modal `--modal-w` 720px (a form or short content) · large `--modal-lg-w` 1180px (rich content in columns: a Wild Shape form, a combo, a leveling plan, the Spell Book). On phones each is a sheet from the bottom. (A full-window size for the Spell Book was retired on 2026-10-29: too wide on large screens.)

**Screen widths:** phone ≤ 640px, tablet ≤ 900px, wide ≥ 1100px, and the full menu bar > 1240px (below it the Live pill shortens to "● Live", 2026-10-26) (media queries can't use variables; the test allows only these). A list's own width (container queries) is its columns' need instead; see Narrow screens.

- **Key-moment types** are colored words, not boxes: Event (muted), Reveal (lavender), Decision (blue), Loot (amber), Theory (italic, muted) so speculation never looks like fact.

## Rules for every page (Brett's reviews, 2026-10-23)

Read these before designing or building any page; sessions that skipped them produced rework.

- **Mock up first** (`docs/mockups/`; the table's own characters, "Enemy 1" and "NPC 1" for the rest, Brett 2026-10-26), get Brett's OK, then build one piece at a time. Mockups show phone and an in-between width (about 1000px), not just desktop.
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
- **No code words on a page.** A file name, a class or a roadmap phase belongs in the docs, not in text a DM or a player reads.
- **Check every width** (phone, tablet, about 1000px, wide) and every role (admin, DM, player; Manage › View as) before
  calling it done. The width check (tests/browser/test_layout.py) does the measurable part on every pull request; see
  Narrow screens below for what it checks and how each part of a page gives way.

## Narrow screens (2026-10-26)

Pages are used from 375px phones to wide monitors, and the in-between widths (a laptop with a side panel, a half-screen
window) are where things break. The rules:

- **Nothing scrolls sideways.** The page is never wider than the window. A wide table scrolls inside its own box, or
  (better) switches to its compact layout.
- **One-line controls stay on one line.** Buttons, tabs, chips, tags and the menu bar's controls never break onto two The one exception (Brett, 2026-10-30): inside anything smaller than a page (the roll window, a side panel, a modal, a corner card) a long label wraps inside its button, so it never runs out of the box.
  lines (`.btn` is `nowrap`); the row around them wraps instead.
- **Text stays in its box.** Menus, panels, cards and buttons hold their text; long words (a web address) break
  (`overflow-wrap` on `body`), and names that must stay on one line end in "…".
- **Decide what gives way, in order, for anything that shares a row.** Write it next to the component's CSS.

How each part gives way:

| Part | As the room runs out |
|---|---|
| Menu bar | The logo never shrinks. Below 1240px the Live pill shortens to "● Live"; then the campaign's name ends in "…"; below 1100px the word "askdnd" goes; at 900px and below, the bottom bar takes over Story, Campaign, your character, Party and More. Manage, your character, Party, ? and you never wrap or shrink. |
| Menus from the menu bar | Their own width (240-360px, never wider than the window less 24px); text wraps inside. Party's opens leftward. |
| Side panel | Beside the page on wide screens; a sheet from the bottom at 900px and below. |
| Lists with columns (Sheet's Spells, Wild Shape, Inventory, Features; the Spell Book) | Switch to compact rows when the list's own box is narrower than its columns need, whatever the screen (container queries: Spells and the Spell Book 920px, Wild Shape 740, Features 700, Inventory 680). Filters sit beside the list, above it on phones. |
| Sections with tab bars | The sticky tab bar reaches the section's edges: 30px wide, 18px from tablet down. |
| Battle's numbers and saves | One row; when the row itself is under 1000px, Spell DC / attack shortens to Spell DC; under 760px the saves drop under the numbers, six across; on phones Hit points takes a row, then two by two, then the saves three across. |
| Battle's columns | Three side by side; on phones one at a time with Action / Bonus / Reaction tabs. |
| The tour's card | Beside what it lights (beside the side panel when lighting inside it); at the bottom on phones. |

**Checking:** `tests/browser/test_layout.py` opens every main page (player and admin, with long names on purpose),
each tab, the menu bar's menus and Battle's side panel at 375, 768, 1000 and 1280px, and fails on anything that
scrolls sideways, spills, wraps or overlaps (`tests/browser/layout_check.js`). At the end of each roadmap phase,
`scripts/layout_sweep.py` runs the same check over every page of a copy of real data, as each role, and saves a
screenshot of each page at each width for a look-over.

## Components

Each one is on Manage › Design system with its class or macro. Use these; don't invent a near-copy.

- **Buttons** (`.btn`): four styles, **Primary** (`.primary`, red, one per screen), **Secondary** (plain `.btn`), **Quiet** (`.link`, text only) and **Danger** (`.link.danger`, always confirms), each in two sizes (regular and `.small`). Labels are verbs with outcomes. **Row action** (`.row-act`; Brett, 2026-10-29): an action inside a list's row (the Spell Book's Roll, and Concentrate as its ◎ icon with a label on hover) is a compact pill, so the row keeps its room for the columns; amber on hover when it rolls.
- **Pills**, four kinds (Brett, 2026-10-22): **Tag** (`.tag`) labels something and is never clickable (Conc., Ritual, Draft); **Chip** is clickable, one look with a blue on state (filters, Wild Shape forms, spells to cast, conditions, the roll window's choices: `.ls-chip`, `.ws-chip`, `.spell-chip`, `.cond-pill`, `.chip`), `--chip-h` tall; **Count** (`.count`) is a number by a tab or heading; **Roll chip** (`.roll-chip`, `.roll-hit`) rolls dice and turns amber on hover. Where a number is what you roll (an attack's to-hit, Initiative on Battle) the number itself is the button (`.roll-hit`, `.tile-hit` on a tile), and any Roll button goes in its side panel.
- **Headings:** page title (`main h1`), section heading (`.section h2`), divider label (`h3.divider`), action-economy heading (`.econ-head` + `.k-*`). A heading's own action ("+ Add") is a red link for a section's action (Reminders, Battle combos) and the quiet `.head-add` inside busy columns (Action, Bonus action, Reaction). Rules from classes and feats that change a Battle column sit in a **Rules (n)** chip at its top right, shown on hover or tap (Brett, 2026-10-22).
- **Section** (`.section`): a card on the page background with a heading, then content. **Stat** (`.stats > .stat`, `.attention` for a red edge), **number tiles** (`.strip.compact`) and the **resources row** (`.res-row`). **Battle's top** (`.battlebar`; Brett 2026-11-01, `docs/mockups/battle-band/` Option E): Resources first, with Inspiration as a chip you can press (`insp_mark`, gold with a filled star when you have it, grey and hollow when not; it asks first, then changes it on D&D Beyond) and Rest at its far right; then one row (`.battle-head`): the numbers share the room left and the saves stay stacked 3 × 2 behind a line, with no word "save". Both Inspiration and Rest are in the Status row on a phone, where Resources is closed.
- **Lists** (Lists and filters below): search box (`search_box()`), toolbar (`.ls-toolbar` with `view_switch()`, `.ls-select`, `.ls-check`), filter group (`chip_group()`), row (`ri()`, or `.ls-row` in the shared list), empty state.
- **Marks** (`.pick.star`, `.fav`, `.remind`): Pin, Shortlist, Remind me. Every icon button shows its label on hover, keyboard focus or a long press (app.js, from `data-tip`, `aria-label` or `title`). **Pips** (`pips()`) and **what it uses up** (`spends()`).
- **No help lines or explaining labels** (Brett, 2026-10-27; help lines with Got it were `_help.html`, 2026-10-22): the tour (? › Take the tour) and Help explain the pages, so pages carry only their content. **Note** (`.note`) for dates and footnotes. **Empty state** (`.muted`): every list says what goes there and how to add the first one.
- **Side panel** (`data-panel-url`) from the right edge (the bottom on phones): head with what it belongs to, its name and ✕; a scrolling body; an optional foot. **Modal** (`data-modal-url`; `data-modal-size="large"`). Sizes under Visual system › Panels and modals.
- **Where a window's actions go** (Brett, 2026-10-29): a side panel's or modal's buttons (Save, Add, Edit, Cancel) sit in its **foot** (`.peek-foot.row`), along the window's bottom edge below the scrolling body, never partway down it: the main action first, then Cancel as a quiet link; something destructive (Delete) at the far end (`.push`); a short note may follow the buttons. A window that is a form wraps its body and foot in `.peek-form`. (The hit points window keeps its Take and Cancel with the working they depend on, at the end of its body.)
- **Story block** (`.story`) for recaps, descriptions and answers.
- **Tuning slider** (`.tn-row`, Manage › Dice tuning; Brett 2026-10-24): a name and one help line, a slider with its value, a tick and "now …" for the saved value, the value amber once changed with its own Reset; a sticky save bar (`.tn-save`) counts unsaved changes, with Undo changes and Save. Use it for any setting that's a number to dial in, next to a preview that shows it.
- **Reader** (`.reader`, Campaign › World; Brett 2026-10-22, option E in `docs/mockups/campaign-reading.html`): for reading rather than deciding. A name list on the left (`.reader-nav`, the shared list engine with **All · Last session** and search pinned at its top, kind headings; a blue dot `.rd-dot` marks the last session, so no name is listed twice) and one entry on the page (`.reader-article`, `_peek.html` with `where="reader"`: **Part of** quest chips `.chip-link`, its connections, then two columns, key moments as a timeline `.moment-line`). ↑ ↓ move through the names.
- **Quest board** (`.quest-board-card`, Campaign › Quests; Q1 in `docs/mockups/campaign-tabs.html`): every open quest at full size, an amber edge, Given by and Since, Progress (the last three key moments, **earlier** for the rest), Who and where, What the table knows; a quiet line after three sessions without a key moment. Done quests are one line each (`.qb-done-row`).
- **Family tree** (`.ft`, Campaign › Relationships; R1): one card per family, generations in rows split by a dashed rule, children grouped under "Children of A and B", ⚭ for spouses. People are `.ft-p` buttons. The other ties are plain lists (`.ties`).
- **Connections** (`_connections.html`, `.cx`; R2): one entry in the middle (`.cx-hub`), family keeping its shape around it (parents above, spouse and siblings beside, children below), allies and enemies on the left, factions, service and quests on the right. Lines are SVG; names are HTML placed in percent. Line styles by kind of tie (`.e-family`, `.e-allegiance`, `.e-ally`, `.e-enemy`, `.e-quest`). On phones it's a plain list. Embedded in the Reader; in a large window from the Relationships tab, where a name moves to the middle.
- **Character card** (`.pt-card`, Party › At a glance; Brett 2026-10-26, `docs/mockups/party.html`): portrait (`.roll-av` in the character's table-rolls color), name and classes, three number tiles (`.strip.compact.pt-tiles`: HP, AC, Speed), best saves, resources with pips and slots; two to a row, one on narrow screens; a click opens the short character modal. **Who has it** (`.pt-who > .pt-w`, Party's Spells and Items): each character by portrait with a short note ("item", "1/Long Rest", "×2 3/7"); a click opens their copy. Party's lists are the shared list (Lists and filters below) with columns (`.pt-row`).
- **Fight band** (`.fight-band`, `_fight_band.html`; Brett 2026-10-29, bolder 2026-10-30): above the name on every character page and at the top of Party while a fight runs in D&D Beyond's VTT. A war banner: a pennant with the round (`.fb-round`), whose turn in big condensed capitals (`.fb-head`), and who's next. `data-turn` colours all of it: gold for yours (its token glows slowly), red for an enemy's, blue for an ally's. The order is tokens (`.fb-who`), each a round picture with its name under it (a character's portrait, a creature's token art or Monster Manual picture, else its initial): enemies (`.enemy`) ringed red, whose turn (`.now`) large and glowing, those who've acted this round dimmed, a hidden token (`.hid`, the DM's only) dotted, one at 0 Hit Points (`.down`) striped with "0 HP". Under 900px the order takes its own row; on phones, pictures only, with whose turn by name.
- **Dying tile** (`_char.html` `hp_tile`, `.dying`; Brett 2026-10-29, `docs/mockups/death-saves.html`): at 0 Hit Points, Battle's and Sheet's Hit points tile turns red and is named Dying, with the death save marks after the number (three green, three red, `.ds-pip`) and its Roll; Stable turns it green, Three failures says the DM rules. It takes two columns of the strip. Party's tile shows the same marks without the Roll, and a line on how others can help.
- **Corner card** (`#cards > .card.k-*`, app.js `toast(message, action, kind)`; Brett 2026-10-29, `docs/mockups/temporary-items.html`): the one place for everything you read and dismiss: "Saved", a refused button's reason, an error, someone's roll when their dice aren't thrown. Bottom right, 400px wide, newest at the bottom, three at most, its buttons in a row under the text (Brett 2026-10-29: beside it they squeezed the words; the main one tinted, `.card-act.main`), beside an open side panel; on phones one at a time above the bottom bar or Table rolls. Its kind gives its icon, colour and time: **done** (green ✓, 4 seconds), **for your information** (blue i, 6), **someone's roll** (their die, 6), **refused** (amber !, 10), **error** (red ✕, until closed); every card has ✕ and hovering keeps it. **With a button** (`toast(message, {label, run}, kind)`: Undo, Keep going) it stays 20 seconds. The server says the kind with `web.notice(text, kind)` (its text alone means done). Dice are never cards: your own are thrown across the page, their total at the top centre (`.dt-card`, clear of the roll window, which opens by the button or at the bottom; Brett 2026-10-29), others' land in the tray. Rolls made while the tab was out of sight are never replayed (Brett 2026-10-30): they're in Table rolls, and while it's closed one card says how many, with Show.
- **Item on Battle** (`.items-head`, `.item-go`, `_use_window.html`; Brett 2026-10-30, `docs/mockups/potions-and-charges.html`): a column's Items section holds pinned items, with All items for the side panel. An item's button sits where an attack's to-hit does and says what you do (Drink, Read, Use); it opens the roll window, never a new kind of pop-up. Dimmed and disabled with no uses left.
- **Correct this** (`.correct`, `_panel_detail.html`; Brett 2026-10-30, `docs/mockups/correction-flow.html`): the box at the bottom of a side panel, for the DM and admins. A row of options per setting that saves as you click (`.ov-field`), and Why in a few words. Admins pick This campaign or Everyone; a DM only has This campaign.
- **A seat on Table** (`.seat`, `manage_table.html`; Brett 2026-10-30, `docs/mockups/the-table.html`): a person and their character on one row, which opens for everything about it. Its dropdowns save as you pick (`select[data-autosave]`). Remove opens in place and says exactly what will happen before you confirm; nothing is deleted, and Left the table has Bring back.
- **Spell bar** (`.spell-bar`, Battle): the one blue block on a page, in Concentration's colour. **Spell Book** (`.spellbook-btn`) is its filled blue button, the only button that isn't one of the four styles, because it's the door to everything castable; then slots and pinned spells.
- **Start cards** (`.start-cards`, a new campaign's Story; Brett 2026-10-31): what's ready before the first recap, one action per card, as many columns as fit.
- **A window that does one thing** (the roll window's family: `_cast_window.html`, `_count_window.html`, `_rest_window.html`, `_coins_window.html`, `_use_window.html`): opens beside its button (the bottom of the screen on phones), never a new kind of pop-up; name and ✕, then the choices, then the action. When the sheet can't be reached, one amber line says how, with no action.
- **Open on D&D Beyond** (`.sheet-open`): the ↗ square beside a name, and last in each row of the Live window so the icons line up.
- **Grouped resources** (`res_groups`; `.pt-group` on Party): rows sharing a name before ": " under that name once. They wrap, each row whole.
- **Party's Rows** (`.pt-track`, a fight; Brett 2026-10-31): one line each in turn order, inside `.table-scroll`.
- **Changing Hit Points** (`.hp-btns`, `_hp_quick.html`; Brett 2026-11-01, `docs/mockups/hp-flow/` Option B): − and + on Battle's Hit points tile open the small window on Damage or Heal, ready to type in, and Enter takes it. The rest of the tile still explains the number, like every tile. The form is the same one Apply to opens in its modal (`_hp_form.html`).
- **Two-way switch** (`.seg > button[aria-pressed]`): two or three choices side by side that change something on the page, the one that's on in red.
- **Conditions** (Battle; Brett 2026-10-28, `docs/mockups/conditions-on-battle.html`): each has its own color (`--cond-*`) and an icon drawn for askdnd (`_cond_icons.html` `cond_icon`). **Concentration** first in the Status row (`.conc-pill[data-cond=concentration]`, `_conc_pill.html`, then a divider `.cond-sep`), in blue (`--cond-concentration`, the spell bar's color; in the Spell Book a filled "◎ Concentration" tag on its spell, the ◎ pulsing once as it opens), on the edge always and with a badge, like a condition (Brett 2026-10-29). The **condition pill** (`.cond-pill[data-cond]`) under Battle's numbers, in D&D Beyond's order, a condition ending keeping its place, how long it lasts in a few words (`.cond-time`, amber `.soon` when it ends or asks for its save this turn) and the whole of it in its box (`.cond-lasts`), with Keep when its time is up; + Condition's **Lasts** (`.cond-lasts-form`) above the chips; a badge's amber dot (`.cond-soon`) on the turn it ends; a **badge** per condition after the character's name on Battle, Sheet and Plan (`.char-name > .cond-badges > .cond-badge`, `cond_badges`; Brett 2026-10-29, `docs/mockups/temporary-items.html`), Concentration first, icons only, six at most, its summary on hover or tap, popping in once as it starts; **the page's edge** (`.cond-halo`, `cond.edge`; Battle only): a thin line and a soft glow in the newest three conditions' colors (Concentration's always), over the sidebar and side panel, darker for Blinded or Unconscious, brightening once as one starts and otherwise still. Party cards have the same badges after each name (`cond_badges(…, still=true)`: what each does on hover, as a click opens the card), your menu bar button a dot each (`.cond-dots`).
- **D&D Beyond states** (`.br-st` with `.br-live`, `.br-wait`, `.br-off`, `.br-seen`, `.br-asleep`; the bridge, a local proof, 2026-10-27): Live with D&D Beyond, Waiting for D&D Beyond, Not on D&D Beyond yet (with the end state to make by hand), Changed on D&D Beyond, and asleep. **On its way** (`[data-sync]`, `_char.html` `sync`/`sync_attrs`, `ddb_bridge.as_shown`; Brett 2026-10-29): a change shows as made the moment it's made, with a quiet mark until D&D Beyond has it, in the background (askdnd is the tool, D&D Beyond the repository): a thin, grey, half-clear dashed line and a still ↻, no words but the hover title; a condition ending is faded; one given up is the same in amber with !. When D&D Beyond has it, the mark just goes (no green glow). The bridge's **status badge** (`.br-pill`) sits in the corner of every page where it's on; hidden on phones.
- **Table** (`.table-scroll` around every `<table>`; a test checks): a wide table scrolls inside its own box, never the page.
- **Help menu** (the **?** in the menu bar, `.help-menu`): Help's tabs and **Take the tour**. **Tour card** (`.tour-card` over `.tour-spot`, app.js "the tour"): a progress bar and "18 of 30" for every stop, the stop's title, what it is and why, then Back, Next and ✕; ✕ or Esc asks **End the tour?** (Keep going / End tour) first. One target per stop; a stop with `all` lights every match together (a column). Brett, 2026-10-26.
- **Table rolls sidebar** (`_table_rolls.html`): open, or closed to the **edge tab** (`.rs-edge`, the left edge under the menu bar); on phones a bottom sheet with its bar, the newest rolls or everything. Its rules are in Navigation above.
- **Manage pages** (Brett, 2026-10-23): built only from these, with no inline spacing (a test checks; Manage › Design system › Manage pages shows each). **Section list** (`_manage_head.html`, 2026-10-27): the page's half of Manage down the left in sections (Every week · The table · Setup; People · Running askdnd · Tuning), most often opened first, from 1240px (it sits in the page's left padding, so each page keeps its width); narrower, the same list from the **jump control** (`.manage-jump`) at the top; a **thin line** at the top of every Manage and Admin page (`.manage-band.camp` red, `.tool` blue) saying which half you're in, with the way to the other beside the title (room kept for it, however long the campaign's name), and a **waiting count** (`.mcount`) beside Needs you and Inbox, fetched from `/manage/counts` when the menu opens. **Overview card** (`.ov-cards > a.ov-card`, askdnd's Overview): a page's name, how it stands (`.ov-state.ok` green, `.warn` amber), what it's for. **Page head** (`.title-row h1`, one `.title-action` button, `.subtitle`); **Section** (`.section > h2 + .hint`, fixed gaps on `main.manage-page`); **Records** (`.records` with `.cols-3`, `.cols-3-even` or `.cols-4`, `.records-head` for column names, each `.record` = `.record-main` (bold name, then notes), fields, `.record-actions`; `.faded` for removed): every list of people, characters, campaigns, rules, corrections and top-ups; **Inline edit** (`_manage.html` `inline_edit()`); **Form row** (`.form-row`, `.field.grow`); **Narrow form** (`.form-narrow`); **Fold** (`details.fold`); **Section pair** (`.section-pair`, two sections side by side); data tables (`table.list`, `td.end` for buttons).
- **Review pieces:** **Read/Edit block** (reading view plus an **Edit** link; edit mode swaps in the form with **Save** and **Cancel**), **Question item** (Answer / Skip; answered ones move to Done with **Edit** / **Remove answer**), **Suggestion item** (Before and Proposed side by side, stacked on phones; **Accept**, **Edit**, **Reject**; Done shows "Now in askdnd" with **Undo**), **Done drawer** ("▸ Done (n)") and **Progress panel** (checklist with the single **Publish** button; a bottom bar on phones).

## Implementation notes

- Server-rendered Jinja templates; small interactions (Edit/Cancel, answer, accept, undo) use HTMX partial swaps so the page doesn't jump.
- One shared stylesheet with the tokens above as CSS variables; pages don't define their own colors or sizes, and `tests/test_design_system.py` checks it.
- Every interactive element has a visible focus style and an accessible label.
- A time of day is written with the `clock` filter (`{{ when | clock }}`, `clock(date=True)` with the day): the server keeps UTC and doesn't know the reader's time zone, so the page shows it in the reader's own (app.js "clocks"). Never `strftime` a clock time; how long ago something was is `ago`.
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

- **Main view decides across many items; the side panel shows one item.** Clicking a row opens the side panel from the right edge; inside a modal such as the Spell Book it slides out from the modal's own right edge, inside it. The Spell Book fills the window so rows aren't cramped. Pin, Shortlist, Remind me and the note are always available in the side panel; Sheet may also offer them inline on rows, and the Spell Book offers Pin on each row (an empty spell bar shows **+ Add**, which opens it).
- **Views:** Ready · Shortlist · All, above the list; the first one is where the list starts. The Spell Book is the exception: it shows only Prepared spells (castable now). Inventory starts on All (All · Equipped · Shortlist): what you carry matters more there than what's equipped.
- **Filters:** a left column of chip groups, then a **More filters** fold. Chips are OR within a group, AND across groups; a second click turns a chip off; no "Any" chip. Each chip shows a live count; zero-count chips are greyed out but stay clickable (to be judged once live). An active-filter row above the list shows what's on, with **Clear all**; the filter column itself has no Clear all.
- **Search overrides filters** and says so (the filters dim while searching).
- **Sort and lenses are separate from filters.** Spells sort by level, then name. A lens (the Spell Book's **Cast at**: Base, 1st, 2nd…) changes numbers, not which rows show; its column is **Damage / Healing**, with healing in green. Sort options are single words (Level, Name, Amount).
- **Remembered per page, per browser**, never shared across pages, and cleared after a day without use.
- **Rows are compact**, one line plus an optional note line. Wild Shape rows get a thumbnail.
- **Spell filters:** visible Level, Effect (damage, heal, control, support, utility), Casting time, Concentration. Under More: Ritual, Save type, On a successful save (half, nothing, damage still lands), Attack roll, Area or single target, Damage type, Range. Save spells always say what a successful save does.
- **The DM** sees only the All view: no Ready, Shortlist or pins, and no notes.
- **Build order:** 1) words and one note per thing, 2) Spell Book, 3) Sheet spells, 4) Plan, 5) Wild Shape; later Inventory, Features and Campaign. Each step ships on its own, and Brett reviews it before the next.
