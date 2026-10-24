# Rules references

Where askdnd's rules knowledge comes from, and how we use it. **This repo is public**, so it holds only our own short
summaries and openly licensed data, never the books' text.

| Source | Access | Used for |
|---|---|---|
| Player's Handbook (2024) on D&D Beyond | Brett's D&D Beyond account (signed in to the in-app browser) | Druid class and Circles (`druid.md`), Rules Glossary (checks `app/rules_terms.py`), weapon properties, languages |
| Monster Manual (2024) on D&D Beyond | Same | Checking the Beast list; it has 91 Beasts, the SRD has 90 of them |
| Dungeon Master's Guide (2024) on D&D Beyond | Same | Magic item rules beyond the PHB (attunement prerequisites, cursed items); later, rulings guidance for rules answers |
| System Reference Document 5.2.1 (CC-BY-4.0), the official PDF | Public (https://www.dndbeyond.com/srd) | `app/data/srd/`: monsters, spells, magic items and the Rules Glossary as data (below), read by `scripts/srd_import.py`; Wild Shape's Beasts and the roll recipes (`scripts/roll_audit.py`, report in `rolls-audit.md`) are built on it |
| Open5e's conversion of the SRD | Public API | Only a check: `scripts/srd_import.py --compare` lists where its numbers differ from ours |
| D&D Beyond character data | Public character sheets | Each character's features, spells and known forms, with full feature text |

## Rules content as data

`app/rules_data.py` reads the SRD files and a campaign's own entries (`campaign_content` in the database: the DM's
creations, or entries copied from a book the DM owns) as one: `catalog(kind, db, campaign_id)` lists them,
`find(kind, name, db, campaign_id)` finds one, `save(...)` adds one to a campaign (checked first). A campaign's entry
with an SRD key replaces that entry for the campaign. Every entry says where it's from in `source` ("SRD 5.2.1",
"Homebrew", a book's title). Kinds and their fields (the schemas in `rules_data.py` are the full list):

