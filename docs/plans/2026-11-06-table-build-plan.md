# askdnd's table: the build plan (Nov 6, 2026)

This plan replaces `2026-11-02-vtt-build-plan.md`. It comes from the whole-table walkthrough
(`docs/mockups/table-slices/`, published as *askdnd's Table, slice by slice*) and Brett's answers the same evening.

## Brett's answers (Nov 6)

- **No Milestone A, one cutover.** The table keeps playing on D&D Beyond's VTT until everything below is built, then
  moves to askdnd's table all at once. Playing with something half-finished would frustrate the table. The next game
  may be a month away, which is the time to build it all.
- **The order** on the walkthrough's road stands: your turn's bar, creatures in the side panel, phones, the scene notes,
  the map, tokens, askdnd runs the fight, moving, fog, spell areas.
- **A group of the same creature rolls one Initiative**, and the DM can split any of them.
- **Build on staging, no testing round per slice.** Brett looks when there's a product to look at; pushes are kept
  few, since each one runs GitHub's checks.
- **How a scene works:** decide it from how other tools do it (below).

## What other tools do, and what their users say (research, Nov 6)

**D&D Beyond Maps**, the table's VTT today. Its Scene Prep (Aug 31, 2026) is what the DM sent:
- A *Location* is a map, or a Theater of the Mind page with no map.
- Scenes are DM-only pins dropped on the Location, each with free-form notes. A starter framework is offered and
  optional. Pins can be faded so the map stays usable.
- Combat encounters are separate. "Add All Tokens" fills one from the map's tokens. A group of the same monster added
  together shares one Initiative, lettered A, B, C.
- The DM sees names, hidden creatures, AC, HP and Initiative. Players see the order and whose turn it is.

What D&D Beyond's users ask for most:
- the monster's stat block beside the Initiative order;
- editing a monster's Hit Points and rolling its attacks from there;
- a Bloodied marker;
- the distance while dragging a token;
- condition timers by round;
- DM notes on the map;
- switching maps while keeping each one's tokens and fog;
- a "players can see this map" switch;
- the encounter builder and the map being one place (today DMs enter everything twice).

What they like: it's simple, light and works on any device. One DM put it as "close to how you play on a real table".
Several want fog left manual: "I like that control in my hands".

**Foundry VTT.** A Scene is a map with its tokens, walls, lights and fog, plus journal notes pinned on it.
- The most popular add-ons store an encounter's creatures with a note on the scene and drop them into the fight in one
  click (Quick Encounters, GM's Drawer). Its users are building the "scene holds its creatures" idea themselves.
- Powerful, but setup is the complaint: walls and lighting take hours ("4 hours setting up a 4 hour game").
- Desktop-first; poor on phones.

**Roll20.** Pages (maps), a GM layer for hidden tokens, a turn tracker the GM opens.
- Group Initiative is an add-on script.
- Users say it's dated, with features behind a paywall, and uneven on phones.

**Owlbear Rodeo.** The simplest: scenes, tokens, hand-drawn fog, a basic Initiative tracker.
- Loved for having almost no setup and for working on phones.
- Thin on automation.

Sources:
- [How to Use Scene Prep](https://www.dndbeyond.com/posts/2236-how-to-use-scene-prep-d-d-beyonds-new-prep-tool)
- [Combat tracking comes to Maps](https://www.dndbeyond.com/posts/1841-roll-for-initiative-combat-tracking-comes-to-the)
- [Prep made easy](https://www.dndbeyond.com/posts/1856-prep-made-easy-getting-ready-for-your-online)
- [32 features missing from Maps](https://www.dndbeyond.com/forums/d-d-beyond-general/d-d-beyond-feedback/228828-32-features-missing-from-the-mapsvtt-roadmap)
- [Quick Encounters](https://foundryvtt.com/packages/quick-encounters)
- [Foundry vs Roll20 vs Owlbear, 2026](https://gmcrafttavern.com/foundry-vs-roll20-owlbear-2026/)
- [Roll20 Turn Tracker](https://help.roll20.net/hc/articles/360039178634)
- [Owlbear Rodeo extensions](https://extensions.owlbear.rodeo)

## How askdnd's table works, from that

- **A place and its scenes** (D&D Beyond's model, so the DM knows it already; with Foundry's creatures added):
  - A *place* has one map or none.
  - On the map are its tokens: the party, and the creatures the DM put there, hidden or shown.
  - Each place keeps its own fog.
  - Its *scenes* are the DM's pins on it, each with her notes in the shape she sent (all optional).
  - Switching places keeps every place's tokens and fog as they were.
  - Players see only the place the DM shows them.
  - A place can be a World place, so its pictures and the Map tab carry over.
- **The creatures are prepared on the map.** Setting up the encounter is placing it, so nothing is entered twice.
  Start a fight takes in every token on the map, as "Add All Tokens" does.
- **Everything D&D Beyond's users ask for, built in from the start:**
  - the stat block beside the order, with Hit Points and the creature's rolls;
  - Bloodied;
  - feet while dragging;
  - condition timers (askdnd's already exist);
  - notes on the map;
  - "Players see this place".
- **Simple first, like Owlbear and Maps.**
  - Fog is drawn by hand, and a whole room is revealed in one click when the file has walls.
  - Vision from walls and lights comes later (3.7). Foundry's users find that setup the costliest part.
  - Nothing to set up for a map from Dungeon Alchemist: its grid comes with it.
- **One Initiative per group of the same creature, lettered.** The DM splits a group by typing a number for one of them.

## The slices

All of them go behind Labs › askdnd's VTT, built in this session on the branch `jettison-v/table` and tried on
staging. The table moves at the end.

| # | Slice | What it adds |
|---|---|---|
| 2 | Your turn's bar | Under the middle: movement left (− and + 5 ft, Dash), what you've used of your Action, Bonus Action and Reaction, your Battle pins by cost, End turn. Off your turn: Reactions and a readied action. |
| 3 | Creatures in the side panel | A creature's stat block from the campaign's books, then the SRD; its Hit Points with − and + for the DM, Bloodied for players; its actions rolled in askdnd, damage with Apply to. On its turn, the bottom bar is the creature's. |
| 4 | Phones | The table page at 375px: the turn bar on top, Table rolls as its thin line, your bar and the side panel as sheets. |
| — | The DM's scene notes | Scenes with her sections (Intro read-aloud, Purpose, Outcomes, Location info, Activities, Scene summaries, @ links). The DM's alone (`docs/plans/2026-11-06-dm-scene-notes.md`). |
| 5 | Places and their maps | A place with a map: a picture with its grid set by hand, or a Universal VTT file (.dd2vtt) with its grid and walls. Scenes are pins on it. Players see the place the DM shows. |
| 6 | Tokens | The party's tokens (pictures, Hit Points, conditions, reminders), the DM's creatures from the books and the SRD (hidden ones only hers), your creatures beside you. Dragging. |
| 7 | askdnd runs the fight | Start a fight takes in the map's tokens. Players roll their own Initiative; creatures are rolled for the DM, one per group. Then the order, Begin, Next turn, Undo and battle settings. D&D Beyond's VTT is no longer listened to here. |
| 8 | Moving and measuring | Feet while dragging, Difficult Terrain the DM paints, leaving a creature's reach, the table's diagonal rule. |
| 9 | Fog | Show and hide by squares, a whole room, all; each place keeps its own. |
| 10 | Spell areas | The area tool; Cast starts it; who's in it carries to the saves and Apply to. |

**When Brett looks:** once slices 2 to 6 run on staging, there's a map with tokens, the scene notes and the bars to
judge. The rest follows his notes.

## How it's built (Claude's choices, in product terms)

- **Places, scenes and tokens are rows of their own.** Many people drag tokens at the same moment, so a token is one
  row and a move changes only that row. A place keeps its map, grid, walls and fog.
- **askdnd's fight is the same fight everything already follows.**
  - It's kept where D&D Beyond's fight is kept (`Campaign.fight`, marked as askdnd's), so these work unchanged: the
    fight band, Party's Rows, reminders, conditions that end, Concentration's rounds, a familiar's turn and Initiative
    from Battle.
  - While it runs, what D&D Beyond's VTT reports is ignored.
- **The map is drawn by the browser itself**, with no drawing library: one picture with tokens placed over it, moved
  and zoomed with CSS. That keeps a large map smooth on an iPhone without a new download. If a large Dungeon Alchemist
  map turns out slow on the iPhone, a drawing library replaces only the map's middle.
- **Maps are kept in askdnd's file storage** (S3 under `v2/`), never in git.
- **Moves are announced like everything else** (`realtime.announce`). Each page fetches what it may see, so a hidden
  token never reaches a player's browser.
