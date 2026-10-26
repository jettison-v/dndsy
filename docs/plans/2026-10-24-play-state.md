# Play state and the play log (VTT 0.4 with 1.7, then 1.1 Hit points) — reviewed by Brett 2026-10-26

Phase 1 of the VTT roadmap (`docs/plans/2026-10-22-vtt-roadmap.md`) starts here: askdnd takes over the numbers
that change during play, so D&D Beyond is only for building and leveling. This is the shared foundation (0.4 play
log, 1.7 D&D Beyond merge) and its first piece (1.1 hit points). Mockup: `docs/mockups/play-state.html`.

Nothing here is built yet. Brett reviewed the mockup on 2026-10-26 (his answers are under Decisions); it's built in
small buckets, one pull request each (below).

## The frustrations this should fix (my list; Brett's own list will correct it)

From how the table plays today (Zoom, D&D Beyond sheets and Maps, askdnd beside them) and what tables commonly
report about D&D Beyond, Foundry and Roll20. Each points at the item that fixes it.

| Frustration | Where it comes from | Fixed by |
|---|---|---|
| Damage math out loud: "28 fire, I'm resistant, so 14, minus my 5 temp…" | D&D Beyond's sheet takes a number, not a typed hit | 1.1 typed damage with the reason shown |
| Nobody knows who changed what; a mis-click means fixing three numbers by hand | D&D Beyond, Roll20: changes are silent, no undo | 0.4 play log (the DM can undo) |
| The DM asks "how's everyone's HP?" every round | Each player's sheet is in their own tab | 1.8 party at a glance, fed by the play log |
| Concentration forgotten after taking damage | Nothing prompts the save | 1.1 + 1.2: damage while concentrating offers the Con save (DC shown) |
| Two places for the same number (D&D Beyond and askdnd), out of sync | askdnd reads D&D Beyond every 2–3 minutes | Play state owned by askdnd; 1.7 merges only build changes |
| Leveling up mid-campaign wipes or confuses current HP and slots | Re-importing a sheet resets play | 1.7: build changes come in, play state is kept, "what changed" listed |
| Rests: resetting every resource by hand, forgetting some | Per-resource checkboxes | 1.4 rests list what comes back |
| Potions and charges forgotten; "I always forget my hat and my cloak" | Inventory isn't part of play | 1.5 inventory in play |
| Conditions and their end forgotten ("until the end of your next turn") | No durations | 1.6 conditions with durations |
| Maps live in a separate tab; tokens don't know HP | D&D Beyond Maps, Roll20 | Phase 3 (tokens are the characters) |
| Setup tax: hosting, modules that break, paid tiers | Foundry, Roll20 | Principle: nothing to install or host |

## What askdnd owns, and what D&D Beyond still owns

| D&D Beyond (the build: changes when you level or shop) | askdnd (play: changes during a session) |
|---|---|
| Max HP, Hit Dice per class, AC, abilities, proficiencies | HP lost, temporary HP, death saves, Hit Dice spent |
| Spell slots per level, pact slots, spells known/prepared | Slots spent, pact slots spent, concentration |
| Class resources and their maximums (Wild Shape uses, Focus…) | Uses spent; Wild Shape form and its HP |
| Items owned, attunement slots | Quantities used (potions, ammo, charges), who holds what (1.5) |
| Resistances, immunities, vulnerabilities, senses | Conditions, Exhaustion level, item effects (Invisible…) |

Rule of thumb: if it changes because of a level-up or a purchase, it's D&D Beyond's; if it changes because of a
turn, it's askdnd's.

## Play state

One record per character per campaign (`play_state`), so a test copy in the test campaign has its own and the real
character is never touched. It holds what askdnd owns (table above) plus a `version` number.

- **HP is stored as damage taken**, not current HP: current = max − damage taken. When D&D Beyond's max goes up at a
  level-up, current goes up by the same amount, the same as D&D Beyond and the way most tables play it (Brett).
