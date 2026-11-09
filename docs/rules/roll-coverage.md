# Roll coverage

Whether the roll card can play each thing on Battle, by `scripts/roll_coverage.py` from app/roll_plan.py for the party's saved sheets (tests/fixtures/ddb).
Ready: every number from a checked recipe, the sheet or askdnd's rules. Unchecked: a number from D&D Beyond's data or read from its words. Gap: its words have dice the plan doesn't roll; each has its reason (app/roll_plan.py `KNOWN_GAPS`). Don't edit this file: run the script.

**All together:** 54 ready · 7 unchecked · 13 gap · 79 no roll

## Big C

16 ready · 1 unchecked · 4 gap · 20 no roll

| Action | Cost | How it rolls | From | Status |
|---|---|---|---|---|
| Hammer of Thunderbolts (Maul) | Action | to hit +11 · 2d6+8 bludgeoning | the sheet | ready |
| Javelin | Action | to hit +10 · 1d6+7 piercing | the sheet | ready |
| Unarmed Strike | Action | Which Unarmed Strike · to hit +10 · 8 bludgeoning | askdnd's rule, the sheet | ready |
| Fire Bolt | Action | to hit +6 · 1d10 fire | checked recipe, the sheet | ready |
| Green-Flame Blade | Action | to hit +6 · 1d8 | read from its words, the sheet | gap: its words have 2d8, 3d8, which the plan doesn't roll (a 2024 spell outside the free rules with no recipe: needs a checked one (the second target's fire)) |
| Lightning Lure | Action | Str save DC 14 · 1d8 lightning | D&D Beyond's data, the sheet | unchecked |
| Word of Radiance | Action | Con save DC 14 · 1d6 radiant | checked recipe, the sheet | ready |
| Command | Action | Wis save DC 14 | the sheet | ready |
| Compelled Duel | Bonus action | Wis save DC 14 | the sheet | ready |
| Cure Wounds | Action | At what level · 2d8 | checked recipe, the sheet | ready |
| Divine Smite | Bonus action | At what level · 2d8 radiant | checked recipe, the sheet | ready |
| Healing Word | Bonus action | At what level · 2d4 | checked recipe, the sheet | ready |
| Hellish Rebuke | Reaction | At what level · Dex save DC 14 · 2d10 fire | checked recipe, the sheet | ready |
| Inflict Wounds | Action | At what level · Con save DC 14 · 2d10 necrotic | checked recipe, the sheet | ready |
| Branding Smite | Bonus action | 2d6 radiant | D&D Beyond's data | gap: its words have 1d6, which the plan doesn't roll (D&D Beyond's data rolls it on casting with no upcasting: needs a checked recipe (on the next hit, +1d6 a level)) |
| Find Steed | Action |  |  | gap: its words have 1d8, 2d8, which the plan doesn't roll (the dice are the steed's (its stat block, app/summons.py), not the caster's) |
| Hold Person | Action | Wis save DC 14 | the sheet | ready |
| Spiritual Weapon | Bonus action | At what level · to hit +6 · 1d8 force | checked recipe, the sheet | ready |
| Favored by the Gods | Other |  |  | gap: its words have 2d4, which the plan doesn't roll (adds 2d4 to a missed attack or failed save: the card's after-a-miss pill) |
| Opportunity Attack | Reaction | to hit +11 | the sheet | ready |
| Potion of Healing | Bonus action | 2d4+2 | checked recipe | ready |

## Cole

13 ready · 2 unchecked · 3 gap · 18 no roll

| Action | Cost | How it rolls | From | Status |
|---|---|---|---|---|
| Unarmed Strike | Action | Which Unarmed Strike · to hit +6 · 1d6+3 bludgeoning | askdnd's rule, the sheet | ready |
| Guidance | Action |  |  | gap: its words have 1d4, which the plan doesn't roll (adds 1d4 to an ability check: a pill on the check it's used on) |
| Starry Wisp | Action | to hit +7 · 1d8 radiant | checked recipe, the sheet | ready |
| Thorn Whip | Action | to hit +7 · 1d6 piercing | checked recipe, the sheet | ready |
| Absorb Elements | Reaction | 1d6 acid or cold or fire or lightning or thunder | D&D Beyond's data | unchecked |
| Cure Wounds | Action | At what level · 2d8 | checked recipe, the sheet | ready |
| Faerie Fire | Action | Dex save DC 15 | the sheet | ready |
| Healing Word | Bonus action | At what level · 2d4 | checked recipe, the sheet | ready |
| Heat Metal | Action | At what level · Con save DC 15 · 2d8 fire | checked recipe, the sheet | ready |
| Moonbeam | Action | At what level · Con save DC 15 · 2d10 radiant | checked recipe, the sheet | ready |
| Conjure Animals | Action | Dex save DC 15 · 3d10 slashing | checked recipe, the sheet | ready |
| Depth Charge | Action | Con save DC 15 · 7d6 thunder · 9d6 thunder | D&D Beyond's data, the sheet | gap: its words have 1d6, which the plan doesn't roll (a spell outside the free rules: needs a checked recipe) |
| Unarmed Strike | Bonus action | Which Unarmed Strike · to hit +6 · 1d6+3 bludgeoning | askdnd's rule, the sheet | ready |
| Flurry of Blows | Bonus action | to hit +6 · 1d6+3 bludgeoning | the sheet | ready |
| Uncanny Metabolism | Other | 1d6+2 | read from its words | unchecked |
| Opportunity Attack | Reaction | to hit +6 | the sheet | ready |
| Potion of Healing | Bonus action | 2d4+2 | checked recipe | ready |
| Soul Coin | Action |  |  | gap: its words have 1d10, which the plan doesn't roll (Drain Life's Temporary Hit Points: needs an item recipe) |

