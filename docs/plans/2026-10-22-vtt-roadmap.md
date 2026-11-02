# From table companion to virtual tabletop (2026-10-22, reviewed 2026-10-24, reordered 2026-10-26, statuses and order of work 2026-10-27)

The long-range plan for growing askdnd into a full virtual tabletop (VTT) for our table. **The one page Brett reads is
the askdnd Roadmap** (`docs/roadmap.html`, published at https://claude.ai/artifact/EtCBFsKNwLK5LNhQjcbzS3; master
since 2026-10-28, one list since 2026-11-02): everything left to do in order, then what's done, then every plan and
mockup with whether it's current. The VTT's slices are in `docs/plans/2026-11-02-vtt-build-plan.md`. This
file is the detail behind it (how we build, principles, each item's reasoning); when a status changes, change both.

## Decided (Brett, 2026-10-22)

- **Audience:** our table, without ruling out other groups later (each piece is built so it could serve another
  group; nothing is built for that until asked).
- **First area:** live character state.
- **D&D Beyond:** characters are built and leveled there (it holds the purchased books); askdnd owns everything
  during play. D&D Beyond can't be written to, so its changes merge in without overwriting play state.
- **Voice and video:** later, nice to have.
- **Built to scale and kept clean** (Brett, 2026-10-24): each piece is built the way it would hold up with more
  copies of the app, more tables and more data, even when that takes more effort; what a change makes unnecessary or
  contradictory (code, docs) is removed in the same change.

This changed two lines of `docs/BRIEF.md` ("won't replace D&D Beyond as the character sheet or the VTT" and "no
DM-only features"); the brief says so.

## How we build it: one site, a VTT switch, a test campaign (decided 2026-10-22, built 2026-10-23)

- **Table Assistant (TA)** is the name for askdnd as the table uses it today. It isn't a separate copy: it's askdnd
  with the VTT switched off. Small TA improvements keep coming as the table plays.
- **One `main` branch, no long-lived VTT branch.** Phase 1 rewrites the pages TA uses every session (Battle, HP,
  slots), so two branches would drift and every TA fix would need copying by hand. Each TA fix or VTT step goes on a
  short branch (days, not weeks), opens a pull request, and merges into `main` after CI passes;
  `scripts/deploy_check.py` follows it to beta.
- **One site** (beta.askdnd.ai now; **askdnd.ai once legacy retires**, when Brett says so).
- **A VTT switch per campaign** (app/vtt.py). Each item below ships as one or more **pieces** registered in
  `vtt.PIECES`, merged early and hidden. The **test campaign** ("VTT test", with test copies of the characters) sees
  every piece; releasing a piece to the table means its DM or an admin switches it on in Manage › Settings, and it can
  be switched back off. An item is **built** when its piece works in the test campaign and **released** when the
  table's campaign has it on.
- **Testing before it ships:** CI on every pull request (including the width check: every main page at 375, 768,
  1000 and 1280px, tests/browser/test_layout.py), each change tried on the local copy of beta's data
  (`scripts/pull_beta.sh`), and the piece tried in the test campaign on beta.
- **A layout sweep at the end of each phase** (Brett, 2026-10-26): `scripts/layout_sweep.py` over every page of the
  local copy of real data, as each role, at five widths, plus a look over its screenshots; fixes go in before the next
  phase starts, so new work isn't built on layout problems.
- **Safety:** no deploys on game night; database changes add before they remove; Railway rollback and the nightly
  backup are the safety net.
- **Considered and left for later: a VTT preview site** (a second Railway environment). The tests, the local copy of
  real data and the switch cover most of what it would protect against; add it if something ever slips through.

## Effort and priority

Sizes at today's pace (Claude builds, Brett reviews on beta): **S** a day or two · **M** about a week · **L** 2–3
weeks · **XL** a month or more. **Core** = needed for the VTT to replace D&D Beyond Maps; **Nice** = worth it, not
required.

## Principles (every phase)

One place instead of five tabs · automation the DM can overrule (the DM makes every ruling) · nothing changes
silently (play log with undo) · no setup tax · the story remembers itself (play feeds recaps) · inform, don't
advise · built to scale, kept clean.

**Don't over-automate** (Brett, 2026-10-26). askdnd does the bookkeeping (numbers, what's left, what changed) and
**reminds** the table of the checks and rulings that follow, with what's needed (a Concentration save and its DC,
death saves at 0 HP); people roll and decide. A reminder becomes automatic only after playtests on beta show the
table wants it. The DM controls the game.