- **monster**: `key` ("adult-red-dragon"), `name`, `size` ("Medium or Small"), `type` (one of the 14 creature types),
  `tags` (["Chromatic"]), `swarm_of` ("Tiny" for a swarm of Tiny Beasts), `alignment`, `ac`, `initiative`, `hp`,
  `hit_dice`, `speed` ({"walk": 40, "fly": 80}), `hover`, `speed_note` ("40 ft. (bear form only)"), `abilities` and
  `saves` (all six, as the stat block prints them), `skills` ({"Perception": 13}), `resistances`, `vulnerabilities`,
  `immunities`, `condition_immunities`, `gear`, `senses` ({"darkvision": 120}), `senses_note`, `passive_perception`,
  `languages`, `cr` (0.25), `cr_label` ("1/4"), `xp`, `xp_lair`, `pb`, then `traits`, `actions`, `bonus_actions`,
  `reactions` and `legendary_actions` as [{"name", "text"}] (a use limit is part of the name, as printed: "Fire Breath
  (Recharge 5–6)"), and `legendary_uses` (the Legendary Actions intro).
- **spell**: `key`, `name`, `level` (0 for a cantrip), `school`, `classes`, `casting_time`, `ritual`, `range`,
  `components` (["V", "S", "M"]), `material`, `duration`, `concentration`, `text`, `higher_levels`, `cantrip_upgrade`,
  and `creatures` (stat blocks the spell makes, whose numbers come from the caster, so their header stays as printed).
- **magic_item**: `key`, `name`, `category` ("Armor", "Wondrous Item"…), `base` ("Plate Armor", "Any Sword"), `rarity`
  (as printed, e.g. "Rare (+1), Very Rare (+2), or Legendary (+3)"), `attunement`, `attunement_by` ("by a Wizard"),
  `text`, `monsters` (keys of monsters it makes) and `creatures` (like a spell's).
- **glossary** (the SRD only): `key`, `name`, `tag` ("Condition", "Action", "Area of Effect", "Hazard", "Attitude"
  or none), `text`. `rules_data.conditions()` is its 15 conditions; `app/conditions.py` and `app/rules_terms.py` take
  the list from there and add askdnd's own summaries and roll effects.

`text` fields are a small Markdown: paragraphs apart by a blank line, a run-in heading in bold ("**Audible Alarm.**
The alarm…"), bullets as "- ", tables as pipe tables with a bold title above. Pictures of SRD monsters are links to
D&D Beyond's art (`app/data/monster_pictures.json`, `scripts/monster_pictures.py`), kept apart from the SRD's text.

## Offline copy (Brett's Mac only)

So work can continue if the D&D Beyond sign-in in the in-app browser stops working, the three books are saved as
Markdown (one file per chapter) plus the Monster Manual's stat blocks as data in `private/books/`, which is
git-ignored. They never go to GitHub, Railway or the database. To refresh them: run
`uv run python scripts/book_receiver.py`, then from a signed-in D&D Beyond tab in the in-app browser send pages to
`http://127.0.0.1:8799/save?z=…` (gzipped JSON in the address, since the browser only lets a website reach this Mac by
opening an address). See the script's docstring.

## Checks done

- 2026-10-18: all 90 rule terms in `app/rules_terms.py` compared with the PHB Rules Glossary, weapon properties and the
  language tables. Fixed: Grappled (escape, dragging), Prone (standing at Speed 0), Dash (special speeds), Hide (sound
  louder than a whisper, DC to find you), Influence (no roll if willing or unwilling; DC 15 or the creature's Intelligence),
  Unarmed Strike (target chooses the save; free hand), Heroic Inspiration (pass on a second one), Emanation, Short Rest
  and Long Rest (1 HP to start, interruptions, 16 hours between Long Rests), Shape-Shifting (the general rule, not Wild
  Shape's), and language origins.
- 2026-10-18: Attunement checked against the PHB (Equipment › Magic Items) and the DMG (Treasure › Magic Items): added
  touching the item, nonmagical benefits only until attuned, no two copies, prerequisites, and ending it yourself.
- 2026-10-18: SRD Beasts compared with the Monster Manual: AC, HP, CR and attacks match. Giant Squid is MM-only;
  Giant Fly is SRD-only; the SRD's Swarm of Insects has a Fly Speed D&D Beyond's MM entry doesn't list.
- 2026-10-19: every class and subclass in the PHB, plus battle feats and weapon masteries, checked for what they change
  about a turn; the Battle page now follows `app/class_rules.py`. See `battle-actions.md`.
- 2026-10-21: roll audit (`scripts/roll_audit.py`, `rolls-audit.md`). Every SRD 5.2 spell with dice (127), the Player's
  Handbook spells the table uses, common items and all 88 Beast actions with dice: every dice expression in the text is
  in the recipe or marked as not a roll you make, 48 recipes written by hand with the reason, and every SRD spell's dice
  compared with the offline 2024 PHB (124 the same; Open5e's copy lacked dice for Conjure Celestial and the upcast line
  for Dissonant Whispers, fixed by hand). Found and fixed: Beast charge damage (Rhinoceros, Boar, Elk, Giant Goat,
  Warhorse, Giant Boar, Triceratops) was added to every hit; D&D Beyond's data has 2014 numbers for some of the table's
  spells (Cure Wounds 1d8, Inflict Wounds as a 3d10 attack), so askdnd uses the audited 2024 recipe; Open5e's structured
  upcasting is wrong for Ice Knife.
- 2026-10-24: SRD 5.2.1 read from the official PDF into `app/data/srd/` (VTT 0.6) and every number compared with
  Open5e's conversion (`--compare`). Each difference was checked against the PDF, which is what we keep: the PDF has
  XP 10 for CR 0, the Mastiff's Wisdom save +3, the Swarm of Insects' "Climb or Fly 20 ft. (GM's choice)" and the
  werecreatures' animal-form speeds; Open5e lists Tiny creatures and "Medium or Small" ones as Small and has the
  Octopus's Constitution wrong. One PDF misprint is corrected (the Young White Dragon's Intelligence save). The roll
  recipes come out the same from the official text, which also has the dice Open5e's copy lacked (Conjure Celestial,
  Dissonant Whispers' upcasting).
