# From table companion to virtual tabletop (2026-10-22)

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

This changes two lines of `docs/BRIEF.md` ("won't replace D&D Beyond as the character sheet or the VTT" and "no
DM-only features"): askdnd now aims to be the VTT, and the DM gets their own tools.

## How we build it: one site, a VTT switch, a test campaign (decided 2026-10-22)

- **Table Assistant (TA)** is the name for askdnd as the table uses it today. It isn't a separate copy: it's askdnd
  with the VTT switched off. Small TA improvements keep coming as the table plays.
- **One `main` branch, no long-lived VTT branch.** Phase 1 rewrites the pages TA uses every session (Battle, HP,
  slots), so two branches would drift and every TA fix would need copying by hand. Each TA fix or VTT step goes on a
  short branch (days, not weeks), opens a pull request, and merges into `main` after CI passes.
- **One site** (beta.askdnd.ai now; **askdnd.ai once legacy retires**).
- **A VTT switch per campaign.** VTT pieces merge early but stay hidden until switched on. The table's campaign keeps
  it off; a **test campaign** for Brett and the DM has it on (multiple campaigns come with step 10). Releasing a piece
  to the table means switching it on for their campaign, and it can be switched back off.
- **Testing before it ships:** CI on every pull request, and each change tried on the local copy of beta's data
  (`scripts/pull_beta.sh`).
- **Safety:** no deploys on game night; database changes add before they remove; Railway rollback and the nightly
  backup are the safety net.
- **Considered and left for later: a VTT preview site** (a second Railway environment where code lands before the
  table site). The tests, the local copy of real data and the switch cover most of what it would protect against;
  add it if something ever slips through to the table.
- Set up as Phase 0 item 0.1 (S), right after step 10 and the Railway cleanup. The step-by-step goes in
  `docs/SETUP_LOG.md` as it's built.

## Effort and priority

Sizes at today's pace (Claude builds, Brett reviews on beta): **S** a day or two · **M** about a week · **L** 2–3
weeks · **XL** a month or more. **Core** = needed for the VTT to replace D&D Beyond Maps; **Nice** = worth it, not
required.

## Principles (every phase)

One place instead of five tabs · automation the DM can overrule (the DM makes every ruling) · nothing changes
silently (play log with undo) · no setup tax · the story remembers itself (play feeds recaps) · inform, don't
advise.

## Phases

**Phase 0, Foundations.** 0.1 One site, a VTT switch, a test campaign (above) S core · 0.2 Finish data organization
(step 10) L core, in progress · 0.3 Live table connection (WebSockets; changes within a second) M core · 0.4 Play log
with undo M core · 0.5 File storage for the campaign (S3 `v2/`) M core · 0.6 Rules content as data (SRD 5.2; DM
creations in the database, never the public repo) M core · 0.7 Finish the Railway cleanup (step 12) S core.

**Phase 1, Live character state (first).** 1.1 Hit points askdnd owns, typed damage with resistances M core · 1.2
Casting spends slots, upcasting, concentration M core · 1.3 Class resources and uses M core · 1.4 Short and long
rests, party rest M core · 1.5 Inventory in play (quantities, potions, charges, ammo, coins, attunement, giving,
loot) L core · 1.6 Conditions with durations, Exhaustion M core · 1.7 D&D Beyond merge (build in, play state kept,
what changed) M core · 1.8 Party at a glance for the DM S core · 1.9 Level-up companion S nice · 1.10 House rules for
what askdnd automates (each common table rule a switch on Manage › House rules, applied where askdnd does that
thing: critical hit damage, potions as a bonus action, flanking, rest variants; added 2026-10-23) M core, partly built.
Milestone: a whole session's bookkeeping in askdnd; D&D Beyond only for building and leveling.

**Phase 2, Combat.** 2.1 Encounters (2024 DMG budget) L core · 2.2 Initiative and turns M core · 2.3 Clickable stat
blocks L core · 2.4 Attacks and saves that resolve, DM confirms L core · 2.5 Reactions at the right moment M nice ·
2.6 What players see of monsters S core · 2.7 Fights flow into the recap S nice.
Milestone: a whole fight in askdnd.

**Phase 3, Maps and tokens.** 3.1 Map canvas L core · 3.2 Tokens L core · 3.3 Movement and measuring M core · 3.4
Fog of war M core · 3.5 Spell areas M core · 3.6 Scenes M core · 3.7 Walls, doors and vision XL nice · 3.8 Import
.dd2vtt maps M nice · 3.9 Draw and ping S nice · 3.10 Story map M nice.
Milestone: a session on askdnd's maps instead of D&D Beyond Maps.

**Phase 4, The DM's table tools.** 4.1 Show to the table S core · 4.2 Music and ambience M nice · 4.3 Sound effects S
nice · 4.4 Asset library M core · 4.5 Make stat blocks and items L core · 4.6 Session prep M core · 4.7 Secret rolls
and whispers S nice · 4.8 Paste-in import (Claude converts, DM checks) M nice.
Milestone: the DM runs a session's images, music and prepared content from askdnd.

**Phase 5, During play.** 5.1 Rules answers in play (from the brief) L core · 5.2 Table chat with rolls M nice · 5.3
Phones and tablets M nice · 5.4 Start-of-turn summary S nice · 5.5 Animated dice S nice.

**Phase 6, Voice and video (later).** 6.1 Voice and video in askdnd L nice · 6.2 One recording track per person L
nice · 6.3 Recording straight to recap L nice · 6.4 Live captions and catch-up M nice.
Milestone: a session with no Zoom and no MacWhisper.

**Phase 7, Other groups (not planned).** 7.1 Content and licensing check S, before sharing · 7.2 Invite another
group L nice · 7.3 Accounts and costs per group L nice.

## Decisions along the way

How screens update live (phase 0) · where monsters come from: SRD built in, DM-owned books entered by the DM and
kept in the database (phase 2) · how much map automation (phase 3) · music sources (phase 4) · video service and the
raw-transcript privacy rule (phase 6) · licensing before other groups (phase 7).

## Next

Brett lists the table's frustrations with D&D Beyond Maps, Foundry and Roll20; each is attached to the item that
fixes it. Then phases 0 and 1 become a detailed plan here, built in reviewed steps.