- **Starting point:** when the piece is switched on for a campaign, each character's play state starts from D&D
  Beyond's current numbers (damage taken, temp HP, slots and uses spent), so nothing jumps.
- **Where it moves from:** `characters.concentration`, `conditions` and `wild_shape` move into play state, each with
  the bucket that first changes it (concentration with bucket 6, conditions with 1.6, Wild Shape with 1.3), and its
  column is removed in that same change, so each fact always has one place.

## The play log

Every change to play state is one log entry: who (a person, "D&D Beyond", or "a rest"), which character, what
changed (before → after), and why in words ("Fireball from the Goblin Shaman, 28 fire, halved: resistant (Fiendish
Legacy)"). A damage entry from a table roll links to that roll.

- **Where it shows:** in the **Table rolls** sidebar, interleaved with the rolls: one feed of what happened at the
  table, not another place to look (Brett). Filters: All · Rolls · a third for changes to characters, its name
  Brett's pick from the mockup (Characters suggested; Brett found "Changes" didn't sound right).
- **Cards group, lines stay separate** (Brett: group more, keep undo granular). A card is one thing that happened:
  a roll and everything it did (each **Apply to…** target is a line in the roll's card), a hit and its Con save, or a
  run of changes to one character by one person. Each line is one log entry with before → after and why.
- **Undo is the DM's** (Brett: uncommon, so out of the way, and not on players' screens): a quiet ⋯ on a line
  offers "Undo this line". It applies the reverse of what that entry actually changed (an entry is never edited or
  deleted): undoing "took 14" heals 14, so it still works after later changes, and the line stays, crossed out,
  "Undone by Mary". A 60-point hit on someone with 29 HP left records 29 lost, so its Undo gives back 29, not 60.
  Players see no Undo anywhere, toasts included.
