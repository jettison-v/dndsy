# The books' coverage

What askdnd's roll data plays from the 2024 Player's Handbook and DMG: every class feature, subclass feature, feat, species trait and magic item whose words hold dice, a saving throw or a bonus to a roll. Written by `scripts/books_coverage.py` from the offline books (names only); `tests/test_books_coverage.py` checks it.

**382 entries**: 142 played, 3 partly, 9 the sheet's numbers, 41 a save with nothing for the character to roll, 44 in words on purpose, 143 missing.

**Played** means askdnd's data has it: an `add` plays on every roll it changes; a `rolls` entry plays on the Battle row D&D Beyond lists for it (activated features are listed as actions). **Save only**: the target rolls the save; its DC is the sheet's. Magic items are listed for reference: an item's rolls are added as the table's characters carry it.

## Class and subclass features

| Name | Where | Has | askdnd |
|---|---|---|---|
| Tandem Footwork | Bard 6, College of Dance | bonus | **missing** |
| Mantle of Inspiration | Bard 3, College of Glamour | bonus | **missing** |
| Disciple of Life | Cleric 3, Life Domain | bonus | **missing** |
| Blessed Healer | Cleric 6, Life Domain | bonus | **missing** |
| Supreme Healing | Cleric 17, Life Domain | dice | **missing** |
| Improved Duplicity | Cleric 17, Trickery Domain | bonus | **missing** |
| Survivor | Fighter 18, Champion | bonus | **missing** |
| Undying Sentinel | Paladin 15, Oath of the Ancients | bonus | **missing** |
| Elder Champion | Paladin 20, Oath of the Ancients | save, bonus | **missing** |
| Foe Slayer | Ranger 20 | dice | **missing** |
| Celestial Resilience | Warlock 10, Celestial Patron | bonus | **missing** |
| Dark One’s Blessing | Warlock 3, Fiend Patron | bonus | **missing** |
| Intimidating Presence | Barbarian 14, Path of the Berserker | save | save only: the target rolls |
| Branches of the Tree | Barbarian 6, Path of the World Tree | save | save only: the target rolls |
| Beguiling Magic | Bard 3, College of Glamour | save | save only: the target rolls |
| Unbreakable Majesty | Bard 14, College of Glamour | save | save only: the target rolls |
| Telekinetic Adept | Fighter 7, Psi Warrior | save | save only: the target rolls |
| Abjure Foes | Paladin 9 | save | save only: the target rolls |
| Nature’s Wrath | Paladin 3, Oath of the Ancients | save | save only: the target rolls |
| Avenging Angel | Paladin 20, Oath of Vengeance | save | save only: the target rolls |
| Spell Thief | Rogue 17, Arcane Trickster | save | save only: the target rolls |
| Clairvoyant Combatant | Warlock 6, Great Old One Patron | save | save only: the target rolls |
| Psychic Blades | Rogue 3, Soulknife | dice | the sheet: a weapon on the sheet, with its own attack and damage |
| Relentless Rage | Barbarian 11 | save | in words: your own Con save (DC 10, up 5 each use): Table rolls' Con save |
| Jack of All Trades | Bard 2 | bonus | in words: in the sheet's check bonuses |
| Channel Divinity | Cleric 2 | dice, save | in words: each Channel Divinity option is its own entry |
| Greater Divine Intervention | Cleric 20 | dice | in words: how many Long Rests until it's back (2d4): Any dice |
| Corona of Light | Cleric 17, Light Domain | save | in words: Disadvantage on saves for enemies, the DM's roll |
| Druidic | Druid 1 | save | in words: a check others make to spot a message |
| Wild Shape | Druid 2 | bonus | in words: askdnd's Wild Shape forms (app/wild_shape.py) |
| Improved Circle Forms | Druid 6, Circle of the Moon | bonus | in words: askdnd's Wild Shape forms add it (app/wild_shape.py) |
| Star Map | Druid 3, Circle of the Stars | dice | in words: free Guiding Bolt casts, through the Cast window; the spell's own roll |
| Cosmic Omen | Druid 6, Circle of the Stars | dice | in words: acts on someone else's roll, after they see it |
| Twinkling Constellations | Druid 10, Circle of the Stars | dice | in words: Starry Form's dice, a named scale |
| Improved Combat Superiority | Fighter 10, Battle Master | dice | in words: the Superiority Die's size, a named scale |
| Relentless | Fighter 15, Battle Master | dice | in words: a d8 in place of a Superiority Die once a turn, said |
| Ultimate Combat Superiority | Fighter 18, Battle Master | dice | in words: the Superiority Die's size, a named scale |
| Monk’s Focus | Monk 2 | save | in words: the Focus save DC is the sheet's |
| Channel Divinity | Paladin 3 | save | in words: each Channel Divinity option is its own entry |
| Fey Wanderer Spells | Ranger 3, Fey Wanderer | dice | in words: a gift chosen or rolled once (1d6): Any dice |
| Reliable Talent | Rogue 7 | dice | in words: a check's floor, said by the player |
| Supreme Sneak | Rogue 9, Thief | dice | in words: a Cunning Strike option with no roll |
| Use Magic Device | Rogue 13, Thief | dice, save | in words: a d6 to keep charges: Any dice |
| Clockwork Spells | Sorcerer 3, Clockwork Sorcery | dice | in words: a manifestation chosen or rolled once: Any dice |
| Restore Balance | Sorcerer 3, Clockwork Sorcery | dice | in words: acts on someone else's roll |
| Bastion of Law | Sorcerer 6, Clockwork Sorcery | dice, bonus | in words: a ward of d8s the warded creature spends, kept by the player |
| Trance of Order | Sorcerer 14, Clockwork Sorcery | dice | in words: a d20's floor, said by the player |
| Wild Magic Surge | Sorcerer 3, Wild Magic Sorcery | dice | in words: a d20 after a spell and a d100 table: Any dice, the DM reads the table |
| Tides of Chaos | Sorcerer 3, Wild Magic Sorcery | dice | in words: Advantage on one D20 Test, the player's choice |
| Bend Luck | Sorcerer 6, Wild Magic Sorcery | dice | in words: acts on someone else's roll, after they see it |
| Tamed Surge | Sorcerer 18, Wild Magic Sorcery | dice, bonus | in words: a chosen Wild Magic Surge effect |
| Beguiling Defenses | Warlock 10, Archfey Patron | save, bonus | in words: half the damage back on a failed save, said |
| Create Thrall | Warlock 14, Great Old One Patron | bonus | in words: the summoned Aberration's own numbers |
| Arcane Ward | Wizard 3, Abjurer | bonus | in words: a ward's Hit Points, kept by the player |
| Portent | Wizard 3, Diviner | dice | in words: replaces a roll with a die rolled at dawn, decided by the player |
| Greater Portent | Wizard 14, Diviner | dice | in words: Portent's third die, decided by the player |
| Overchannel | Wizard 14, Evoker | dice | in words: maximum damage and its cost, said by the player |
| Rage | Barbarian 1 | bonus | rules/phb-2024 scale |
| Brutal Strike | Barbarian 9 | dice | rules/phb-2024 |
| Improved Brutal Strike | Barbarian 13 | bonus | rules/phb-2024 |
| Improved Brutal Strike | Barbarian 17 | dice, bonus | rules/phb-2024 |
| Frenzy | Barbarian 3, Path of the Berserker | dice, bonus | rules/phb-2024 |
| Vitality of the Tree | Barbarian 3, Path of the World Tree | dice, bonus | rules/phb-2024 |
| Divine Fury | Barbarian 3, Path of the Zealot | dice, bonus | rules/phb-2024 |
| Warrior of the Gods | Barbarian 3, Path of the Zealot | dice, bonus | rules/phb-2024 |
| Bardic Inspiration | Bard 1 | dice | rules/phb-2024 |
| Peerless Skill | Bard 14, College of Lore | dice | rules/phb-2024 |
| Combat Inspiration | Bard 3, College of Valor | bonus | rules/phb-2024 |
| Sear Undead | Cleric 5 | dice, bonus | rules/phb-2024 |
| Blessed Strikes | Cleric 7 | dice, bonus | rules/phb-2024 |
| Improved Blessed Strikes | Cleric 14 | dice, bonus | rules/phb-2024 |
| Radiance of the Dawn | Cleric 3, Light Domain | dice | rules/phb-2024 |
| Improved Warding Flare | Cleric 6, Light Domain | dice, bonus | rules/phb-2024 |
| Elemental Fury | Druid 7 | dice, bonus | rules/phb-2024 |
| Improved Elemental Fury | Druid 15 | dice, bonus | rules/phb-2024 |
| Land’s Aid | Druid 3, Circle of the Land | dice, save, bonus | rules/phb-2024 |
| Circle Forms | Druid 3, Circle of the Moon | bonus | class_rules |
| Lunar Form | Druid 14, Circle of the Moon | dice | rules/phb-2024 |
| Wrath of the Sea | Druid 3, Circle of the Sea | dice, save | rules/phb-2024 |
| Starry Form | Druid 3, Circle of the Stars | dice, bonus | rules/phb-2024 |
| Second Wind | Fighter 1 | dice, bonus | rules/phb-2024 |
| Tactical Mind | Fighter 2 | dice, bonus | rules/phb-2024 |
| Combat Superiority | Fighter 3, Battle Master | dice, save | rules/phb-2024 |
| Improved Critical | Fighter 3, Champion | dice | class_rules |
| Superior Critical | Fighter 15, Champion | dice | class_rules |
| Psionic Power | Fighter 3, Psi Warrior | bonus | rules/phb-2024 |
| Martial Arts | Monk 1 | dice | rules/phb-2024 scale |
| Uncanny Metabolism | Monk 2 | bonus | rules/phb-2024 |
| Deflect Attacks | Monk 3 | dice, save, bonus | rules/phb-2024 |
| Heightened Focus | Monk 10 | bonus | class_rules |
| Hand of Ultimate Mercy | Monk 17, Warrior of Mercy | dice | rules/phb-2024 |
| Elemental Epitome | Monk 17, Warrior of the Elements | bonus | rules/phb-2024 |
| Open Hand Technique | Monk 3, Warrior of the Open Hand | save | rules/phb-2024 |
| Wholeness of Body | Monk 6, Warrior of the Open Hand | bonus | rules/phb-2024 |
| Quivering Palm | Monk 17, Warrior of the Open Hand | dice | rules/phb-2024 |
| Aura of Protection | Paladin 6 | bonus | rules/phb-2024 |
| Radiant Strikes | Paladin 11 | dice | rules/phb-2024 |
| Sacred Weapon | Paladin 3, Oath of Devotion | bonus | rules/phb-2024 |
| Inspiring Smite | Paladin 3, Oath of Glory | dice, bonus | rules/phb-2024 |
| Tireless | Ranger 10 | dice, bonus | rules/phb-2024 |
| Dreadful Strikes | Ranger 3, Fey Wanderer | dice, bonus | rules/phb-2024 |
| Dread Ambusher | Ranger 3, Gloom Stalker | dice, bonus | rules/phb-2024 |
| Stalker’s Flurry | Ranger 11, Gloom Stalker | dice, save | rules/phb-2024 |
| Hunter’s Prey | Ranger 3, Hunter | dice, bonus | rules/phb-2024 |
| Superior Hunter’s Prey | Ranger 11, Hunter | bonus | rules/phb-2024 |
| Sneak Attack | Rogue 1 | dice, bonus | rules/phb-2024 |
| Cunning Strike | Rogue 5 | dice, save, bonus | rules/phb-2024 |
| Devious Strikes | Rogue 14 | dice, save | rules/phb-2024 |
| Assassinate | Rogue 3, Assassin | bonus | rules/phb-2024 |
| Envenom Weapons | Rogue 13, Assassin | dice | rules/phb-2024 |
| Death Strike | Rogue 17, Assassin | save | rules/phb-2024 |
| Psionic Power | Rogue 3, Soulknife | bonus | rules/phb-2024 |
| Soul Blades | Rogue 9, Soulknife | bonus | rules/phb-2024 |
| Rend Mind | Rogue 17, Soulknife | save | rules/phb-2024 |
| Warping Implosion | Sorcerer 18, Aberrant Sorcery | dice, save | rules/phb-2024 |
| Elemental Affinity | Sorcerer 6, Draconic Sorcery | bonus | rules/phb-2024 |
| Steps of the Fey | Warlock 3, Archfey Patron | dice, save | rules/phb-2024 |
| Misty Escape | Warlock 6, Archfey Patron | dice, save | rules/phb-2024 |
| Healing Light | Warlock 3, Celestial Patron | dice | rules/phb-2024 |
| Radiant Soul | Warlock 6, Celestial Patron | bonus | rules/phb-2024 |
| Searing Vengeance | Warlock 14, Celestial Patron | dice, bonus | rules/phb-2024 |
| Dark One’s Own Luck | Warlock 6, Fiend Patron | dice, bonus | rules/phb-2024 |
| Hurl Through Hell | Warlock 14, Fiend Patron | dice, save | rules/phb-2024 |
| Spell Breaker | Wizard 10, Abjurer | bonus | rules/phb-2024 |
| Empowered Evocation | Wizard 10, Evoker | bonus | rules/phb-2024 |

