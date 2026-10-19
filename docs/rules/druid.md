# Druid rules that askdnd models (2024 Player's Handbook)

Our own short summary for building features. It isn't the book's text and doesn't replace it; the DM makes every ruling.
Sources read on 2026-10-18: the Druid class and all four Circles in the Player's Handbook (2024) on D&D Beyond, plus
Cole's live sheet. The repo is public, so this stays a summary in our own words, never the book's text.

## Wild Shape (Druid 2+), and what `app/wild_shape.py` does with it

| Rule | Detail | In askdnd |
|---|---|---|
| Uses | 2 (level 2), 3 (6), 4 (17). One back on a Short Rest, all on a Long Rest | Read from D&D Beyond |
| Action / duration | Bonus Action to shift; lasts half Druid level in hours; ends on another Wild Shape, Incapacitated or death; leave early as a Bonus Action | Battle cards and notes |
| Known forms / max CR / fly | 4 / 1/4 / no (level 2); 6 / 1/2 / no (4); 8 / 1 / yes (8). Swap one known form per Long Rest | Planner limits |
| Temporary HP | Druid level when you shift (3 × with Circle Forms, below) | Shown |
| Game statistics | Beast's stat block, but you keep creature type, HP, Hit Dice, Int/Wis/Cha, class features, languages, feats, and skill/save proficiencies (your PB); use the Beast's modifier if higher | Computed per form: feats' and class features' bonuses and Advantage included; species traits left out |
| Spells | Can't cast, but Concentration isn't broken | Except as below |
| Equipment | Falls, merges (no effect) or is worn; DM decides what fits | Note; item bonuses only when ticked under Kept in Wild Shape › Equipment |

## Audit: what carries into Wild Shape (2026-10-19)

Brett's belief table checked against the summary above (from the PHB read on 2026-10-18) and the code.