- **Who changes what:** a player changes their own character; the DM changes any character in the campaign; admins
  too. Everyone at the table sees the log (the table already sees each other's HP and rolls). DM-only entries arrive
  with Phase 2's monsters.
- **The story remembers itself:** 2.7 reads the log for the recap (knockouts, big hits, loot).

## Two people at once

Every change says which `version` of the play state it started from. If someone else changed the character first,
the change isn't applied; the person sees what's there now and can apply theirs on top in one click ("Mary set Cole
to 30 HP a moment ago. Apply your 8 damage to 30?"). Nothing is silently overwritten, and a slow connection can't
undo someone else's change.

## The D&D Beyond merge (1.7)

On each refresh, askdnd compares the build (left column above) with the last copy:

- Build changes come in; play state is kept, adjusted only where the build forces it, per field:
  - **Max HP up or down:** damage taken stays the same, so current moves with the max (at least 0).
  - **Slots per level go down** (rare: a respec): slots spent are capped at the new number.
  - **An item removed on D&D Beyond:** its play quantities go too (with a log entry).
  - **A resource's maximum changes:** uses spent are capped at the new maximum.
- If anything changed, one log entry by "D&D Beyond" lists it ("Level 8 → 9, max HP 51 → 60 (HP 37 → 46), new
  spell: Conjure Animals"), and Battle shows the same list once, with **Got it**.
- D&D Beyond's own play numbers (its HP box, slot checkboxes) are ignored once the piece is on. Battle says so once
  ("askdnd keeps your HP now; D&D Beyond's HP box won't change it").

## 1.1 Hit points (the first piece)

- Click the HP number (Battle, Sheet, Party): **Damage · Heal · Temporary HP**, an amount, and for damage its type.
  askdnd applies the 2024 rules in order and shows its working before you confirm:
  1. Resistance halves (rounded down), vulnerability doubles, immunity makes it 0, with the reason from the sheet.
  2. Temporary HP absorbs first; the rest comes off HP.
  - **Gaining temporary HP:** by the 2024 rules they don't add up; you keep the ones you have or take the new ones
    (askdnd picks the higher; the player can choose). Brett's table adds them up (28 + 28 = 56), so that's a house
    rule, **"Temporary HP add up"**, a switch on Manage › House rules (1.10), on for his campaign; the HP window then
    says "House rule" in its working, like the roll window does.
  3. At 0 HP: Unconscious and death saves; damage at 0 is a failed death save (a critical hit, two); damage that
     leaves you at 0 with at least your max HP left over is death (massive damage). Any healing from 0 clears the
     death saves.
  4. Concentrating: "Make a Constitution save, DC 10" (or half the damage, up to 30) with a Roll button.
- **From a roll:** a damage result in Table rolls gets **Apply to…** (any character in the campaign), carrying the
  type and amount, with **Saved: half** for a save-for-half spell like Fireball. Phase 2 does this automatically
  against targets; Phase 1 is one click by a person (Brett).
- The DM is never overruled: they can apply any amount to anyone, ignore resistance (a magical source the sheet
  doesn't know), or undo any line.
- **Live:** the change is announced (`realtime.announce`, kind `play`, the character id); Battle, Party and the
  sidebar update on every screen.

## How it's built (for the record)

- `app/play.py`: the only way play state changes: `apply(db, character, change, expected_version, actor)` validates,
  writes the state, writes the log entry, announces it; `undo(db, entry, actor)`. Damage math lives in one pure
  function with tests for every rule above.
- Tables: `play_state` (character, campaign, the owned numbers, version) and `play_log` (entries, never edited;
  `undoes` and `undone_by` link pairs). Migration adds both, copies the three existing columns, then drops them.
- VTT pieces: `play_hp` first (then `play_slots`, `play_resources`…). While a campaign has the piece off, askdnd
  reads D&D Beyond's numbers exactly as today.
- Tests: the damage rules (unit), concurrency (the second change is refused with the new state), undo after later
  changes and undo of a hit bigger than the HP left, the merge per field, and a browser test with a player and the DM: damage applied on one page shows on the
  other within a second, and the DM's Undo puts it back.

## Decisions (Brett, 2026-10-26)

1. The play log lives in the Table rolls sidebar.
2. A level-up raises current HP by the same amount as the max.
3. Undo is the DM's only for now, one line at a time, out of the way; players don't see it.
4. "Apply to…" on a damage roll in Phase 1.
5. Cards group more (a roll with what it did, a run of changes); undo stays per line.
6. "Changes" is renamed: the third filter's name is Brett's pick in the mockup.
7. Temporary HP add up at Brett's table: a house rule switch, since the 2024 rules say they don't.

## Built in buckets

Each bucket is one small pull request, hidden behind the VTT piece `play_hp` and tried in the test campaign (with
Try it yourself) before the next starts. The table sees none of it until the piece is switched on for TA.

| # | Bucket | What it adds | Size |
|---|---|---|---|
| 1 | Play state underneath | `play_state` and `play_log`, `app/play.py` (`apply()` with the version check), starting from D&D Beyond's numbers; Battle, Sheet and Party read HP from it. Nothing new to click. | S |
| 2 | The HP window | Damage · Heal · Temporary HP on Battle, with the 2024 rules as one tested function (resistance, temporary HP, 0 HP), the "Temporary HP add up" house rule, live on every screen | M |
| 3 | The play log | Cards and lines in Table rolls, All · Rolls · (third filter) | S |
| 4 | Apply to… | From a damage roll to any character, with Saved: half | S |
| 5 | The DM's undo | ⋯ on a line, the reverse of what was lost | S |
| 6 | Concentration and death saves | The Con save prompt with its DC, death saves at 0, massive damage; concentration moves into play state | M |
| 7 | D&D Beyond merge (1.7) | Build changes in, play kept, the "what changed" card | M |

Then 1.2 (slots) builds on the same play state and log.