## No Name

10 ready · 1 unchecked · 4 gap · 23 no roll

| Action | Cost | How it rolls | From | Status |
|---|---|---|---|---|
| Sylvan Talon Dagger | Action | to hit +7 · 1d8+4 piercing | the sheet | ready |
| Vicious Quarterstaff | Action | to hit +7 · 1d8+4 bludgeoning | the sheet | ready |
| Dart | Action | to hit +7 · 1d4+4 piercing | the sheet | ready |
| Unarmed Strike | Action | Which Unarmed Strike · to hit +7 · 1d8+4 bludgeoning | askdnd's rule, the sheet | ready |
| Eldritch Blast | Action | to hit +4 · 1d10 force | checked recipe, the sheet | ready |
| Ray of Frost | Action | to hit +4 · 1d8 cold | checked recipe, the sheet | ready |
| Tasha's Hideous Laughter | Action | Wis save DC 12 | the sheet | ready |
| Unarmed Strike | Bonus action | Which Unarmed Strike · to hit +7 · 1d8+4 bludgeoning | askdnd's rule, the sheet | gap: its words have 1d6, which the plan doesn't roll (the Martial Arts die its words name for lower levels; the sheet's die is the one rolled) |
| Flurry of Blows | Bonus action | to hit +7 · 1d8+4 bludgeoning | the sheet | ready |
| Uncanny Metabolism | Other | 1d8+6 | read from its words | unchecked |
| Deflect Attack | Reaction |  |  | gap: its words have 1d10, which the plan doesn't roll (reduces the damage you take: a Reaction's own roll, not yet a step of the card) |
| Deflect Attack: Redirect Attack | Reaction | 2d8+4 | read from its words | gap: its words have 1d10, which the plan doesn't roll (the same reduction; the redirected damage is in the plan) |
| Opportunity Attack | Reaction | to hit +7 | the sheet | ready |
| Soul Coin | Action |  |  | gap: its words have 1d10, which the plan doesn't roll (Drain Life's Temporary Hit Points: needs an item recipe) |
| Potion of Healing | Bonus action | 2d4+2 | checked recipe | ready |

## Trah

15 ready · 3 unchecked · 2 gap · 18 no roll

| Action | Cost | How it rolls | From | Status |
|---|---|---|---|---|
| Shortsword | Action | to hit +5 · 1d6+2 piercing | the sheet | ready |
| Unarmed Strike | Action | Which Unarmed Strike · to hit +2 · bludgeoning | askdnd's rule, the sheet | ready |
| Fire Bolt | Action | to hit +7 · 1d10 fire | checked recipe, the sheet | ready |
| Mind Sliver | Action | Int save DC 15 · 1d6 psychic | checked recipe, the sheet | ready |
| Toll the Dead | Action | Wis save DC 15 · 1d8 necrotic · 1d12 necrotic | checked recipe, the sheet | ready |
| Burning Hands | Action | At what level · Dex save DC 15 · 3d6 fire | checked recipe, the sheet | ready |
| Chromatic Orb | Action | At what level · to hit +7 · 3d8 | checked recipe, the sheet | ready |
| Magic Missile | Action | At what level · 1d4+1 force | checked recipe, the sheet | ready |
| Suggestion | Action | Wis save DC 15 | the sheet | ready |
| Counterspell | Reaction | Con save DC 15 | the sheet | ready |
| Fireball | Action | At what level · Dex save DC 15 · 8d6 fire | checked recipe, the sheet | ready |
| Banishment | Action | Cha save DC 15 | the sheet | ready |
| Raulothim's Psychic Lance | Action | Int save DC 15 · 7d6 psychic | D&D Beyond's data, the sheet | gap: its words have 1d6, which the plan doesn't roll (a spell outside the free rules: needs a checked recipe) |
| Sickening Radiance | Action | Con save DC 15 · 4d10 radiant | D&D Beyond's data, the sheet | unchecked |
| Second Wind | Bonus action | 1d10+1 | read from its words | unchecked |
| Opportunity Attack | Reaction | to hit +5 | the sheet | ready |
| Keoghtom's Ointment | Action | 2d8+2 | read from its words | unchecked |
| Potion of Healing | Bonus action | 2d4+2 | checked recipe | ready |
| Potion of Healing (Superior) | Bonus action | 8d4+8 | checked recipe | ready |
| Soul Coin | Action |  |  | gap: its words have 1d10, which the plan doesn't roll (Drain Life's Temporary Hit Points: needs an item recipe) |
