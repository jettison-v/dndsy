# Play state and the fight screen (Phase 1: 2.2 with 1.1 and the play log) — rewritten 2026-10-28

Phase 1 of the VTT roadmap (`docs/plans/2026-10-22-vtt-roadmap.md`): the table's shared fight screen, with hit
points and the fight's log on it. This is the design the fight screen's mockup is drawn from; nothing here is built
yet.

**What changed since the first version (2026-10-24, reviewed by Brett 2026-10-26).** That version had askdnd keep its
own copy of the numbers that change in play (a `play_state` table, a version number per change, and a merge with D&D
Beyond on every read). The D&D Beyond bridge (2026-10-27, for the table since 2026-10-28) replaced that: **D&D Beyond
keeps a character's numbers, and askdnd makes its changes there and counts them once it reads them back** (Brett: no
partial sync; correct in both places, or the difference shown). So there is no second copy to merge, and what moved
to the fight screen on 2026-10-26 stays there. Brett's 2026-10-26 answers that still hold are kept under Decisions;
the old mockup `docs/mockups/play-state.html` is superseded by the fight screen's.

## What the table actually needs (Brett, 2026-10-28, speaking for the table until they answer)

The table plays on **D&D Beyond's own VTT**, which already handles turns well and most of the bookkeeping. What it
leaves to the table:

- **Damage math out loud in Wild Shape**: D&D Beyond doesn't know the form, so the Beast's resistances and the form's
  Temporary Hit Points are worked out by hand on every hit.
- **Forgotten effects**: Concentration saves after damage, conditions and when they end, potions and item charges.

So askdnd's first job in a fight is what D&D Beyond's VTT is missing, not another turn tracker. The list below is my
earlier guess, kept for the record; the two above are the ones that count.

## The frustrations I first guessed (2026-10-24)

From how the table plays today (Zoom, D&D Beyond sheets and Maps, askdnd beside them) and what tables commonly
report about D&D Beyond, Foundry and Roll20. Each points at the item that fixes it.

| Frustration | Where it comes from | Fixed by |
|---|---|---|
| "Whose turn is it?" and "what round is it?" | Turn order lives in the DM's notes or head | 2.2 the fight screen: turn order everyone sees live |
| Damage math out loud: "28 fire, I'm resistant, so 14, minus my 5 temp…" | D&D Beyond's sheet takes a number, not a typed hit | 1.1 typed damage with the working shown |
| The DM asks "how's everyone's HP?" every round | Each player's sheet is in their own tab | The fight screen (and 1.8 Party at a glance outside a fight) |
| Nobody knows who changed what; a mis-click means fixing numbers by hand | D&D Beyond, Roll20: changes are silent, no undo | The fight's log, with the DM's undo |
| Concentration forgotten after taking damage | Nothing prompts the save | 1.1 + 1.2: damage while concentrating reminds of the Con save (DC shown) |
| Two places for the same number, out of sync | askdnd read D&D Beyond every 2–3 minutes | **Done**: the bridge (both ways, within seconds) |
| Rests: resetting every resource by hand, forgetting some | Per-resource checkboxes | 1.4 rests list what comes back |
| Potions and charges forgotten; "I always forget my hat and my cloak" | Inventory isn't part of play | 1.5 inventory in play |
| Conditions and their end forgotten ("until the end of your next turn") | No durations | 1.6 conditions with durations, ended on the fight screen's turns |
| Maps live in a separate tab; tokens don't know HP | D&D Beyond Maps, Roll20 | Phase 3 (tokens are the characters) |
| Setup tax: hosting, modules that break, paid tiers | Foundry, Roll20 | Principle: nothing to install or host (the bridge is one Chrome extension) |

## Where each number lives