## Options a feature picks from

| Name | Where | Has | askdnd |
|---|---|---|---|
| Bait and Switch | Fighter 3, Battle Master | bonus | in words: a bonus to AC until your next turn, said |
| Empowered Spell | Sorcerer 2 | bonus | in words: rerolling damage dice: the roll card's Reroll |
| Seeking Spell | Sorcerer 2 | dice | in words: rerolling a missed spell attack: the roll card's Reroll |
| Investment of the Chain Master | Warlock 5 | save | in words: the familiar's own Battle has its numbers |
| Ambush | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Commanding Presence | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Disarming Attack | Fighter 3, Battle Master | save, bonus | rules/phb-2024 |
| Distracting Strike | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Feinting Attack | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Goading Attack | Fighter 3, Battle Master | save, bonus | rules/phb-2024 |
| Lunging Attack | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Maneuvering Attack | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Menacing Attack | Fighter 3, Battle Master | save, bonus | rules/phb-2024 |
| Parry | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Precision Attack | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Pushing Attack | Fighter 3, Battle Master | save, bonus | rules/phb-2024 |
| Rally | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Riposte | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Tactical Assessment | Fighter 3, Battle Master | bonus | rules/phb-2024 |
| Trip Attack | Fighter 3, Battle Master | save, bonus | rules/phb-2024 |
| Agonizing Blast | Warlock 2 | bonus | rules/phb-2024 |
| Eldritch Smite | Warlock 5 | dice | rules/phb-2024 |
| Lifedrinker | Warlock 9 | dice, bonus | rules/phb-2024 |

