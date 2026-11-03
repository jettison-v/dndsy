# The VTT build plan (Nov 2, 2026)

askdnd's own table, built in this session, one working slice at a time (Brett, 2026-11-02: "Fine working all in this
thread to promote quality"). Each slice is tried locally, merged, and lands on beta behind the switch **askdnd's VTT**,
which only test campaigns see until Brett switches it on. The layout is decided: the frame around the map
(`docs/mockups/vtt-layout/`, published as VTT Layout). The roadmap (`docs/roadmap.html`) lists these slices in its one
to-do list; this file is the detail behind them.

## What's already decided

- **The frame** (VTT Layout › Main): the menu bar, the fight band across the top as the turn bar, Table rolls on the
  left, the side panel on the right, corner cards at the bottom right, windows over the middle, and your turn's bar
  under the middle. Each is the same piece of code as on every other page.
- **Step 1 is the final page with a different middle** (VTT Layout › The first step): a row per fighter instead of a
  map, while the table keeps using D&D Beyond's map. When maps come, only the middle changes.
- **The turn bar is askdnd's own once a fight starts on this page**; until then it keeps listening to D&D Beyond's VTT,
  as today. Brett's answers from the parked turn order (Oct 28) apply: enemy Hit Points hidden from players by default
  (they see Healthy, Bloodied or Down), in a DM battle settings menu that keeps defaults; players roll their own
  initiative; the DM's change to a player whose sheet can't be reached is listed for them to make by hand.
- **Two switches** (DECISIONS 2026-11-02): Play through askdnd (the bridge, casting, resources and rests, the DM as a
  backup) and askdnd's VTT (its way in is the menu bar's Table button, D&D Beyond's VTT until it's on; its page is
  refused while it's off).
- **Movement and spell areas** (VTT Layout › Movement, Areas): askdnd counts and shows, never stops a move; Dash and a
  Bonus Action Dash while moving; leaving a creature's reach says it may provoke an Opportunity Attack; an area covers a
  square at least half inside it; Cast starts the area for a spell with one, and who's in it carries to the roll and
  Apply to. The DM rules every case.
- **Maps from any builder** (DECISIONS 2026-11-02): any picture with its grid set by hand, and Universal VTT files
  (.dd2vtt / .uvtt) with their grid, walls, doors and lights, since the DM builds in Dungeon Alchemist.
- **Monsters** come from the campaign's books (the Monster Manual once it's uploaded to beta), then the SRD, through
  `rules_data`, as Wild Shape's forms already do.

## Before slice 1 (from the architecture review, `docs/plans/2026-11-02-architecture-review.md`)

- ARCHITECTURE.md rewritten as today's map (S), before slice 1 adds to it.
- No request holds the database while D&D Beyond answers (M), before slice 2: the VTT adds the DM and every player
  changing things during a fight.
- Slice 2's creatures are askdnd's own play state (no D&D Beyond sheet): a fight and its fighters as rows, changed one
  at a time under the fight's lock (`fight.lock`), with a log for the DM's Undo; not more JSON on `Campaign.fight`.

## The slices, in order

| # | Slice | Size | What you can do when it lands |
|---|---|---|---|
| 0 | The two switches | S | Manage › Settings shows Play through askdnd (once live state is reviewed) and askdnd's VTT. The Table button opens askdnd's table in a test campaign, D&D Beyond's everywhere else. **Built Nov 2** (ahead of Brett's review: Play through askdnd gives the bridge until live state is Ready, then the rest with it). |
| 1 | The table's frame | M | `/c/<campaign>/table`: the turn bar, Table rolls, the side panel, corner cards and your turn's bar around a middle that lists the fight's rows as heard from D&D Beyond's VTT. Nothing new to learn: every piece is the one from Battle and Party. **Built Nov 2**: the middle is Party's Rows (one piece, `_fight_rows.html`); a character's row opens its short version in the side panel; your turn's bar comes with its content in slice 3. |
| 2 | askdnd runs the fight | L | The DM starts a fight here, adds creatures (from the books or the SRD; hidden ones only the DM sees), players roll their own initiative into it, the DM presses Next turn. Rounds, reminders and Concentration count from askdnd's turns, as they do from D&D Beyond's today. Players see enemies as Healthy, Bloodied or Down. |
| 3 | Your turn's bar | M | Movement left counted with − and + 5 ft (a split move kept), Dash, what you've used of your Action, Bonus Action and Reaction, Battle's pins in three columns, End turn. Off your turn: your Reactions. |
| 4 | Creatures in the side panel | L | Click a creature: its stat block (2.3), its Hit Points with − and + for the DM, what players see of it (2.6), its actions with Roll. On a creature's turn the bottom bar is the creature's. The DM's rolls for creatures are made in askdnd and reach Apply to as today. |
| 5 | Phones | M | The same page on a phone: the turn bar on top, Table rolls as its thin line, your turn's bar and the side panel as sheets from the bottom. |
| | **Milestone A: a fight run in askdnd, the map still on D&D Beyond** | | A playtest with the table decides what slice 6 onward needs first. |
| 6 | The map | L | The middle becomes a map: the DM uploads a picture and sets its grid, or imports a Universal VTT file (.dd2vtt from Dungeon Alchemist) with its grid in one step; scenes (one map per scene, 3.6). The rows move into the turn bar and the side panel. |
| 7 | Tokens | L | A token per fighter tied to its character or creature (3.2): conditions, reminders and the fight band on it; hidden creatures only on the DM's map. |
| 8 | Moving and measuring | M | Drag a token: feet per square, movement left in your turn's bar, Difficult Terrain the DM paints, the table's diagonal rule in Manage › House rules (3.3). |
| 9 | Fog | M | The DM hides and reveals parts of the map (3.4); with an imported file's walls, later, vision (3.7). |
| 10 | Spell areas | M | The area tool, and Cast starting it for a spell with an area; who's in it carries to the roll and Apply to (3.5). |
| | **Milestone B: a session on askdnd's maps** | | Then Phase 2b's rest (attacks that resolve, encounters) and Phase 4, in the roadmap's order. |

## Choices made along the way (Claude's, said in product terms when they come up)

- How the map is drawn (slice 6): a drawing library that handles a large Dungeon Alchemist picture and many tokens
  smoothly on an iPhone, vendored like the dice. Chosen and tried on the iPhone in WebKit before slice 6 starts.
- Where maps are kept: S3 under `v2/maps/`, never in git, like the Monster Manual's pictures.
- What a fight saves: askdnd's own fight and its fighters are rows of their own, changed one at a time under the
  fight's lock (Before slice 1), and announced like `Campaign.fight` today, so every open page hears them through the
  live table connection.