| D&D Beyond, through the bridge (a character's own numbers) | askdnd (the fight, and what D&D Beyond has no place for) |
|---|---|
| Hit points, temporary HP, death saves, Hit Dice spent | The fight: who's in it, turn order, whose turn, the round |
| Spell slots and Pact Magic slots spent | Enemies and NPCs in the fight ("Enemy 1"): their HP, conditions |
| Class resources and an item's uses spent, charges | Concentration, Wild Shape's form, effects with their source (an item's Invisible) |
| Items, quantities, equipped, attuned, coins | The fight's log: who did what, and why |
| Conditions and Exhaustion, Heroic Inspiration | Pins, notes and reminders (the player's own) |

Rule of thumb: if D&D Beyond's sheet has a place for it, D&D Beyond keeps it and askdnd changes it through the bridge;
if it doesn't (the fight, enemies, why a number changed), askdnd keeps it. A level-up just comes through: D&D Beyond
already keeps damage taken, so current HP rises with the max, as Brett wanted.

## How a change is made (the same for every number)

1. Someone changes something on the fight screen (or on Battle, Sheet, Party). askdnd works out the result by the
   2024 rules (damage below) and shows its working.
2. **Only while the sheet can be reached** (decided 2026-10-28): the character's own D&D Beyond sheet has been heard
   by its player's extension in the last minute or so. Then the change is made on D&D Beyond as that player, and
   counted once askdnd reads it back. Otherwise the control says how in place (add the askdnd bridge to Chrome and
   open your sheet, or make it on D&D Beyond) and nothing is queued; phones always change on D&D Beyond. A change
   already waiting gives up a few minutes after that sheet was last heard and is listed to make by hand.
3. **Changes are relative** ("takes 14", "spends a 2nd-level slot"), worked out against what D&D Beyond holds when
   they're made, so two people changing one character never overwrite each other; one that no longer makes sense
   ("no Potion of Healing left") is listed with why, never forced. This replaces the first version's version numbers.
4. **Every screen shows it the one way** (decided 2026-10-28): the change announces itself on save
   (`realtime.TABLE_SEES`; the fight's own records join that list) and every page showing it swaps its new copy in
   place (app.js `showInPlace`). **A number that changed marks itself for a moment** (Brett, 2026-10-28), whether it
   came from D&D Beyond, the fight screen or someone else's screen; it lives in `showInPlace`, so it works the same
   everywhere.
5. Enemies' numbers are askdnd's own, so their changes are made at once, the same way otherwise.

**The DM changing a player's character** (Brett, 2026-10-28: rare). Only the player's own browser writes their sheet.
When the DM applies 14 damage to Cole and Cole's sheet can be reached, it's made through Cole's extension as usual.
When it can't (Cole on a phone), it's listed on Cole's screen as "Take 14 (from the DM): make it on D&D Beyond",
ticked off when askdnd reads it, and Cole's HP shows as waiting.

## The fight screen (2.2)

- **One screen the whole table watches** (`/c/<campaign>/fight`, everyone sees it live): the party and the DM's
  enemies in turn order, whose turn it is, the round, and each one's HP and conditions.
- **The DM runs it:** starts a fight, adds enemies (from the SRD's monsters, the campaign's books or by hand, named
  "Enemy 1"…), moves the turn on, ends the fight. **Players roll their own initiative** (Brett: it creates suspense),
  in askdnd or on D&D Beyond, and it comes in through Table rolls; the DM rolls for enemies and can type any number.
  Players see it and change their own character from it.
- **Starting a fight starts Game Mode for the table** if it isn't on (Game Mode is one switch for the table:
  `docs/mockups/game-mode-and-bridge.html`).
- **Party at a glance (1.8)** is the same screen outside a fight: the Party page already shows everyone's numbers.
- **Enemies' HP shown to players:** the DM chooses per fight (exact, Bloodied or hidden), **hidden by default**. The DM
  gets a **battle settings menu** that keeps defaults like this one (Brett, 2026-10-28).

## Hit points (1.1)

- Click an HP number (the fight screen, Battle, Sheet, Party): **Damage · Heal · Temporary HP**, an amount, and for
  damage its type. askdnd applies the 2024 rules in order and shows its working before you confirm:
  1. Resistance halves (rounded down), vulnerability doubles, immunity makes it 0, with the reason from the sheet.
  2. Temporary HP absorbs first; the rest comes off HP.
  - **Gaining temporary HP:** by the 2024 rules (and on D&D Beyond) they don't add up; you keep the ones you have or
    take the new ones. askdnd picks the higher and the player can choose (Brett: rules as written, no house rule).
  3. What follows is a **reminder**, not done for the table (Brett: don't over-automate): at 0 HP, Unconscious and
     death saves (the player rolls as usual and marks them; damage at 0 is a failed death save, a critical hit two);
     massive damage (at least the max HP left over) is pointed out for the DM to rule. Healing from 0 clears the marks.
  4. Concentrating: a reminder, "Constitution save, DC 10" (or half the damage, up to 30), with the usual roll
     button and End concentration. Nothing ends concentration on its own, not even a failed save or 0 HP; the
     player or the DM does.
- **From a roll:** a damage result in Table rolls gets **Apply to…** (anyone on the fight screen), carrying the type
  and amount, with **Saved: half** for a save-for-half spell like Fireball. One click by a person (Brett); Phase 2
  targets automatically.
- The DM is never overruled: they can apply any amount to anyone, ignore resistance (a magical source the sheet
  doesn't know), or undo any line.

## The fight's log

Every change in a fight is one line: who (a person, "D&D Beyond"), which character or enemy, what changed (before →
after), and why in words ("Fireball from Enemy 1, 28 fire, halved: resistant (Fiendish Legacy)"). A damage line from
a table roll links to that roll. It builds on the bridge's log (`BridgeLog`: "From askdnd" and "On D&D Beyond"), so
there is one log, not two.

- **Where it shows:** on the fight screen (moved from Table rolls, 2026-10-26).
- **Cards group, lines stay separate** (Brett: group more, keep undo granular). A card is one thing that happened: a
  roll and everything it did, a hit and its Con save, or a run of changes to one character by one person.
- **Undo is the DM's** (Brett: uncommon, out of the way, not on players' screens): a quiet ⋯ on a line offers "Undo
  this line". It makes the reverse of what that line actually changed, as a change like any other (through the
  bridge for a character): undoing "took 14" heals 14, and a 60-point hit on someone with 29 HP left gave back 29. The
  line stays, crossed out, "Undone by the DM".
- **Who changes what:** a player changes their own character; the DM changes anyone in the campaign; admins too.
  Everyone at the table sees the log.
- **The story remembers itself:** 2.7 reads the log for the recap (knockouts, big hits, loot).

## Decisions

From Brett, 2026-10-26 (still holding):

1. The fight's log has cards that group (a roll with what it did, a run of changes); undo stays per line.
2. Undo is the DM's only for now, one line at a time, out of the way; players don't see it.
3. "Apply to…" on a damage roll in Phase 1.
4. No filters on the log for now.
5. Temporary HP follow the 2024 rules (no stacking), as on D&D Beyond; no house rule.
6. Don't over-automate: checks and rulings are reminders (the Concentration save and its DC, death saves); people
   roll and decide. Automation follows real playtest feedback.
7. Mockups use the table's own characters (Big C, Cole, Trah, No Name) and "Enemy 1", "NPC 1" for everyone else.

From Brett, 2026-10-28:

8. D&D Beyond keeps a character's numbers; askdnd changes them through the bridge and counts a change once it reads
   it back (replaces the first version's play state, versions and merge).
9. A change from askdnd only while that character's sheet can be reached; otherwise the control says how and nothing
   is queued.
10. Game Mode is one switch for the table; the Live pill says how your own sheet is kept in step.
11. Every page shows a new copy one way (`showInPlace`), and a changed number marks itself for a moment.
12. Players roll their own initiative (suspense).
13. Enemies' HP: the DM chooses per fight, hidden by default, in a battle settings menu that keeps the DM's defaults.
14. The DM's change to a player whose sheet can't be reached is listed for that player to make by hand (rare).
15. Hit points start from the roll: a damage or healing roll in Table rolls carries its amount and type, and Apply
    opens the window filled in; typing is for damage nobody rolled.
16. The player normally applies a hit to their own character; the DM can apply to anyone.
17. The Concentration save is the player's to roll after being hit, on their screen, also when the DM applied it.
18. The HP window: the types the character resists first; anyone can cross out a step, with the reason shown; the
    change mark is a green glow with the change for two seconds.

Superseded: the play log in the Table rolls sidebar (moved to the fight screen, 2026-10-26); a level-up raising
current HP (D&D Beyond already does).

## Built in buckets (reordered by Brett, 2026-10-28)

What D&D Beyond's VTT is missing comes first; the fight screen's own turn order waits for playtests. Each bucket is
one small pull request, tried in the test campaign (with Try it yourself) before the next starts, and hidden behind a
VTT piece until it's switched on for the table. Mockups: Battle's HP window in Wild Shape (`docs/mockups/hp-window.html`)
and the table-wide Game Mode with the Live pill (`docs/mockups/game-mode-and-bridge.html`).

| # | Bucket | What it adds | Size |
|---|---|---|---|
| 1 | Game Mode for the table, the Live pill | One switch for the campaign (anyone starts or ends it), the pill about your own sheet, the bridge pill to admins (`docs/mockups/game-mode-and-bridge.html`) | M |
| 2 | Changes only while the sheet can be reached | The rule above, and a waiting change giving up after its sheet was last heard | S |
| 3 | A changed number marks itself | In `showInPlace`, so every page and every source gets it | S |
| 4 | Hit points from a roll, with the working, Wild Shape aware | It starts from the roll (Brett, 2026-10-28): a damage roll (the DM's, for an enemy) or a healing roll (a party member's) in Table rolls carries its amount and type, and **Apply to Cole** opens his hit points window filled in; a roll is applied once. Normally the character's own player applies it; the DM can too, for anyone. The Concentration save is the player's to roll after being hit: its reminder and roll button are on the player's screen, also when the DM applied the hit. The 2024 rules as one tested function, with a form's resistances and immunities and its Temporary Hit Points; the Concentration reminder with its DC; made on D&D Beyond through the bridge. Without a roll (a trap), Hit points itself takes a number. Checked Oct 28: the DM's rolls reach a player's open sheet through the game log (the extension now hears them as well as the sheet's own), with the monster's name, the attack ("Ogre", "Greatclub"), to hit or damage, advantage, the dice and total, but **no damage type**; so the type comes from the monster's attack in the campaign's rules data (`rules_data.find`), and the window asks when the monster isn't there. A roll for the character made on another page (the encounter's) arrives the same way and goes into Table rolls too, once (its roll id) | M |
| 5 | Forgotten effects | Conditions that say when they end, potions and charges at hand on Battle; first find out whether the extension can hear D&D Beyond's own turn tracker (as it hears rolls), else a simple "next turn" for the DM | M |
| 6 | Death save reminders and the massive damage note | At 0 HP: the marks and the note for the DM | S |
| — | Parked: the fight screen's own turn order | Turn order, whose turn, the round, enemies, the fight's log and the DM's undo, the battle settings menu; after playtests show the table wants it (Apply from a roll moved into bucket 4) | — |

Then Phase 2 (1.2 slots, 1.3 resources, 1.6 conditions with durations…) uses the same change path.

## D&D Beyond's initiative order (checked Oct 29, on the test campaign's VTT)

Before step 5's "until the end of your next turn", Brett asked whether askdnd can hear, and maybe write, D&D Beyond's
own initiative order. Checked in Brett's Chrome with a temporary listener in the local extension (removed after):

- **Where it lives.** In the VTT (`/games/<campaign>`), on its own game server connection (`wss://games.dndbeyond.com/…`),
  separate from the Game Log. Opening the VTT sends `CONNECT` and gets a `SYNC` with the whole game: every token (with
  hit points and conditions, monsters too) and `game.encounter` (groups such as "Enemy" with their tokens, each
  entry's initiative, the round and the turn).
- **Hearing it.** Every change is a named action the server passes to every open VTT, with an index: Next is
  `INCREMENT_COMBAT_TURN`; changing a number is `UPDATE_INITIATIVE` with `[{group, key, initiative}]`. The VTT's code
  also has `CLEAR_ENCOUNTER`, `UPDATE_INITIATIVE_BONUS` and grouping actions. So the extension can hear the order,
  the round and whose turn it is, but **only on a VTT page**: a character sheet doesn't connect to the game server
  and heard nothing when the turn moved. Today the extension runs only on sheets; hearing turns means it also runs on
  `/games/*` for whoever has the VTT open (the DM at least).
- **Writing it.** Technically the same way the VTT does: the same action on the open VTT's own connection, as the
  signed-in person. But unlike the Game Log (whose messages name their source, so askdnd's say "askdnd" and ⓐ), these
  actions carry only `source: "CLIENT"`: anything askdnd sent would look exactly like the VTT's own click. That
  touches the standing rule against imitating D&D Beyond's client, so it's Brett's call, and nothing has been written
  beyond the test (Next once, the Ogre's initiative 9 → 10 → 9).

**Decided (Brett, Oct 29): hear only.** The extension listens on the VTT page; askdnd never writes the order. If players' initiative should reach the order, first check whether the VTT fills it from an askdnd Initiative roll in the Game Log (its "pending initiative").

## Conditions that end (designed Oct 29, `docs/mockups/turn-conditions.html`)

Decided by Brett: each condition can say how long it lasts (until it's ended; the start or end of someone's next turn; rounds; 1 minute; minutes or hours; until a save, with its ability, DC and when it's rolled), chosen in + Condition's **Lasts**. The turns come from D&D Beyond's VTT (heard, never written). When one runs out or asks for a save, a **corner card** reminds the character's player and the DM: End it / Keep, or Roll the save; nothing ends by itself. Battle's pills say it in a few words ("to your next turn", "Wis 13 save", "9 rounds"), and a click shows the whole of it with End it; a badge gets an amber dot on the turn it ends. A **fight band** above the name on every character page and on Party shows the round, whose turn, "you're next" and the order, only while a fight runs. Not heard (no VTT open), nothing is counted and no reminder comes; Concentration keeps +1.

To build, in order: the extension listening on the VTT page (a new extension version for the Chrome Web Store), askdnd keeping the fight (order, round, turn) per campaign and announcing it live, the fight band, then durations and their reminders.
