# System Reference Document 5.2.1

This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC,
available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0
International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

The same statement is on Help › About (`app/rules_data.py` `ATTRIBUTION`). The license asks for exactly this wording
and no other attribution to Wizards of the Coast, so other places say "SRD 5.2.1" and point to Help › About.

## What's here

| File | What | How many |
|---|---|---|
| `monsters.json` | Every stat block in Monsters and Animals, plus the Giant Fly from the Figurine of Wondrous Power | 331 |
| `spells.json` | Every spell, with any creature it makes | 339 |
| `magic_items.json` | Every magic item, as the book prints it (one "Armor, +1, +2, or +3", not one per armor) | 258 |
| `rules_glossary.json` | The Rules Glossary; the 15 conditions are its `[Condition]` entries | 155 |

Each file is `{"source": {...}, "<kind>": [...]}`; `source` names the PDF (URL and SHA-256) it was read from. The shape
of each kind is in `docs/rules/README.md` ("Rules content as data") and checked by `app/rules_data.py` on load.

## How it's made

`uv run scripts/srd_import.py` downloads the official PDF (to `private/srd/`, not committed) and reads it, so these
files are the book's own text, not someone's conversion. Don't edit them by hand: change the script and run it again.
Text is as printed, except apostrophes as typed (’ → ') and one misprint the stat block itself shows to be wrong (the
script's `CORRECTIONS`, each with its reason). `uv run scripts/srd_import.py --compare` checks every number against
Open5e's independent conversion; on 2026-10-24 the two agreed except where the 5.2.1 corrections changed something or
Open5e misread the book.

Nothing from the purchased books goes here: the repo is public. A DM's own monsters, spells and items, or ones copied
from a book they own, live in the database (`campaign_content`), per campaign.
