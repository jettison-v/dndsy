"""Does Battle put each thing in the column its own rules text says? (feedback 15, Nov 5: audit Action, Bonus Action,
Reaction and On a hit against the reference text.)

    uv run --env-file .env python scripts/battle_audit.py              # every character at a table, from the local copy of beta
    uv run --env-file .env python scripts/battle_audit.py Cole Vi      # some of them

For each feature, action and item use on a character's sheet, the cost its own text states (D&D Beyond's copy of the
book's words: "As a Bonus Action…", "you can take a Reaction…", "take the Magic action…") is compared with where
Battle puts it (app/character_views.py options: D&D Beyond's activation, askdnd's item rules, corrections). It lists:

- **moved**: Battle's column differs from what the text says first;
- **missing**: the text gives it an action, Bonus Action or Reaction, but it's in no column and not "On a hit";
- **rider?**: the text adds something when you hit, and "On a hit" doesn't list it.

A finding is a lead, not a verdict: a text can mention another feature's Bonus Action, and the DM rules. Prints names
and short phrases only (never the book's text).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COVERED = {"Extra Attack", "Monk’s Focus", "Monk's Focus", "Martial Arts", "Channel Divinity", "Artificer Infusions", "Eldritch Cannon", "Gnomish Lineage",
           "Rock Gnome", "Metamagic"}  # (the attack count's tag; menus whose options Battle lists by their own names)
# Features Battle lists under another name (checked by hand, Nov 5)
LISTED_AS = {"Wild Companion": "Find Familiar", "Pact of the Chain": "Find Familiar", "War Caster": "Reactive Spell",
             "Telekinetic": "Telekinetic Shove", "Lay On Hands": "Lay On Hands: Heal", "Lay On Hands: Healing Pool": "Lay On Hands: Heal",
             "Explosive Cannon": "Detonate Eldritch Cannon"}
# Options whose text is the whole feature's, so it states another option's cost first (the Eldritch Cannon's text says
# creating it takes an action; activating it is the Bonus Action D&D Beyond says). D&D Beyond's own label stands
SHARED_TEXT = ("Eldritch Cannon:", "Create Tiny Clockwork Device", "Tiny Clockwork Device:")
HIT = r"\bwhen(?:ever)? you hit\b|\bhit a (?:creature|target) with an attack\b|\bon a hit\b"


def stated(text: str) -> str | None:
    from app.character_views import stated_cost  # (the app's own reading, so the two never drift)

    return stated_cost(text)


def audit(sheet: dict) -> list[tuple[str, str, str, str]]:
    """[(finding, name, Battle's column, what the text says)]."""
    from app import character_views as views
    from app import class_rules

    opts = views.options(sheet, set())

    def placed(name: str) -> set[str]:
        """Battle's columns for a feature, by its name or an option named after it ("Lay On Hands: Heal", "Deflect
        Attack" for Deflect Attacks): an Unarmed Strike is in two."""
        n = name.split(" (")[0].lower()
        stem = n.rstrip("s")
        return {o["cost"] for o in opts for m in [o["name"].split(" (")[0].lower()]
                if m.rstrip("s") == stem or m.startswith((n + ":", stem + ":")) or n.startswith(m + ":")}
    riders = {r["name"] for r in class_rules.turn(sheet)["riders"]}
    out, seen = [], set()
    for x in [*(sheet.get("actions") or []), *(sheet.get("features") or [])]:
        name = x["name"]
        if name in seen or name.split(" (")[0] in COVERED or class_rules.is_mastery_action(name):
            continue
        seen.add(name)
        text = x.get("text") or x.get("summary") or ""
        says = stated(text)
        cols = placed(LISTED_AS.get(name, name))
        col = ", ".join(sorted(cols))
        if cols and says and says not in cols and cols != {"Other"} and not name.startswith(SHARED_TEXT):
            out.append(("moved", name, col, says))
        elif cols == {"Other"} and says:  # (D&D Beyond says "Special": Battle shows it nowhere)
            out.append(("missing", name, "Other", says))
        elif not col and says and name not in riders and x.get("activation") not in ("Hour", "Minute", "Special"):
            out.append(("missing", name, "none", says))
        if re.search(HIT, text, re.I) and name not in riders and not col:
            out.append(("rider?", name, "none", "on a hit"))
    return out


def main() -> None:
    from sqlalchemy import select

    from app import characters as chars
    from app.db import SessionLocal
    from app.models import Campaign, CampaignCharacter, Character

    want = set(sys.argv[1:])
    with SessionLocal() as db:
        rows = db.execute(select(Character, Campaign).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                          .join(Campaign, Campaign.id == CampaignCharacter.campaign_id)
                          .where(CampaignCharacter.left_on.is_(None), Character.copy_of_id.is_(None)).order_by(Campaign.id, Character.name)).all()
        for ch, camp in rows:
            if want and ch.name.split()[0] not in want:
                continue
            sheet = chars.character_summary(ch)
            if not sheet:
                continue
            classes = ", ".join(f"{c.get('name')} {c.get('level')}" for c in sheet.get("classes") or [])
            found = audit(sheet)
            print(f"\n== {ch.name} ({camp.name}; {classes}): {len(found) or 'nothing'} to look at")
            for kind, name, col, says in found:
                print(f"  {kind:8} {name:42} Battle: {col:13} text: {says}")


if __name__ == "__main__":
    main()
