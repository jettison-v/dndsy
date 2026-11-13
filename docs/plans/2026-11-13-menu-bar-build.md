# The menu bar by person: the build (Nov 13)

Brett's picks on [Menu Bar by Person](https://claude.ai/artifact/JUbytTRRvQePW6U5kaxQJu)
(`docs/mockups/menu-bar-people/`, store `answers/pick`, Nov 13): **1 the player's bar, 2 the DM's bar, 4 the Live
pill's words, 5 Story and Campaign as one**, Campaign opening on **Previously on…**, and Search as **D, a command bar**
that keeps its place and its box as it shrinks. Not picked: **3, Admin and Help in the account menu** (the gear and ?
stay in the bar). Brett: "holistic changes, not piecemeal, using or updating the design system": one change, every
person, every width, every page that pointed at what moved.

## What changes

1. **Campaign takes Story in.** One page, Campaign, with tabs **Previously on… · Sessions · World · Quests ·
   Relationships · Glossary · Map**, opening on Previously on… (`?tab=` as today; `?open=<id>` still opens an entry in
   World or Quests). Its address stays `/c/<campaign>/campaign` (most links already go there); `/c/<campaign>/`
   (Story's) becomes a kept forward to it, like `/`, and every link to Story moves to Campaign (tests/test_links.py
   fails on one that redirects). Story's pieces (the scroll, key moments, open threads, All sessions' rolled scrolls,
   From the start, Story search) move unchanged into the two tabs as partials; nothing about them is redrawn.
2. **The menu bar for every person** (`base.html`): logo, the campaign's name, **Campaign**, **Table**, your character,
   **Party ▾**, Search's bar, then the Live pill, Manage ▾ (the DM, reviewers, admins), ⚙ (admins), ?, your picture.
   The DM has no character, so the room goes to Search and Manage. DM Tools (PR 319, not merged) joins Manage when it
   lands, never a door of its own (Brett's note, Nov 13; The DM's Workspace decides its page).
3. **The Live pill's words** (`_live_pill.html`): connected is the **green dot alone** ("Connected" on hover and to a
   screen reader); every other state says what to do in words (Via the DM · open your sheet, Open your sheet, Not
   connected, 1 didn't go through, Add the bridge, D&D Beyond not answering; the DM's 3 of 4 · 1 via you, 2 of 4
   connected, None connected), and their short forms below 1100px. Never a bare "Live". The connection band (Nov 13)
   already says the same in the same colours.
4. **Search as a command bar** (`.search-bar`, replacing `.search-btn`): right after Party, always the same distance
   from it, taking only the bar's free room (up to 380px, down to 78px), its words going from "Search your character,
   the rules, the story" to "Search" to the magnifier and ⌘F alone (container queries), the same box at every width.
   Pressing it, ⌘F, Ctrl F or ⌘K opens the search box under it, at its left edge (the box seems to grow out of it).
5. **The order things give way** (docs/DESIGN.md › Navigation): Search's bar shrinks first, always; below **1360px**
   the word askdnd goes; **1200px** your character's name (its picture stays, the name on hover); **1100px** the Live
   pill's short words; **1000px** the campaign's name shortens with "…" (to about 120px); **900px** the phone layout:
   the top bar keeps the logo, the campaign's name, Search's magnifier and the pill, the bottom bar Campaign · your
   character · Party · More.

## Every place it reaches

- **Design system**: docs/DESIGN.md › Navigation rewritten (the table, the collapse order, the pill's states) and
  Manage › Design system gets a **Menu bar** section: the bar at each width, every pill state, the Search bar's three
  lengths. The band (Nov 13) sits under it.
- **Pages and links**: the 16 links to Story, `answer_question`'s redirect, session pages' way back, Needs you, the
  digest email's link, entry_url (unchanged), the bottom bar and More.
- **Help** (About, FAQ: the Live pill, Search, where the recap is), **the DM guide** (Story → Campaign › Previously
  on…), **the tour** (its Story stops become Campaign's first tabs, still page by page with none twice;
  tests/browser/test_new_player_tour.py), **CLAUDE.md** (Where things are: Menu bar, Story, Campaign page, Search).
- **Tests**: test_links (every page, every role), the layout tests at 375, 768, 1000 and 1280 plus WebKit (a new
  check: the menu bar never wraps or spills at 1000–1512), Search's tests (the bar opens the box; ⌘F still works),
  the tour, story search, the pill's states (tests/test_dm_backup.py's words).
- **Every person**: a player, the DM (no character), a reviewer, an admin who plays, View as, a test account; signed
  out sees none of it.
- **Every state**: one campaign and several (the switcher), a long campaign name, a test campaign's tag, staging's
  label, no recap yet (a new campaign's Previously on… is its start cards), a fight running, the band showing.
- **Look at it**: 1512, 1440, 1280, 1200, 1100, 1000, 768 and 375, as each person; screenshots for Brett.
