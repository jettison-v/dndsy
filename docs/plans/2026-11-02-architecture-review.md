# Architecture review before the VTT (Nov 2, 2026)

Brett, after the code review of PRs 140–158: "If you find value, you can do a whole architecture review." It was worth
it in one sense: the VTT is the first part of askdnd that several people change at once, many times a minute, so this
looks at what the VTT will lean on: the live connection, who owns which state, the database under load, and the page
code. The roadmap (`docs/roadmap.html`) carries what came out of it as to-do items.

## What it found

1. **Two changes to a fight saved at once lost one (fixed, PR 159; proven by a test the same night).** Each change
   (a turn report from any open VTT page, a death-save card) reads the fight, adds to it and saves it whole, and
   nothing kept two from being saved at the same moment, so one was dropped: a dying character's card could never
   reach the player or the DM. `fight.lock` now holds the campaign's row (FOR NO KEY UPDATE, like the bridge's own
   lock) before any change to the fight. tests/test_fight.py saves two cards at once in two threads: with the lock both
   stay, without it the test fails. (First written up as "doubled reminders"; the test showed the real harm was the
   lost one.) Slice 2's own fight inherits it.

2. **A request holds the database while D&D Beyond answers (open since Nov 2).** When the bridge builds a batch on a
   copy of the sheet older than a minute, it reads the sheet from D&D Beyond (up to 15 seconds, plus the class spell
   lists) while holding a database connection and the character's row lock. This is what ran beta out of connections
   with three test players on Nov 2; the bigger pool and the spell-list cache eased it, they didn't remove it. The VTT
   adds the DM and every player making changes during a fight, so it's done before slice 2: read D&D Beyond first, with
   no connection or lock held, then take the lock and check the copy is still the newest before using it. Size S–M.

3. **Who owns play state has changed since the VTT plan was written.** The Oct 24 foundations (vtt-roadmap › Play
   state and the play log) assumed askdnd owns a character's hit points, slots and conditions during play. The bridge
   (Oct 27–28) made D&D Beyond the owner: askdnd changes a character there and reads it back. That's right for
   characters. Creatures have no D&D Beyond sheet, so in slices 2 and 4 askdnd owns their hit points, conditions and
   whether they're hidden. They get their own tables (a fight and its fighters, one row each, changed row by row with
   a log for the DM's Undo), not more JSON on `Campaign.fight`, which several people now write at once. Designed at
   the start of slice 2.

4. **The live connection is right for slices 1–5 and planned for 7–8.** "Something changed, fetch it again" suits turns,
   Hit Points and conditions: a few changes a minute, and the page's own address decides who sees what. Dragging a
   token can't wait for a page fetch; the plan already says positions will carry their data (about 10 a second per
   token) and anything hidden goes on a DM channel (vtt-roadmap › Live connection). Built with slice 7. Nothing to
   change now.

5. **The map is its own page code.** app.js is 3,400 lines loaded on every page. The map (slice 6) gets its own script,
   loaded only on the table page, with its drawing library vendored like the dice. Decided now so slice 1's frame
   leaves room for it.

6. **`docs/ARCHITECTURE.md` is a draft from Oct 14.** It still describes the three-week first build. The real map is
   CLAUDE.md's "Where things are" and the stack map. Rewritten as a short current map (services, who owns what data,
   how a change travels) before the VTT adds to it. Size S.

7. **`app/ddb_bridge.py` is 1,600 lines**: the bridge's engine, its routes and the DM as a backup in one file. It works
   and is well tested; split the routes from the engine the next time it changes for a reason of its own, not as work
   of its own.

## Checked and fine

- One copy of the app or several: the live connection goes through Postgres, the bridge locks per character, and the
  in-memory caches (roles, D&D Beyond's item and spell lists) expire on their own, so a second copy works.
- Privacy: nothing in today's code sends request bodies, names or emails to Sentry; raw transcripts stay local.
- Tests: 763 server and 49 browser tests; the one unreliable test (Battle's resources) was fixed in PR 158.
