# Rules references

Where askdnd's rules knowledge comes from, and how we use it. **This repo is public**, so it holds only our own short
summaries and openly licensed data, never the books' text.

| Source | Access | Used for |
|---|---|---|
| Player's Handbook (2024) on D&D Beyond | Brett's D&D Beyond account (signed in to the in-app browser) | Druid class and Circles (`druid.md`), Rules Glossary (checks `app/rules_terms.py`), weapon properties, languages |
| Monster Manual (2024) on D&D Beyond | Same | Checking the Beast list; it has 91 Beasts, the SRD has 90 of them |
| System Reference Document 5.2 (CC-BY-4.0) via Open5e | Public | `app/data/beasts_2024.json` (Wild Shape stat blocks), stored in the repo with credit |
| D&D Beyond character data | Public character sheets | Each character's features, spells and known forms, with full feature text |

## Checks done

- 2026-10-18: all 90 rule terms in `app/rules_terms.py` compared with the PHB Rules Glossary, weapon properties and the
  language tables. Fixed: Grappled (escape, dragging), Prone (standing at Speed 0), Dash (special speeds), Hide (sound
  louder than a whisper, DC to find you), Influence (no roll if willing or unwilling; DC 15 or the creature's Intelligence),
  Unarmed Strike (target chooses the save; free hand), Heroic Inspiration (pass on a second one), Emanation, Short Rest
  and Long Rest (1 HP to start, interruptions, 16 hours between Long Rests), Shape-Shifting (the general rule, not Wild
  Shape's), and language origins.
- 2026-10-18: SRD Beasts compared with the Monster Manual: AC, HP, CR and attacks match. Giant Squid is MM-only;
  Giant Fly is SRD-only; the SRD's Swarm of Insects has a Fly Speed D&D Beyond's MM entry doesn't list.
