# Your creatures: build plan (Nov 3)

Brett chose Option B on [Your Creatures](https://claude.ai/artifact/MLSXxJLwP7Go3vuNrqZChS) (`docs/mockups/your-creatures/`, DECISIONS 2026-11-03): a creature a player controls (a familiar, an artificer's Homunculus Servant or Steel Defender, a ranger's companion, a summon) gets a switch by its master's name on Battle, **Vi · Homunculus**, and Battle becomes the creature's, the way Wild Shape shows a druid's form. A Labs feature, **Your creatures** (piece `creatures`), tried in VTT test first.

## What D&D Beyond gives us (checked on the test sheets, Nov 3)

- A sheet's `creatures` list carries each creature's stat block (`definition`: AC, average Hit Points, speeds, abilities, senses, traits, actions, bonus actions, reactions as text), its own name, `groupId`, `isActive`, and **its damage taken** (`removedHitPoints`, `temporaryHitPoints`).
- Groups, from D&D Beyond's own config: 1 Wild Shape (2014), 2 Familiar, 3 Beast Companion (2014), 4 Mount, 5 Pet, 6 Summoned, 7 Misc, 10 Battle Smith Defender, 11 Sidekick, 12 Infusion (Vi's Homunculus Servant), 13 Wild Shape (2024). Wild Shape forms stay Wild Shape's; every other group is one of *your creatures*.
- D&D Beyond's sheet changes a creature with `PUT /character/v5/creature/hp` (`id`, `removedHitPoints`, `temporaryHitPoints`) and `PUT /character/v5/creature/status` (`id`, `isActive`). Both tried on Vi's test sheet and put back.
- The extension sends only requests on its list (`extension/askdnd-bridge/ddb-page.js`), so syncing a creature's Hit Points needs **extension 0.10.0**: Brett uploads it for Google's review.
- D&D Beyond's stat block is the creature's at level 1 (Vi's Homunculus: 1 HP, +4, 1d4 + 2). Numbers that grow with the master are rules from the artificer's book, not the 2024 core: askdnd shows D&D Beyond's, and the DM corrects them (Correct this, as for items) until the book's rule is checked.

## Slices

1. **Battle as the creature (read only).** Read every creature that isn't a Wild Shape form, with its group and Hit Points as D&D Beyond keeps them. The switch by the name on Battle (only for a character with one, only with Labs › Your creatures on) draws Battle as the creature: Hit Points, AC, Speed, Initiative, abilities, its actions with Roll, bonus actions, reactions, traits and senses, and a line for its turn by its own rules (its own Initiative for a familiar; right after its master for a Homunculus, Steel Defender or summon; within its master's turn for a Primal Companion). Its rolls go to Table rolls as "Vi's Homunculus". Sheet gets a Creatures tab. Tried locally on the copy of beta, then on Vi's seat.
2. **Its Hit Points, synced** (built Nov 3; Brett chose D&D Beyond over askdnd keeping them). D&D Beyond shows a Homunculus Servant at its stat block's 1 Hit Point, so its maximum there is set to the rule's first (`PUT custom/value`, character value 43, tried on Vi's test sheet), on a press; then − and + keep both the same. Summon and Dismiss (`creature/status`) wait until there's a reason for them. Originally: − and + on its Hit Points tile, Temporary Hit Points, and the hit points window's Apply to for a creature, through the bridge (`creature_hp:<id>`), read back from the sheet like everything else; Summon and Dismiss (`creature_active:<id>`). Extension 0.10.0 adds the two requests; an older one says to update. A live test run on Vi's Homunculus.
## Round 2 slices (Creatures as Characters, all chosen Nov 4)

Built in order, each tried locally first, in Labs › Your creatures:

5. **Party, its own card, and no yellow line.** Party › Cards gives a creature its own card as the second half of its master's (board 7, A; linked as one card in two halves, board 8, C): picture ring, "Trah's familiar", Hit Points, AC, Speed, its turn, its senses; its master's card says "with Pip"; pressing it opens its Battle. A growing creature's maximum is set on D&D Beyond by askdnd itself after a read (first, and when its master's level or Intelligence changes), once per number, never over a number typed on D&D Beyond. **Built Nov 4.**
6. **Here, away, gone** (built Nov 4 with slice 7's casting window, askdnd's side: app/companions.py; D&D Beyond's Active switch and adding a form wait for extension 0.11.0). askdnd keeps where each familiar, steed or summon is (`Character` data, by its D&D Beyond id): a creature on Extras that was never cast through askdnd is *Not here*. Battle's band (board 3): Send to the pocket dimension, Bring back, Dismiss forever, Gone at 0 Hit Points; its master's own Battle offers See through its eyes and Deliver a touch spell only while it's here. Class companions are always here.
7. **Casting Find Familiar** (board 2): the Cast window's Your familiar part (one you've had or a new one, one at a time, its form, Celestial/Fey/Fiend, name, picture), and option A on D&D Beyond: add the form if missing (`POST creature`), name it (`PUT creature`), its type (character value, D&D Beyond's type override), Active (`PUT creature/status`), never delete. First: each request tried on a test sheet and put back, then extension 0.11.0 (Google's review). Pictures: uploaded by its player, kept by askdnd.
8. **Steeds, summons, Wild Companion** (board 5): numbers from the spell's level and its master's spell attack and DC; a summon tied to Concentration; Find Steed's "the one that disappeared or a different one"; Wild Companion from Wild Shape's uses, leaving at the Long Rest (listed there).
9. **The World entry** (board 4): a Companion entry, made the first time it's cast, its forms and story lines from reviewed recaps.

Then slice 3 (the fight) and slice 4 (Help, the tour, live runs, out of Labs) cover them all.

3. **In the fight.** The fight's rows (Party's Rows, askdnd's table) and the fight band list a creature under its master, or by its own Initiative when D&D Beyond's VTT has it as its own fighter; the DM sees it like any fighter; a turn reminder when its turn comes.
4. **Help, the tour, a live run per creature kind, and out of Labs** once the table has played with it.

## To work out with Brett (Nov 4)

- **Round 2, Creatures as Characters** (Brett, Nov 4; `docs/mockups/creatures-as-characters/`): a creature is a small character of its own that comes and goes by its rules. A familiar or summon exists only once cast (Brett, Nov 3); casting Find Familiar brings one the character has had or a new one (one at a time: otherwise a new form), with its form, Celestial/Fey/Fiend, name and picture; the pocket dimension, 0 Hit Points, Concentration and a Long Rest send it away; Party, the fight's rows and Campaign › World show it. D&D Beyond (checked Nov 4): its own page adds (`POST creature`), renames (`PUT creature`), removes (`DELETE creature`) and switches (`PUT creature/status`) a creature and customizes its size, type, alignment, AC, Hit Points and notes; no picture; all 16 creatures at our table are switched off. Brett chose **A** (Nov 4): askdnd keeps Extras in step (add the form if missing, name, type, Active; never delete), and sets a growing creature's maximum by itself, so the yellow line and its button go. Party, more visible: board 7, Brett chose **A**, its own card right after its master's.

## Needs Brett

- A familiar on a test seat, so a creature with its own Initiative is tested too: on Levi's sheet on D&D Beyond, **Extras › Manage Extras**, add an **Owl** to the **Familiar** group (slice 1).
- Upload extension 0.10.0 when slice 2 is ready (the same steps as 0.9.9).