## Feats

| Name | Where | Has | askdnd |
|---|---|---|---|
| Healer | Origin Feats | bonus | **missing** |
| Inspiring Leader | General Feats | bonus | **missing** |
| Boon of Recovery | Epic Boon Feats | dice, bonus | **missing** |
| Actor | General Feats | save | save only: the target rolls |
| Alert | Origin Feats | bonus | the sheet: Initiative, in the sheet's Initiative |
| Crossbow Expert | General Feats | bonus | the sheet: in the sheet's attacks |
| Archery | Fighting Style Feats | bonus | the sheet: +2 on ranged attacks, in the sheet's attack bonus |
| Defense | Fighting Style Feats | bonus | the sheet: +1 AC, in the sheet's AC |
| Dueling | Fighting Style Feats | bonus | the sheet: +2 damage, in the sheet's weapon damage |
| Thrown Weapon Fighting | Fighting Style Feats | bonus | the sheet: +2 damage, in the sheet's weapon damage |
| Two-Weapon Fighting | Fighting Style Feats | bonus | the sheet: the ability modifier on the extra attack, in the sheet's weapon damage |
| Unarmed Fighting | Fighting Style Feats | dice | the sheet: the Unarmed Strike's damage, in the sheet's (its 1d4 to a grappled creature: Any dice) |
| Lucky | Origin Feats | dice | in words: played by the roll card's Luck points |
| Durable | General Feats | bonus | in words: Speedy Recovery is a Hit Point Die (Table rolls' Roll); Defy Death's Advantage is said |
| Poisoner | General Feats | dice, save | in words: a poison brewed with the kit: Any dice; Potent Poison ignores Resistance, said |
| Boon of Fortitude | Epic Boon Feats | bonus | in words: extra healing once a turn, said |
| Boon of Irresistible Offense | Epic Boon Feats | dice, bonus | in words: extra damage on a 20, said |
| Boon of Spell Recall | Epic Boon Feats | dice | in words: a d4 to keep a slot: Any dice |
| Tavern Brawler | Origin Feats | dice | rules/phb-2024 |
| Charger | General Feats | dice, bonus | rules/phb-2024 |
| Chef | General Feats | dice, bonus | rules/phb-2024 |
| Defensive Duelist | General Feats | bonus | class_rules |
| Dual Wielder | General Feats | bonus | class_rules |
| Great Weapon Master | General Feats | bonus | rules/phb-2024 |
| Heavy Armor Master | General Feats | bonus | rules/phb-2024 |
| Polearm Master | General Feats | dice | class_rules |
| Shield Master | General Feats | save | rules/phb-2024 |
| Telekinetic | General Feats | save | rules/phb-2024 |
| Interception | Fighting Style Feats | dice, bonus | rules/phb-2024 |
| Boon of Energy Resistance | Epic Boon Feats | dice, save | rules/phb-2024 |
| Boon of Fate | Epic Boon Feats | dice | rules/phb-2024 |

## Species traits

| Name | Where | Has | askdnd |
|---|---|---|---|
| Necrotic Shroud | Aasimar | save | save only: the target rolls |
| Healing Hands | Aasimar | dice, bonus | rules/phb-2024 |
| Breath Weapon | Dragonborn | dice, save | rules/phb-2024 |
| Fire’s Burn | Goliath | dice | rules/phb-2024 |
| Frost’s Chill | Goliath | dice | rules/phb-2024 |
| Stone’s Endurance | Goliath | dice, bonus | rules/phb-2024 |
| Storm’s Thunder | Goliath | dice | rules/phb-2024 |
| Luck | Halfling | dice | rules/phb-2024 |
| Adrenaline Rush | Orc | bonus | rules/phb-2024 |

## Magic items (DMG)

| Name | Where | Has | askdnd |
|---|---|---|---|
| Ammunition, +1, +2, or +3 |  | bonus | **missing** |
| Ammunition of Slaying |  | dice, save, bonus | **missing** |
| Amulet of the Planes |  | dice, save | **missing** |
| Apparatus of Kwalish |  | dice, save | **missing** |
| Armor, +1, +2, or +3 |  | bonus | **missing** |
| Armor of Resistance |  | dice | **missing** |
| Arrow-Catching Shield |  | bonus | **missing** |
| Axe of the Dwarvish Lords |  | dice, bonus | **missing** |
| Bag of Beans |  | dice, save | **missing** |
| Bag of Tricks |  | dice | **missing** |
| Berserker Axe |  | save, bonus | **missing** |
| Blackrazor |  | dice, bonus | **missing** |
| Book of Exalted Deeds |  | dice | **missing** |
| Book of Vile Darkness |  | dice, save | **missing** |
| Bracers of Archery |  | bonus | **missing** |
| Bracers of Defense |  | bonus | **missing** |
| Candle of Invocation |  | dice | **missing** |
| Carpet of Flying |  | dice | **missing** |
| Cloak of Protection |  | bonus | **missing** |
| Clockwork Amulet |  | dice | **missing** |
| Cube of Force |  | dice, save | **missing** |
| Cube of Summoning |  | dice, save | **missing** |
| Daern’s Instant Fortress |  | bonus | **missing** |
| Dancing Sword |  | bonus | **missing** |
| Decanter of Endless Water |  | dice, save | **missing** |
| Deck of Illusions |  | dice, save | **missing** |
| Deck of Many Things |  | dice | **missing** |
| Defender |  | bonus | **missing** |
| Demon Armor |  | dice, bonus | **missing** |
| Demonomicon of Iggwilv |  | dice, save | **missing** |
| Dragon Scale Mail |  | bonus | **missing** |
| Dust of Disappearance |  | dice | **missing** |
| Dust of Dryness |  | dice, save | **missing** |
| Dwarven Plate |  | bonus | **missing** |
| Efreeti Bottle |  | dice | **missing** |
| Efreeti Chain |  | bonus | **missing** |
| Elven Chain |  | bonus | **missing** |
| Energy Bow |  | save, bonus | **missing** |
| Enspelled Armor |  | dice, save | **missing** |
| Enspelled Staff |  | dice, save | **missing** |
| Enspelled Weapon |  | dice, save | **missing** |
| Eye and Hand of Vecna |  | dice, save, bonus | **missing** |
| Glamoured Studded Leather |  | bonus | **missing** |
| Hat of Many Spells |  | dice, save | **missing** |
| Helm of Brilliance |  | dice, save | **missing** |
| Heward’s Handy Spice Pouch |  | dice | **missing** |
| Horn of Silent Alarm |  | dice | **missing** |
| Horn of Valhalla |  | dice | **missing** |
| Instrument of the Bards |  | dice, save | **missing** |
| Iron Flask |  | dice, save | **missing** |
| Luck Blade |  | bonus | **missing** |
| Lute of Thunderous Thumping |  | dice | **missing** |
| Mace of Smiting |  | bonus | **missing** |
| Manual of Golems |  | dice | **missing** |
| Mariner’s Armor |  | dice, bonus | **missing** |
| Medallion of Thoughts |  | dice, save | **missing** |
| Moonblade |  | dice, save, bonus | **missing** |
| Nine Lives Stealer |  | dice, save, bonus | **missing** |
| Nolzur’s Marvelous Pigments |  | dice | **missing** |
| Orb of Dragonkind |  | dice, save | **missing** |
| Periapt of Health |  | dice, bonus | **missing** |
| Periapt of Wound Closure |  | bonus | **missing** |
| Potion of Diminution |  | dice | **missing** |
| Potions of Healing |  | dice, bonus | **missing** |
| Potion of Longevity |  | dice | **missing** |
| Potion of Pugilism |  | dice | **missing** |
| Potion of Resistance |  | dice | **missing** |
| Potion of Vitality |  | bonus | **missing** |
| Quaal’s Feather Token |  | dice | **missing** |
| Quarterstaff of the Acrobat |  | bonus | **missing** |
| Ring of Elemental Command |  | dice, save | **missing** |
| Ring of Protection |  | bonus | **missing** |
| Ring of Regeneration |  | dice, bonus | **missing** |
| Ring of Resistance |  | dice | **missing** |
| Ring of Shooting Stars |  | dice, save | **missing** |
| Ring of Spell Storing |  | dice | **missing** |
| Ring of the Ram |  | dice | **missing** |
| Ring of Warmth |  | dice, bonus | **missing** |
| Rival Coin |  | dice, save | **missing** |
| Robe of Stars |  | dice, bonus | **missing** |
| Robe of Useful Items |  | dice | **missing** |
| Rod of Absorption |  | dice | **missing** |
| Rod of Alertness |  | bonus | **missing** |
| Rod of Lordly Might |  | dice, save, bonus | **missing** |
| Rod of Resurrection |  | dice | **missing** |
| Rod of Security |  | bonus | **missing** |
| Scarab of Protection |  | bonus | **missing** |
| Scimitar of Speed |  | bonus | **missing** |
| Scroll of Protection |  | dice, save | **missing** |
| Scroll of Titan Summoning |  | dice | **missing** |
| Shield, +1, +2, or +3 |  | bonus | **missing** |
| Shield of the Cavalier |  | dice, bonus | **missing** |
| Sovereign Glue |  | dice | **missing** |
| Sphere of Annihilation |  | dice, save | **missing** |
| Staff of Birdcalls |  | dice | **missing** |
| Staff of Charming |  | dice | **missing** |
| Staff of Flowers |  | dice | **missing** |
| Staff of Power |  | dice, save, bonus | **missing** |
| Staff of Swarming Insects |  | dice | **missing** |
| Staff of the Adder |  | dice, bonus | **missing** |
| Staff of the Magi |  | dice, save, bonus | **missing** |
| Staff of the Woodlands |  | dice, bonus | **missing** |
| Staff of Withering |  | dice, save | **missing** |
| Stone of Good Luck (Luckstone) |  | bonus | **missing** |
| Sword of Answering |  | bonus | **missing** |
| Sword of Kas |  | dice, save, bonus | **missing** |
| Sword of Life Stealing |  | dice, bonus | **missing** |
| Sword of Sharpness |  | dice | **missing** |
| Sword of Vengeance |  | save, bonus | **missing** |
| Talisman of Pure Good |  | dice, save | **missing** |
| Talisman of Ultimate Evil |  | dice, save | **missing** |
| Tentacle Rod |  | dice, save | **missing** |
| Universal Solvent |  | dice | **missing** |
| Vorpal Sword |  | dice, bonus | **missing** |
| Wand of Binding |  | dice, save | **missing** |
| Wand of Conducting |  | dice | **missing** |
| Wand of Enemy Detection |  | dice | **missing** |
| Wand of Fear |  | dice, save | **missing** |
| Wand of Paralysis |  | dice, save | **missing** |
| Wand of Polymorph |  | dice, save | **missing** |
| Wand of Pyrotechnics |  | dice | **missing** |
| Wand of Web |  | dice, save | **missing** |
| Wand of Wonder |  | dice, save | **missing** |
| Weapon, +1, +2, or +3 |  | bonus | **missing** |
| Well of Many Worlds |  | dice | **missing** |
| Winged Boots |  | dice | **missing** |
| Wings of Flying |  | dice | **missing** |
| Wraps of Unarmed Power |  | bonus | **missing** |
| Staff of Thunder and Lightning |  | dice, save, bonus | **partly**: missing Lightning Strike |
| Wand of Orcus |  | dice, save, bonus | **partly**: missing Magic Weapon, Spells |
| Whelm |  | dice, save, bonus | **partly**: missing Shock Wave |
| Bag of Devouring |  | save | save only: the target rolls |
| Cloak of Arachnida |  | save | save only: the target rolls |
| Crystal Ball |  | save | save only: the target rolls |
| Dark Shard Amulet |  | save | save only: the target rolls |
| Dimensional Shackles |  | save | save only: the target rolls |
| Eyes of Charming |  | save | save only: the target rolls |
| Gem of Brightness |  | save | save only: the target rolls |
| Helm of Telepathy |  | save | save only: the target rolls |
| Immovable Rod |  | save | save only: the target rolls |
| Iron Bands of Bilarro |  | save | save only: the target rolls |
| Mace of Terror |  | save | save only: the target rolls |
| Mirror of Life Trapping |  | save | save only: the target rolls |
| Pipes of Haunting |  | save | save only: the target rolls |
| Pipes of the Sewers |  | save | save only: the target rolls |
| Portable Hole |  | save | save only: the target rolls |
| Potion of Animal Friendship |  | save | save only: the target rolls |
| Potion of Mind Reading |  | save | save only: the target rolls |
| Ring of Animal Influence |  | save | save only: the target rolls |
| Ring of Spell Turning |  | save | save only: the target rolls |
| Ring of X-ray Vision |  | save | save only: the target rolls |
| Robe of Eyes |  | save | save only: the target rolls |
| Robe of Scintillating Colors |  | save | save only: the target rolls |
| Rod of Rulership |  | save | save only: the target rolls |
| Rod of the Pact Keeper |  | save | save only: the target rolls |
| Rope of Entanglement |  | save | save only: the target rolls |
| Spell Scroll |  | save | save only: the target rolls |
| Trident of Fish Command |  | save | save only: the target rolls |
| Walloping Ammunition |  | save | save only: the target rolls |
| Wind Fan |  | save | save only: the target rolls |
| Bead of Force |  | dice, save | rules/srd-5.2.1 |
| Dagger of Venom |  | dice, save, bonus | rules/srd-5.2.1 |
| Dragon Slayer |  | dice, bonus | rules/srd-5.2.1 |
| Dust of Sneezing and Choking |  | save | rules/dmg-2024 |
| Dwarven Thrower |  | dice, bonus | rules/srd-5.2.1 |
| Executioner’s Axe |  | dice, bonus | rules/dmg-2024 |
| Flame Tongue |  | dice | rules/srd-5.2.1 |
| Frost Brand |  | dice | rules/srd-5.2.1 |
| Giant Slayer |  | dice, save, bonus | rules/srd-5.2.1 |
| Gloves of Missile Snaring |  | dice, bonus | rules/srd-5.2.1 |
| Hammer of Thunderbolts |  | dice, save, bonus | rules/dmg-2024 |
| Hat of Wizardry |  | save | rules/dmg-2024 |
| Holy Avenger |  | dice, bonus | rules/srd-5.2.1 |
| Horn of Blasting |  | dice, save | rules/srd-5.2.1 |
| Javelin of Lightning |  | dice, save | rules/srd-5.2.1 |
| Keoghtom’s Ointment |  | dice, bonus | rules/dmg-2024 |
| Mace of Disruption |  | dice, save | rules/srd-5.2.1 |
| Necklace of Fireballs |  | dice, save | rules/srd-5.2.1 |
| Necklace of Prayer Beads |  | dice | rules/dmg-2024 |
| Oathbow |  | dice | rules/srd-5.2.1 |
| Potion of Fire Breath |  | dice, save | rules/dmg-2024 |
| Potion of Poison |  | dice, save | rules/srd-5.2.1 |
| Staff of Fire |  | dice | rules/srd-5.2.1 |
| Staff of Frost |  | dice | rules/srd-5.2.1 |
| Staff of Healing |  | dice | rules/srd-5.2.1 |
| Staff of Striking |  | dice, bonus | rules/srd-5.2.1 |
| Sun Blade |  | dice, bonus | rules/srd-5.2.1 |
| Sword of Wounding |  | dice, save, bonus | rules/srd-5.2.1 |
| Thunderous Greatclub |  | dice, save | rules/dmg-2024 |
| Vicious Weapon |  | dice, bonus | rules/srd-5.2.1 |
| Wand of Fireballs |  | dice, save | rules/srd-5.2.1 |
| Wand of Lightning Bolts |  | dice, save | rules/srd-5.2.1 |
| Wand of Magic Missiles |  | dice | rules/srd-5.2.1 |
| Wave |  | dice, save, bonus | rules/phb-2024 |