## How the VTT is built (the shared foundations; added 2026-10-24)

Each phase leans on the same few foundations. They're built once, in Phase 0, and every later item uses them rather
than inventing its own.

- **Live connection (0.3, done).** Every open page holds a WebSocket to its campaign (app/realtime.py). A change
  calls `realtime.announce()`; after the commit it travels through Postgres (NOTIFY/LISTEN) to every copy of the app
  and on to every page at that table. Today a message says only *what* changed and the page fetches it at the usual
  address, which decides who sees what. **Every item that changes something the table sees announces it**; an item
  isn't done until other pages update without a reload.
  - *Phase 3 will extend it:* dragging a token can't wait for a fetch, so public, frequent changes (a token's
    position) will carry their data, sent at most ~10 times a second per token. Anything not everyone may see (a
    hidden monster, fog) goes on a **DM channel** or is filtered per viewer, never on the table's channel.
- **Play state and the play log (0.4 with 1.7).** Today's play state is scattered: `wild_shape`, `concentration` and
  `conditions` are columns on `characters`, and they aren't announced live. Phase 1 replaces that with one design:
  - **Play state:** what askdnd owns during play (hit points, temporary HP, slots, resource uses, conditions,
    concentration, Wild Shape, inventory counts), per character per campaign, so a test copy has its own.
  - **Play log:** every change to play state is a log entry (who, what, before, after, why: "Fireball, 28 fire,
    resisted"), shown to the table, and **Undo** applies the reverse entry. The log is how changes are announced,
    recapped (2.7) and audited; it's never edited in place.
  - **D&D Beyond merge (1.7):** a refresh updates what D&D Beyond owns (max HP, slots per level, items owned, features)
    and never what askdnd owns (current HP, slots spent). Where they meet (max HP went down below current HP, an item
    was removed) the rule is written down per field, and the player sees "what changed".
  - **Two people at once:** each change names the state it started from; if someone else changed it first, the
    second is refused with the new value instead of silently overwriting.
  - The three existing columns move into play state in the same change and are removed (no two places for one fact).
- **Files (0.5).** Maps, handouts and tokens are too large for the database. Pictures live in the database today
  (`entity_pictures`, `note_images`); 0.5 moves them to S3 (`v2/` prefix), served through askdnd with the same access
  checks, cached by Cloudflare, with size limits on upload. Built before Phase 3, which depends on it.
  *Before Phase 3–4 (maps, audio):* files that size shouldn't pass through the app. After askdnd's access check, send
  a short-lived signed S3 link instead (with the same caching), so the app never holds a request while a large file
  downloads (2026-10-24: a page of 23 pictures through the app showed the limits; fixed for pictures by giving the
  database connection back before each download).
- **Rules content as data (0.6).** SRD 5.2 monsters, spells, items and conditions as data in `app/data/` (public,
  licensed); the DM's own creations and anything from purchased books in the database, never in git.
  Stat blocks (2.3), resolving attacks (2.4) and rules answers in play (5.1) all read from it.
- **Testing the table, not just the server (0.8).** Pages now update each other live, which server tests can't see.
  A few browser tests drive two pages at once (a player and the DM) through the table's core flows on every pull
  request.

## Phases

Status as of 2026-10-27. **Needs:** says what must exist first.

**Phase 0, Foundations.** 0.1 One site, a VTT switch, a test campaign S core, **done 2026-10-23** · 0.2 Finish data
organization (step 10) L core, **done 2026-10-23** · 0.3 Live table connection M core, **done 2026-10-24**
(app/realtime.py: WebSockets through Postgres, so it holds with several copies of the app) · 0.4 Play state and the
play log with undo M core, *designed with 1.7, built with 1.1* · 0.5 File storage for the campaign (S3 `v2/`; moves
today's pictures out of the database) M core, **done 2026-10-27** (app/files.py: pictures live only in S3 `v2/files/`;
the database copies were checked against S3 and dropped) · 0.6 Rules content as data (SRD 5.2; DM
creations in the database, never in git; rules answers are built on it, Brett 2026-10-23) M core, **done
2026-10-24** (app/rules_data.py: the SRD 5.2.1 from the official PDF, plus each campaign's own in `campaign_content`) · 0.7
Finish the Railway cleanup (step 12) S core, **done 2026-10-23** · 0.8 Browser tests for the table's core flows (two
pages at once, on every pull request) S core, **done 2026-10-24** (tests/browser) · 0.9 Know when something breaks
(errors on beta reported to Brett, not found by the table) S core, **done 2026-10-24** (app/errors.py, Sentry).

**Table Assistant since 2026-10-24** (not VTT items; on for everyone): the new-player tour and Help › What askdnd
adds (?), the Party page rebuilt (a card per character, then the party's spells and items with the shared filters),
a simpler Table rolls sidebar (open or closed on a computer), a width check on every pull request, and no inline
styles on any page.

**Reordered 2026-10-26 (Brett).** The play state was first designed as screens of its own (an HP window, a play log
in Table rolls) before the table had anywhere to play together, which made each interaction a trip into one
character's page. So the fight screen comes first, and hit points and the play log live on it. Item numbers stay as
they were, so earlier notes still match.

**Phase 1, The fight screen (first).** 2.2 Initiative and turns as the table's shared fight screen M core: the party
and the DM's enemies ("Enemy 1"…) in turn order, whose turn it is, each one's HP; everyone sees it live (0.3). On it:
1.1 Hit points (damage with its type and resistance, healing, temporary HP by the 2024 rules), made on D&D Beyond
through the bridge and counted once read back, the Concentration and death save reminders, and the fight's log (the
DM undoes a line). A damage roll in Table rolls can go to someone on the screen. The play state design
(`docs/plans/2026-10-24-play-state.md`, rewritten 2026-10-28 for the bridge: D&D Beyond keeps a character's numbers,
askdnd keeps the fight and enemies, so no second copy and no merge) has the buckets. 1.8 Party at a glance for the DM
S core is the same screen outside a fight (the Party page, rebuilt 2026-10-26, already shows everyone's numbers).
1.7 D&D Beyond merge is no longer needed: D&D Beyond keeps the numbers, so a level-up just comes through. Mock up the fight screen first.
Milestone: a fight's turn order and HP in askdnd, with the table watching the same screen.

**Phase 2, Live character state.** 1.2 Casting spends slots, upcasting, concentration M core · 1.3 Class resources
and uses M core · 1.6 Conditions with durations, Exhaustion M core (moves today's conditions and concentration into
play state) · 1.4 Short and long rests, party rest M core (needs 1.2, 1.3) · 1.5 Inventory in play (quantities,
potions, charges, ammo, coins, attunement, giving, loot) L core · 1.9 Level-up companion S nice · 1.10 House rules
for what askdnd automates M core, partly built (each switch arrives with the item it changes).
Order: 1.2, 1.3, 1.6, 1.4, 1.5, 1.9. Each shows on the fight screen where it matters (slots, conditions) and on the
character's own pages.
Two ways, always (Brett, 2026-10-27): askdnd takes over during play, but if someone uses D&D Beyond for anything, by
accident or on purpose, it still syncs: a change made in askdnd is made on D&D Beyond and confirmed, and a change made
on D&D Beyond comes into askdnd within seconds (the bridge). Both always agree, or the difference is shown, for data
quality and so the table trusts the tool.
Milestone: a whole session's bookkeeping in askdnd, and D&D Beyond agrees with every number.

**Phase 2b, The rest of combat.** 2.3 Clickable stat blocks L core (needs 0.6) · 2.6 What players see of monsters S
core (needs 2.3) · 2.4 Attacks and saves that resolve, DM confirms L core (needs 1.1, 2.3) · 2.1 Encounters (2024
DMG budget) L core (needs 2.3) · 2.5 Reactions at the right moment M nice · 2.7 Fights flow into the recap S nice
(reads the play log).
Milestone: a whole fight in askdnd.

**Phase 3, Maps and tokens** (needs 0.5, and the live connection's data-carrying and DM channels above). 3.1 Map
canvas L core · 3.2 Tokens L core · 3.3 Movement and measuring M core · 3.4 Fog of war M core · 3.5 Spell areas M core
· 3.6 Scenes M core · 3.7 Walls, doors and vision XL nice · 3.8 Import .dd2vtt maps M nice · 3.9 Draw and ping S nice
· 3.10 Story map M nice · 3.11 Table dice: everyone's rolls thrown across the screen in each player's own dice S nice,
**built 2026-10-23** behind the VTT switch (piece `table_dice`), not yet released.
Milestone: a session on askdnd's maps instead of D&D Beyond Maps.

**Phase 4, The DM's table tools.** 4.1 Show to the table S core (needs 0.5) · 4.2 Music and ambience M nice · 4.3
Sound effects S nice · 4.4 Asset library M core (needs 0.5) · 4.5 Make stat blocks and items L core (needs 0.6) · 4.6
Session prep M core · 4.7 Secret rolls and whispers S nice, *partly built* (DM-only and just-me rolls, 2026-10-22;
whispers remain) · 4.8 Paste-in import (Claude converts, DM checks) M nice.
Milestone: the DM runs a session's images, music and prepared content from askdnd.

**Phase 5, During play.** 5.1 Rules answers in play (from the brief) L core (needs 0.6) · 5.2 Table chat with rolls M
nice (Table rolls are its start) · 5.3 Phones and tablets M nice (TA pages work on phones; this is the map and combat)
· 5.4 Start-of-turn summary S nice (needs 2.2) · 5.5 Animated dice S nice, **done 2026-10-23**: thrown 3D dice in
each player's own set, and admins tune how they move (Manage › Dice tuning, 2026-10-24).

**Phase 6, Voice and video (later).** 6.1 Voice and video in askdnd L nice · 6.2 One recording track per person L
nice · 6.3 Recording straight to recap L nice · 6.4 Live captions and catch-up M nice.
Milestone: a session with no Zoom and no MacWhisper.

**Phase 7, Other groups (not planned).** 7.1 Content and licensing check S, before sharing · 7.2 Invite another
group L nice · 7.3 Accounts and costs per group L nice.

## Decisions along the way

- **How screens update live** (phase 0): decided 2026-10-24, WebSockets through Postgres NOTIFY/LISTEN (above).
- **Play state and the D&D Beyond merge** (phase 1): reviewed by Brett 2026-10-26 (`docs/plans/2026-10-24-play-state.md`,
  mockup `docs/mockups/play-state.html`); where it shows moved to the fight screen the same day.
- **Where the data lives** (before 2.3): decided 2026-10-27 (`docs/plans/2026-10-27-data-strategy.md`): four
  buckets, a campaign's books checked once, and D&D Beyond confirming every change instead of a partial sync.
- **Where monsters come from** (phase 2): SRD built in, DM-owned books entered by the DM and kept in the database.
- **How much map automation** (phase 3).
- **Music sources** (phase 4).
- **Video service and the raw-transcript privacy rule** (phase 6).
- **Licensing before other groups** (phase 7).
- **When askdnd.ai moves to v2 and legacy retires** (Brett, any time; not tied to a phase).

## Next: the order of work (Brett, 2026-10-27: one list of what's done and what's left)

The D&D Beyond bridge (`docs/artifacts/ddb-bridge.html`, merged switched off 2026-10-27) changes how Phases 1 and 2
reach D&D Beyond: instead of askdnd keeping its own hit points and merging, every change is made on D&D Beyond and
read back. So the bridge's changes come first, then the fight screen and live character state use them.

1. **The shorter Manage menu** (**done** 2026-10-27: two doors, Manage for the campaign and ⚙ Admin for askdnd, round 2 option A; mockup `docs/mockups/manage-menu.html`, approved 2026-10-27): six items, a section
   list down the left, an askdnd admin Overview, askdnd's History renamed.
2. **Bridge polish** (**done** 2026-10-27, through the sheet's own store): no reloading the sheet after askdnd changes it (the sheet should take the new numbers in
   place; today every open copy reloads so none saves an old number back); log "Changed on D&D Beyond" even when
   askdnd's own refresh read the change first.
3. **Bridge changes, everything a player changes in play** (**done** 2026-10-27, each checked live on Vi; checked against Foundry's DDB Importer, which syncs the
   same list; askdnd already hears all of them through its reads, so each is the writing half plus its read-back):
   - a. Hit points and their neighbours: hit points and temporary (**done**), death saves, Heroic Inspiration,
     Exhaustion and conditions, hit dice (as a Short Rest: the only way D&D Beyond takes them).
   - b. Spells: spell slots, Pact Magic slots. Prepared spells moved to 1.2 casting (Brett, 2026-10-27).
   - c. Class resources and limited uses (Rage, Wild Shape, Channel Divinity, an item's uses).
   - d. Inventory: an item's count (**done**), equipped, attuned, charges, coins, adding and removing an item, moving
     it into or out of a container.
   - e. Rolls made on D&D Beyond come into Table rolls (heard on the sheet, the way Beyond20 does; labelled "on D&D
     Beyond"), so a roll made there by habit still reaches the table. askdnd's rolls aren't written into D&D Beyond's
     game log: the table watches askdnd, and it would mean imitating D&D Beyond's own client.
   - Left out on purpose: experience points, custom names and custom items (D&D Beyond stays for building and
     leveling).
4. **The bridge for the table** (built 2026-10-28: a VTT piece each campaign switches on; the listing waits on review):
   switch it on for beta (today it refuses to run in production), point the extension
   at beta, and share it as an unlisted Chrome Web Store listing; Brett tells the table the risk first.
5. **The fight screen** (Phase 1: 2.2 with 1.1 and the play log): the play state design is updated for "D&D Beyond
   confirms every change" (**done** 2026-10-28, `docs/plans/2026-10-24-play-state.md`). **Reordered 2026-10-28
   (Brett):** the table plays on D&D Beyond's VTT, which already handles turns, so what it's missing comes first:
   Game Mode for the table and the Live pill, the change rule, change marks, then hit points with the working (Wild
   Shape aware: the form's resistances and Temporary Hit Points), then forgotten effects. The fight screen's own
   turn order is parked until playtests ask for it. Mockup next: Battle's HP window in Wild Shape. It starts with Game Mode and the bridge as one switch and one status
   (decided 2026-10-28, `docs/mockups/game-mode-and-bridge.html`): Game Mode for the whole table, the Live pill about
   your own sheet. Every control that changes a D&D Beyond number works only while that character's sheet can be
   reached now (its extension heard it in the last minute or so); otherwise pressing it says how in place and queues
   nothing, and a change already waiting gives up a few minutes after that sheet was last heard (then it's listed to
   make by hand). The mockup also shows how a change appears (Brett, 2026-10-28): a number that changed, from
   D&D Beyond or in askdnd, marks itself for a moment; it goes in app.js `showInPlace`, the one way every page shows a new
   copy, so it works the same everywhere.
6. **Live character state** (Phase 2: 1.2 casting with prepared spells, 1.3 resources, 1.6 conditions, 1.4 rests, 1.5 inventory), each on
   the bridge change it needs from step 3.

Alongside, whenever there's room:
- **Brett:** list the table's frustrations with D&D Beyond Maps, Foundry and Roll20; each is attached to the item
  that fixes it (still open).
- **The Monster Manual's beasts in Wild Shape** (**done** 2026-10-27, live on beta; data strategy decision 8): the one-book proof of the books model,
  labelled "MM 2024", switchable per campaign, stored only in the database.
- Rules answers (5.1) stay later (Brett, 2026-10-26). askdnd.ai moves to v2 when Brett says.

**First, 2026-10-28: the end-of-day review's fixes** (2026-10-27, one small change): the bridge works out a slot's or
use's most from the sheet, not the page; a roll made to the DM on D&D Beyond reaches the DM; an intent that changes
nothing alone isn't marked made when its batch stops; a storage outage answers Not found per picture, not an error;
Manage's counts count without building Needs you; a campaign's Beasts are read once, not on every page. Design system:
add the Manage menu's one line of other pages and its counts, the jump list, Battle's bar, and (once the table has
it) the bridge page's tiles.

Done on 2026-10-27 (evening): the shorter Manage menu (two doors), bridge steps 2 and 3, the Monster Manual's Beasts,
the SRD text fix, help lines removed from every page (the tour and Help explain them), and the end-of-day code and
design system review.

Done on 2026-10-27: the code and design system review, the roadmap statuses, the test suite review, the data
strategy (decided), Battle's header scrolling with the page, pictures only in S3 (0.5's last step), and the D&D Beyond bridge proof (repairs itself,
awake only while someone uses askdnd or a sheet, admin timers). Done since 2026-10-24: the tour (all three parts),
the play state review.
