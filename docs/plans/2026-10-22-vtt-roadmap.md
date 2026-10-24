# From table companion to virtual tabletop (2026-10-22, reviewed 2026-10-24)

The long-range plan for growing askdnd into a full virtual tabletop (VTT) for our table. The readable version, with
filters, is the "askdnd VTT Roadmap" artifact: https://claude.ai/artifact/EtCBFsKNwLK5LNhQjcbzS3. This file is the
record; the artifact is regenerated from it when it changes.

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
- **Testing before it ships:** CI on every pull request, each change tried on the local copy of beta's data
  (`scripts/pull_beta.sh`), and the piece tried in the test campaign on beta.
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
- **Rules content as data (0.6).** SRD 5.2 monsters, spells, items and conditions as data in `app/data/` (public,
  licensed); the DM's own creations and anything from purchased books in the database, never in the public repo.
  Stat blocks (2.3), resolving attacks (2.4) and rules answers in play (5.1) all read from it.
- **Testing the table, not just the server (0.8).** Pages now update each other live, which server tests can't see.
  A few browser tests drive two pages at once (a player and the DM) through the table's core flows on every pull
  request.

## Phases

Status as of 2026-10-24. **Needs:** says what must exist first.

**Phase 0, Foundations.** 0.1 One site, a VTT switch, a test campaign S core, **done 2026-10-23** · 0.2 Finish data
organization (step 10) L core, **done 2026-10-23** · 0.3 Live table connection M core, **done 2026-10-24**
(app/realtime.py: WebSockets through Postgres, so it holds with several copies of the app) · 0.4 Play state and the
play log with undo M core, *designed with 1.7, built with 1.1* · 0.5 File storage for the campaign (S3 `v2/`; moves
today's pictures out of the database) M core, *before Phase 3* · 0.6 Rules content as data (SRD 5.2; DM creations in
the database, never the public repo; rules answers are built on it, Brett 2026-10-23) M core, **done 2026-10-24**
(app/rules_data.py: the SRD 5.2.1 from the official PDF, plus each campaign's own in `campaign_content`) · 0.7
Finish the Railway cleanup (step 12) S core, **done 2026-10-23** · 0.8 Browser tests for the table's core flows (two
pages at once, on every pull request) S core, **done 2026-10-24** (tests/browser) · 0.9 Know when something breaks
(errors on beta reported to Brett, not found by the table) S core, **done 2026-10-24** (app/errors.py, Sentry).

**Phase 1, Live character state (first).** 1.1 Hit points askdnd owns, typed damage with resistances M core (needs
0.4) · 1.2 Casting spends slots, upcasting, concentration M core (needs 1.1's play state) · 1.3 Class resources and
uses M core · 1.4 Short and long rests, party rest M core (needs 1.1–1.3) · 1.5 Inventory in play (quantities,
potions, charges, ammo, coins, attunement, giving, loot) L core · 1.6 Conditions with durations, Exhaustion M core
(moves today's conditions and concentration into play state) · 1.7 D&D Beyond merge (build in, play state kept, what
changed) M core, *designed first, with 0.4* · 1.8 Party at a glance for the DM S core · 1.9 Level-up companion S nice
· 1.10 House rules for what askdnd automates (each common table rule a switch on Manage › House rules, applied where
askdnd does that thing: critical hit damage, potions as a bonus action, flanking, rest variants; added 2026-10-23) M
core, partly built (one roll for all, such as Magic Missile's darts, and the DM's rulings on a spell).
Order: design 0.4 + 1.7 together (mockup of the play log and "what changed"), then 1.1, 1.2, 1.3, 1.6, 1.4, 1.5,
1.8, 1.9; 1.10's switches arrive with the item each one changes.
Milestone: a whole session's bookkeeping in askdnd; D&D Beyond only for building and leveling.

**Phase 2, Combat.** 2.2 Initiative and turns M core (first: useful even before monsters are in askdnd) · 2.3
Clickable stat blocks L core (needs 0.6) · 2.6 What players see of monsters S core (needs 2.3) · 2.4 Attacks and saves
that resolve, DM confirms L core (needs 1.1, 2.3) · 2.1 Encounters (2024 DMG budget) L core (needs 2.3) · 2.5
Reactions at the right moment M nice · 2.7 Fights flow into the recap S nice (reads the play log).
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
- **Play state and the D&D Beyond merge** (phase 1): the design above is the proposal; the per-field merge rules
  and the play log's look are decided with Brett's mockup review before 1.1 is built.
- **Where monsters come from** (phase 2): SRD built in, DM-owned books entered by the DM and kept in the database.
- **How much map automation** (phase 3).
- **Music sources** (phase 4).
- **Video service and the raw-transcript privacy rule** (phase 6).
- **Licensing before other groups** (phase 7).
- **When askdnd.ai moves to v2 and legacy retires** (Brett, any time; not tied to a phase).

## Next

1. **Brett:** list the table's frustrations with D&D Beyond Maps, Foundry and Roll20; each is attached to the item
   that fixes it (still open).
2. **The play state foundation:** a written design (0.4 + 1.7: what askdnd owns, the merge rules, the play log,
   two people at once) and a mockup of the play log and "what changed", reviewed by Brett; then 1.1 Hit points as
   the first piece, in the test campaign.
