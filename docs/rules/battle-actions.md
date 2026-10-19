# Battle page: what each class changes about a turn (audit, 2026-10-19)

The Battle page lists what a character can do on a turn, from D&D Beyond's action list. That list covers things you
*activate* (Rage, Flurry of Blows, Second Wind) but not how your turn works. So `app/class_rules.py` adds, from the
2024 Player's Handbook:

- **Attacks per Attack action** (Extra Attack and its upgrades). Shown in the Action heading ("the Attack action makes
  2 attacks") and on each weapon. Extra Attack from two classes doesn't stack.
- **On a hit**: extras you add when an attack hits (Sneak Attack, Stunning Strike, Divine Strike, Savage Attacker…),
  with what they cost. They're riders, not actions, so they sit under the columns.
- **Column notes**: things that change a column (Action Surge, War Magic, Paladin's Smite, Heightened Focus, War Caster).
- **Missing options**: options the PHB gives that D&D Beyond may not list (Cunning Action, Steady Aim, War Priest,
  Battle Magic…), plus two for everyone: the **Opportunity Attack** and the **Light weapon extra attack**.
- **Not actions**: D&D Beyond entries that aren't options on a turn are left out of the columns: weapon masteries
  ("Vex (Dart)": shown on the weapon instead), riders (Stunning Strike), resource pools (Sorcery Points, Lay On Hands'
  Healing Pool, the bare Channel Divinity pool) and Circle Forms (part of Wild Shape).
- **Weapon masteries** only show on weapons the character has mastered (D&D Beyond lists every weapon's mastery,
  mastered or not).

Rules apply by class, subclass and level, so a new character gets them automatically. Rules that depend on a choice
(Elemental Fury, Blessed Strikes, Hunter's Prey, invocations) apply only when the sheet shows that choice. If a sheet
lists "Extra Attack" from a class or book not in the table, it still counts. `tests/test_class_rules.py` checks the
party's real sheets and made-up characters for the other classes.

## The table's characters

| Character | Before | Now |
|---|---|---|
| Cole (Druid 6 Moon / Monk 2) | "Wild Shape: Circle Forms" listed as a separate bonus action | Circle Forms folded into Wild Shape (note); Opportunity Attack added; War Caster note on Reaction. One attack per Attack action is right: Monks get Extra Attack at Monk level 5 |
| Trah (Wizard 7 Evoker / Fighter 1) | "Vex (Dart)", "Vex (Shortsword)", "Nick (Dagger)" listed as actions | Masteries shown on the weapons; Potent Cantrip note; Opportunity Attack. Action Surge arrives at Fighter 2 |
| No Name (Monk 6 Shadow / Warlock 2) | One attack implied; Stunning Strike listed as an action; masteries shown on weapons although Monks don't get Weapon Mastery | Attack action makes 2 attacks (Extra Attack); Stunning Strike (DC 14, 1 Focus Point), Empowered Strikes and Savage Attacker under On a hit; unmastered masteries removed. Thirsting Blade needs Warlock 5 |
| Big C (Paladin 6 Conquest / Sorcerer 2 Divine Soul) | One attack implied; Sorcery Points, the Channel Divinity pool and the Lay On Hands pool listed as actions; Topple shown on the maul (not mastered) | Attack action makes 2 attacks; Divine Smite timing note; Savage Attacker under On a hit; masteries only on Longsword (Sap) and Javelin (Slow). Oath of Conquest and Divine Soul are older-book subclasses: their D&D Beyond actions are shown as listed |

## Every class (2024 PHB)

| Class | What the Battle page adds |
|---|---|
| Barbarian | Rage Damage on every Strength hit while raging; Reckless Attack; Extra Attack (5); Brutal Strike (9, 13, 17). Berserker: Frenzy, Retaliation. Zealot: Divine Fury. World Tree: Battering Roots reach |
| Bard | Valor: Extra Attack (6) with a cantrip in place of one attack; Battle Magic (14). Dance: Agile Strikes. (Bardic Inspiration, Cutting Words etc. come from D&D Beyond's list) |
| Cleric | Divine Strike when chosen for Blessed Strikes (7; 2d8 at 14). War: War Priest bonus attack, Guided Strike |
| Druid | Primal Strike when chosen for Elemental Fury (7; 2d8 at 15). Moon: Circle Forms are part of Wild Shape. (Forms themselves: see the Wild Shape window) |
| Fighter | Action Surge (2); Extra Attack 5 / 11 / 20 (2, 3, 4 attacks); Studied Attacks (13). Champion: critical range. Battle Master: maneuvers. Eldritch Knight: War Magic, Eldritch Strike. Psi Warrior: Psionic Strike |
| Monk | Extra Attack (5); Stunning Strike (5) as a rider; Empowered Strikes (6); Flurry of three strikes (10). Mercy: Hand of Harm. Open Hand: Open Hand Technique, Quivering Palm. Elements: elemental Empowered Strikes (17) |
| Paladin | Divine Smite timing (Paladin's Smite, 2); Extra Attack (5); Radiant Strikes (11). Devotion: Sacred Weapon. Vengeance: Vow of Enmity, Soul of Vengeance. Glory: Unerring Strike |
| Ranger | Extra Attack (5); Precise Hunter (17). Beast Master: trade an attack for Beast's Strike, command as a Bonus Action. Fey Wanderer and Gloom Stalker: Dreadful Strikes. Hunter: Colossus Slayer or Horde Breaker as chosen |
| Rogue | Sneak Attack (dice by level); Cunning Action (2); Steady Aim (3); Cunning Strike (5, 11, 14). Thief: Fast Hands. Soulknife: second Psychic Blade. Assassin: Assassinate |
| Sorcerer | Metamagic note. (Innate Sorcery and Font of Magic come from D&D Beyond's list) |
| Warlock | Thirsting Blade / Devouring Blade (pact weapon only), Eldritch Smite and Lifedrinker when taken. Fiend: Hurl Through Hell |
| Wizard | Evoker: Potent Cantrip, Empowered Evocation notes. (Wizards act mostly through spells, which come from D&D Beyond) |
| Feats | Savage Attacker, Great Weapon Master, Polearm Master, Sentinel, War Caster, Charger, Shield Master, Tavern Brawler, Grappler, Mage Slayer, Defensive Duelist, Dual Wielder |

Not covered on purpose: features that only change numbers D&D Beyond already shows (Unarmored Defense, Fighting Style
bonuses, Agonizing Blast), long-term features that aren't combat turns, and older-book subclasses (their D&D Beyond
actions are shown as listed). The Wild Shape window has its own rules (`app/wild_shape.py`).
