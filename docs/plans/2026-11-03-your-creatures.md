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
2. **Its Hit Points, synced.** − and + on its Hit Points tile, Temporary Hit Points, and the hit points window's Apply to for a creature, through the bridge (`creature_hp:<id>`), read back from the sheet like everything else; Summon and Dismiss (`creature_active:<id>`). Extension 0.10.0 adds the two requests; an older one says to update. A live test run on Vi's Homunculus.
3. **In the fight.** The fight's rows (Party's Rows, askdnd's table) and the fight band list a creature under its master, or by its own Initiative when D&D Beyond's VTT has it as its own fighter; the DM sees it like any fighter; a turn reminder when its turn comes.
4. **Help, the tour, a live run per creature kind, and out of Labs** once the table has played with it.

## Needs Brett

- A familiar on a test seat, so a creature with its own Initiative is tested too: on Levi's sheet on D&D Beyond, **Extras › Manage Extras**, add an **Owl** to the **Familiar** group (slice 1).
- Upload extension 0.10.0 when slice 2 is ready (the same steps as 0.9.9).
