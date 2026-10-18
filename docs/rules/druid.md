# Druid rules that askdnd models (2024 Player's Handbook)

Our own short summary for building features. It isn't the book's text and doesn't replace it; the DM makes every ruling.
Sources read on 2026-10-18: the Druid and Circle of the Moon feature text on D&D Beyond (Cole's live sheet, all levels)
and the D&D Beyond Basic Rules (Druid class and Circle of the Land). **Circle of the Sea and Circle of the Stars are still
to be checked against the Player's Handbook** (not in the free rules).

## Wild Shape (Druid 2+), and what `app/wild_shape.py` does with it

| Rule | Detail | In askdnd |
|---|---|---|
| Uses | 2 (level 2), 3 (6), 4 (17). One back on a Short Rest, all on a Long Rest | Read from D&D Beyond |
| Action / duration | Bonus Action to shift; lasts half Druid level in hours; ends on another Wild Shape, Incapacitated or death; leave early as a Bonus Action | Battle cards and notes |
| Known forms / max CR / fly | 4 / 1/4 / no (level 2); 6 / 1/2 / no (4); 8 / 1 / yes (8). Swap one known form per Long Rest | Planner limits |
| Temporary HP | Druid level when you shift | Shown |
| Game statistics | Beast's stat block, but you keep creature type, HP, Hit Dice, Int/Wis/Cha, class features, languages, feats, and skill/save proficiencies (your PB); use the Beast's modifier if higher | Computed per form |
| Spells | Can't cast, but Concentration isn't broken | Except as below |
| Equipment | Falls, merges (no effect) or is worn; DM decides what fits | Note; item bonuses left out |

## Other Druid features that touch Wild Shape

- **Wild Companion (2):** Magic action, spend a slot or a Wild Shape use to cast Find Familiar (no Material components); Fey familiar until a Long Rest. Casting, so not in a form before level 18.
- **Wild Resurgence (5):** once per turn with no uses left, spend a slot for a use; once per Long Rest, spend a use for a level 1 slot.
- **Elemental Fury (7):** choose Potent Spellcasting (add Wis to Druid cantrip damage) or **Primal Strike** (once on each of your turns, a hit with a weapon or a Beast form's attack deals +1d8 Cold, Fire, Lightning or Thunder). Level 15: Potent Spellcasting adds 300 ft to cantrips with 10+ ft range; Primal Strike becomes 2d8.
- **Beast Spells (18):** cast spells in Beast form, except spells whose Material component has a cost or is consumed.
- **Archdruid (20):** regain a use on Initiative if you have none; once per Long Rest turn uses into one spell slot (2 levels per use).
- Primal Order (1): Magician (extra cantrip, + Wis to Arcana/Nature) or Warden (Martial weapons, Medium armor). Druidic: Speak with Animals always prepared.

## Circle of the Moon

- **Circle Forms (3):** max CR for a form = Druid level ÷ 3 (round down); AC = 13 + Wis modifier if higher than the Beast's; temp HP = 3 × Druid level.
- **Circle of the Moon Spells (3):** always prepared, **and castable in a Wild Shape form**: Cure Wounds, Moonbeam, Starry Wisp (3); Conjure Animals (5); Fount of Moonlight (7); Mass Cure Wounds (9).
- **Improved Circle Forms (6):** Lunar Radiance (a form's attacks can deal Radiant instead, chosen on each hit); Increased Toughness (+ Wis modifier to Con saves).
- **Moonlight Step (10):** Bonus Action teleport 30 ft + Advantage on the next attack this turn; Wis modifier uses (min 1) per Long Rest, or spend a level 2+ slot per use.
- **Lunar Form (14):** once per turn +2d10 Radiant on a hit with a form's attack; Moonlight Step can bring a willing creature within 10 ft.

## Circle of the Land

- **Circle Spells (3):** after each Long Rest choose arid, polar, temperate or tropical; that land's spells are prepared. No casting in a form.
- **Land's Aid (3):** Magic action, spend a Wild Shape use: 10-ft Sphere within 60 ft, Con save vs spell DC, 2d6 Necrotic (half on success); one creature there heals 2d6. 3d6 at 10, 4d6 at 14.
- **Natural Recovery (6):** one free Circle spell per Long Rest; after a Short Rest recover slots totalling half Druid level (round up), none level 6+, once per Long Rest.
- **Nature's Ward (10):** immune to Poisoned; Resistance by land (Fire, Cold, Lightning, Poison).
- **Nature's Sanctuary (14):** Magic action, spend a Wild Shape use: 15-ft Cube within 120 ft for 1 minute; you and allies get Half Cover there, allies get your Nature's Ward Resistance; Bonus Action to move it 60 ft.

## Circle of the Sea, Circle of the Stars

To check against the Player's Handbook. Both spend Wild Shape uses on something other than a Beast form (Sea: Wrath of the Sea; Stars: Starry Form), which askdnd lists under "Other ways to use Wild Shape" from the sheet's own text.