| Belief | Rule (our summary) | Verdict | In askdnd now |
|---|---|---|---|
| Feats: kept (all) | Feats are on the list of what you keep | Correct | Feat numbers apply in a form (e.g. Alert's Proficiency Bonus on Initiative, a feat's Speed bonus) and feat Advantage is marked. Was missing; fixed. Background/level Ability Score Improvements aren't listed as feats |
| Class and subclass features: kept, including multiclass | "Class features" are kept, with no limit to Druid ones | Correct. Whether one works in the Beast's body is the DM's call | Monk features show as "Yours". Class-feature bonuses now carry (Primal Order's Magician +Wis to Arcana and Nature was missing; fixed). Unarmored Defense / Movement stay DM toggles (Brett, 2026-10-19) |
| Species traits: lost | Not on the keep list, so the Beast's stat block replaces them | Correct. Nuance: a skill proficiency your species gave you is still a skill proficiency, which you keep | Fixed: species actions (Mask of the Wild) no longer show as "Yours"; species Advantage (Fey Ancestry) isn't marked in a form; the form's senses replace Darkvision. The form's notes list the lost traits |
| Creature type: kept | On the keep list | Correct | Said in the form's notes |
| HP and Hit Dice: kept, plus temp HP = 3 × Druid level | HP and Hit Point Dice kept. Temp HP = Druid level; Circle Forms makes it 3 × | Partly: 3 × is Circle of the Moon only | Already right (Cole, Moon Druid 6: 18; other Circles get their Druid level) |
| Int/Wis/Cha kept; Str/Dex/Con are the Beast's | Same | Correct | Already right |
| Skills and saves: your proficiencies with your PB, plus the Beast's; use the higher | Same: keep skill and save proficiencies with your PB, gain the Beast's, and use the stat block's modifier where it's higher | Correct | Already right; the hover now shows both numbers when the form's is used |
| Languages and speech: kept, and you can speak | Languages are kept. This summary records no rule about speaking, either way | Languages correct; speech **not confirmed** | Says you keep your languages; says nothing about speaking |

Feats in a form, the nuance: **War Caster** gives Advantage on Constitution saving throws *to maintain Concentration*, not on every Constitution save. D&D Beyond's modifier carries that condition, and askdnd marks it that way (a dashed Adv badge on Con, with the condition on hover). Cole's Lucky (Luck Points) also stays; it doesn't change a number.

To check in the book (Brett, private/books on the Mac):
- Whether the 2024 Wild Shape text says anything about speaking in a form.
- That a feat's Speed bonus (e.g. Mobile) applies to a form's walking Speed only, as askdnd does, and not its swim/climb/fly speeds (otherwise the DM's call).


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

## Circle of the Sea

- **Circle of the Sea Spells (3):** always prepared: Fog Cloud, Gust of Wind, Ray of Frost, Shatter, Thunderwave (3); Lightning Bolt, Water Breathing (5); Control Water, Ice Storm (7); Conjure Elemental, Hold Monster (9). Not castable in a Beast form.
- **Wrath of the Sea (3):** Bonus Action, spend a Wild Shape use: a 5-ft Emanation of ocean spray around you for 10 minutes (ends if dismissed, used again, or Incapacitated). When it appears, and as a Bonus Action on later turns, one creature you can see in it makes a Con save vs your spell DC or takes Cold damage (d6s equal to your Wis modifier, min 1) and, if Large or smaller, is pushed up to 15 ft.
- **Aquatic Affinity (6):** the Emanation becomes 10 ft; you gain a Swim Speed equal to your Speed.
- **Stormborn (10):** while Wrath of the Sea is active: Fly Speed equal to your Speed, and Resistance to Cold, Lightning and Thunder.
- **Oceanic Gift (14):** put the Emanation on a willing creature within 60 ft instead (it uses your DC and Wis); or spend two uses to have it on both of you.

## Circle of the Stars

- **Star Map (3):** a Tiny star chart, usable as a Spellcasting Focus. While holding it: Guidance and Guiding Bolt prepared, and free Guiding Bolt casts equal to your Wis modifier (min 1) per Long Rest. A lost map is remade in a 1-hour ceremony during a rest.
- **Starry Form (3):** Bonus Action, spend a Wild Shape use to take a starry form *instead of* shape-shifting. You keep your own game statistics; you shed Bright Light 10 ft and Dim Light 10 ft more; it lasts 10 minutes (ends if dismissed, Incapacitated, or used again). Choose a constellation each time:
  - *Archer:* on activation and as a Bonus Action later, a ranged spell attack at a creature within 60 ft for 1d8 + Wis Radiant.
  - *Chalice:* when a slot-cast spell restores HP, you or a creature within 30 ft also regains 1d8 + Wis.
  - *Dragon:* on Int or Wis checks and Con saves to keep Concentration, treat a d20 roll of 9 or lower as 10.
- **Cosmic Omen (6):** after each Long Rest roll a die: even (Weal) lets you use a Reaction to add 1d6 to a D20 Test of a creature you can see within 30 ft; odd (Woe) subtracts 1d6. Uses equal to Wis modifier (min 1) per Long Rest.
- **Twinkling Constellations (10):** Archer and Chalice become 2d8; Dragon also gives a 20-ft Fly Speed with hover; you can switch constellation at the start of each of your turns.
- **Full of Stars (14):** in Starry Form, Resistance to Bludgeoning, Piercing and Slashing damage.

## What this means for askdnd

- Only Circle of the Moon changes Beast forms (CR, AC, temp HP, spells in a form, extra damage). Land, Sea and Stars spend Wild Shape uses on other things (Land's Aid, Nature's Sanctuary, Wrath of the Sea, Starry Form); the Wild Shape tab lists those from the character's own sheet under "Other ways to use Wild Shape", open by default for those Circles.
- Beasts: the 2024 Monster Manual has 91 Beasts. The SRD 5.2 list we store has 90 of them with matching AC, HP, CR and attacks (checked 2026-10-18); only the Giant Squid (CR 6) is missing, and the SRD adds the Giant Fly. One difference: the SRD gives the Swarm of Insects a 20-ft Fly Speed that D&D Beyond's Monster Manual entry doesn't list.
