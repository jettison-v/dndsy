"""The roll plan: what the roll card does with each thing on Battle (Brett chose the Roll Card Prototype, Nov 9;
docs/mockups/roll-workflow/round-2.html). One plan per option (app/character_views.py `options`), built from what askdnd
already knows, never guessed:

    {"steps": ["choose", "attack", "damage", "apply"],     # only the steps this action has, in order
     "choice": {"ask": "Which Unarmed Strike?", "options": [...]} or None,
     "attack": {"bonus": 7} or None,                        # a d20 with this bonus
     "save": {"ability": "Dex", "dc": 15, "success": "half" | "none" | ""} or None,   # the target rolls
     "damage": [{"dice": "1d8", "flat": 4, "type": "bludgeoning", "from": "Unarmed Strike"}],
     "heal": [...],                                         # the same shape, healing or Temporary Hit Points ("temp")
     "riders": [{"name": "Stunning Strike", "when": "hit", ...}],
     "spends": [...],                                       # what using it costs (options' own)
     "sources": {"attack": "sheet", "damage": "checked", ...},
     "status": "ready" | "unchecked" | "no roll" | "gap", "gaps": ["…"]}

Where each number comes from (`sources`), most trusted first: "correction" (the campaign's or askdnd's), "checked"
(askdnd's recipe, checked against the 2024 rules text: app/roll_recipes.py), "sheet" (the D&D Beyond sheet's own
attack and save numbers), "rule" (askdnd's rules: the Unarmed Strike's DC, class riders), "ddb" (D&D Beyond's
structured spell data, which askdnd hasn't checked: some are 2014 numbers), "text" (dice read from its own words).

Status: "ready" when every number comes from the first four; "unchecked" when one is D&D Beyond's data or read from
the words; "no roll" when nothing in it rolls; "gap" when its own words hold dice the plan doesn't roll, or it attacks
or makes a save with no damage when its words say it deals some. scripts/roll_coverage.py lists them for every
character at a table; tests/test_roll_plan.py keeps the party's sheets free of new gaps.
"""

import re

from app import class_rules
from app import roll_recipes as rr

DICE = re.compile(r"\b(\d+)d(\d+)\b")
# Dice that aren't a roll at the table: how many charges, doses or beads an item has (rolled once, when it's found)
COUNTS = re.compile(r"\b(\d+)d(\d+)(?:\s*\+\s*\d+)?\s+(?:expended\s+)?(?:charges|doses|magic beads|beads)\b", re.I)
SAVE = re.compile(r"^(Str|Dex|Con|Int|Wis|Cha)\s+(\d+)$")
BONUS = re.compile(r"^[+−-]\d+$")
TRUSTED = ("correction", "checked", "sheet", "rule")
UNARMED = (("damage", "Damage", "an attack roll"), ("grapple", "Grapple", "the target saves: Grappled"),
           ("shove", "Shove", "the target saves: pushed 5 feet or Prone"))


def _part(text: str, src: str) -> dict | None:
    p = rr.parse_part(text)
    if not p:
        return None
    n, d, flat, kind = p
    return {"dice": f"{n}d{d}" if n else "", "flat": flat, "type": kind, "from": src}


def _bonus(hit: str) -> int | None:
    hit = (hit or "").strip()
    return int(hit.replace("−", "-")) if BONUS.match(hit) else None


def _dice_in(text: str) -> set[str]:
    return {f"{n}d{d}" for n, d in DICE.findall(COUNTS.sub("", text or ""))}


def _recipe_source(o: dict) -> str | None:
    recipe = o.get("recipe")
    if not recipe:
        return None
    if recipe.get("house_rules"):
        return "correction"
    checked = rr.spell(o["name"]) if o.get("kind") == "spell" else rr.item(o["name"]) if o.get("kind") == "item" else None
    return "checked" if checked else "ddb"


def _spell_dc(sheet: dict) -> int | None:
    """The character's spell save DC, as the sheet gives it on its spells."""
    dcs = [int(m.group(2)) for sp in sheet.get("spells") or [] if (m := SAVE.match(sp.get("save") or ""))]
    return max(dcs) if dcs else None


def _spell_attack(sheet: dict) -> int | None:
    bonuses = [b for sp in sheet.get("spells") or [] if (b := _bonus(sp.get("attack") or "")) is not None]
    return max(bonuses) if bonuses else None


def _slot_levels(sheet: dict, level: int) -> list[int]:
    """The spell slot levels this character has at or above a spell's level (Pact Magic's too)."""
    slots = sheet.get("spell_slots") or {}
    have = {s["level"] for s in slots.get("slots") or [] if s.get("max")}
    if (slots.get("pact") or {}).get("max"):
        have.add(slots["pact"]["level"])
    return sorted(x for x in have if x >= level)


def plan(sheet: dict, o: dict) -> dict:
    """The roll plan for one Battle option (see the module's words)."""
    out = {"name": o["name"], "cost": o.get("cost", ""), "kind": o.get("kind", ""), "steps": [], "choice": None,
           "attack": None, "save": None, "damage": [], "heal": [], "riders": [], "spends": o.get("spends") or [],
           "sources": {}, "notes": [], "status": "", "gaps": []}
    src = out["sources"]
    hit = str(o.get("hit") or "")
    if (b := _bonus(hit)) is not None:
        out["attack"], src["attack"] = {"bonus": b}, "sheet"
    elif m := SAVE.match(hit):
        out["save"], src["save"] = {"ability": m.group(1), "dc": int(m.group(2)), "success": ""}, "sheet"

    if o.get("name") == "Unarmed Strike":  # Damage, Grapple or Shove first (2024 PHB; the prototype's first step)
        from app.character_views import unarmed_choices

        dc = (unarmed_choices(sheet, o) or {}).get("dc")
        out["choice"] = {"ask": "Which Unarmed Strike?", "options": [
            {"key": k, "name": n, "says": s if k == "damage" else f"{s} (DC {dc})"} for k, n, s in UNARMED]}
        src["choice"] = "rule"

    recipe, rsrc = o.get("recipe"), _recipe_source(o)
    events = (recipe or {}).get("events") or []
    for e in events:
        parts = [p for p in (_part(x, e.get("name") or o["name"]) for x in e.get("parts") or []) if p]
        for p in parts:
            p["count"] = e.get("count") or 1
            if e.get("mod"):
                p["mod"] = True  # (plus the spellcasting modifier)
        if e["on"] == "rider":
            out["riders"].append({"name": e.get("name") or o["name"], "when": "hit", "parts": parts, "while": "it lasts"})
        elif e["on"] in ("heal", "temp"):
            out["heal"] += [{**p, "temp": e["on"] == "temp"} for p in parts]
        elif e["on"] == "plain":
            out["damage"] += [{**p, "plain": True} for p in parts]
        else:
            out["damage"] += parts
            if e["on"] == "save":
                out["save"] = {"ability": e.get("save") or (out["save"] or {}).get("ability", ""),
                               "dc": (out["save"] or {}).get("dc"), "success": e.get("success", "")}
                src.setdefault("save", rsrc)
    if events and rsrc in ("checked", "correction"):  # the 2024 rules decide attack or save; the sheet only gives the numbers
        on = {e["on"] for e in events}
        if out["attack"] and "hit" not in on and "save" in on:
            out["notes"].append("D&D Beyond's sheet makes it an attack roll; the 2024 rules make it a save")
            out["attack"] = None
            src.pop("attack", None)
        if out["save"] and "save" not in on and "hit" in on:
            out["notes"].append("D&D Beyond's sheet makes it a save; the 2024 rules make it an attack roll")
            out["save"] = None
        if "hit" in on and not out["attack"] and (b := _spell_attack(sheet)) is not None:
            out["attack"], src["attack"] = {"bonus": b}, "sheet"
        if out["save"] and not out["save"].get("dc"):
            out["save"]["dc"] = _spell_dc(sheet)
    if events:
        src["damage" if out["damage"] or out["riders"] else "heal"] = rsrc
        if any(any(e.get("upcast") or []) or e.get("count_upcast") for e in events) and o.get("level"):
            levels = _slot_levels(sheet, o["level"])
            if len(levels) > 1:
                out["choice"], src["choice"] = {"ask": "At what level?", "options": [{"key": f"l{x}", "name": f"{x}", "says": ""} for x in levels]}, "sheet"
    elif o.get("dice"):
        weapon = next((a for a in sheet.get("attacks") or [] if a["name"] == o["name"]), None) or next(  # (Flurry of Blows: the Unarmed Strike's)
            (a for a in sheet.get("attacks") or [] if a.get("damage") and a["damage"] == o.get("meta")), None) if out["attack"] else None
        sheet_part = _part(weapon["damage"], o["name"]) if weapon and weapon.get("damage") else None  # (the sheet's own attack)
        part = sheet_part or _part(o["dice"], o["name"]) or {"dice": o["dice"], "flat": 0, "type": "", "from": o["name"]}
        (out["heal"] if o.get("heal") else out["damage"]).append(part)
        src["heal" if o.get("heal") else "damage"] = "sheet" if sheet_part else "text"

    if out["attack"] or (out["damage"] and o.get("kind") == "attack"):
        for r in class_rules.turn(sheet)["riders"]:  # what you can add once it hits (Stunning Strike, Divine Smite…)
            out["riders"].append({"name": r["name"], "when": "hit", "says": r["effect"], "on": r["when"]})

    steps = (["choose"] if out["choice"] else []) + (["attack"] if out["attack"] else []) + (["save"] if out["save"] else [])
    if out["damage"]:
        steps.append("damage")
    if out["heal"]:
        steps.append("heal")
    if out["damage"] or out["heal"]:
        steps.append("apply")
    out["steps"] = steps
    _judge(out, o, rsrc)
    return out


def _judge(out: dict, o: dict, rsrc: str | None) -> None:
    """The plan's status, and its gaps in plain words."""
    text = f"{o.get('meta') or ''} {o.get('text') or ''} {o.get('summary') or ''}"
    rolled = {p["dice"] for p in out["damage"] + out["heal"] if p.get("dice")}
    rolled |= {p["dice"] for r in out["riders"] for p in r.get("parts") or [] if p.get("dice")}
    for e in (o.get("recipe") or {}).get("events") or []:
        rolled |= {f"{n}d{d}" for x in e.get("upcast") or [] for n, d in DICE.findall(x)}
        if e.get("cantrip") == "dice":  # (a cantrip's dice grow at levels 5, 11 and 17)
            rolled |= {f"{int(n) * k}d{d}" for x in e.get("parts") or [] for n, d in DICE.findall(x) for k in (2, 3, 4)}
    if rsrc not in ("checked", "correction"):  # (a checked recipe already accounts for every die in the rules text)
        unrolled = sorted(_dice_in(text) - rolled - {"1d20"})
        if unrolled:
            out["gaps"].append(f"its words have {', '.join(unrolled)}, which the plan doesn't roll")
    if (out["attack"] or out["save"]) and not out["damage"] and not out["heal"] and re.search(r"\d+d\d+[^.]{0,40}damage", text):
        out["gaps"].append("it attacks or calls for a save, and its words deal damage the plan doesn't have")
    if out["gaps"]:
        out["status"] = "gap"
    elif not out["steps"] or out["steps"] == ["choose"] and o.get("name") != "Unarmed Strike":
        out["status"] = "no roll"
    elif all(s in TRUSTED for s in out["sources"].values()):
        out["status"] = "ready"
    else:
        out["status"] = "unchecked"


def plans(sheet: dict) -> list[dict]:
    """Every Battle option's plan, in Battle's order."""
    from app.character_views import options

    return [plan(sheet, o) for o in options(sheet, set())]


# The gaps askdnd knows about on the table's sheets, each with what fills it (scripts/roll_coverage.py, Nov 9). A gap
# not listed fails tests/test_roll_plan.py; one that's filled must come off the list (the test says so).
KNOWN_GAPS = {
    "Green-Flame Blade": "a 2024 spell outside the free rules with no recipe: needs a checked one (the second target's fire)",
    "Branding Smite": "D&D Beyond's data rolls it on casting with no upcasting: needs a checked recipe (on the next hit, +1d6 a level)",
    "Depth Charge": "a spell outside the free rules: needs a checked recipe",
    "Raulothim's Psychic Lance": "a spell outside the free rules: needs a checked recipe",
    "Find Steed": "the dice are the steed's (its stat block, app/summons.py), not the caster's",
    "Favored by the Gods": "adds 2d4 to a missed attack or failed save: the card's after-a-miss pill",
    "Guidance": "adds 1d4 to an ability check: a pill on the check it's used on",
    "Deflect Attack": "reduces the damage you take: a Reaction's own roll, not yet a step of the card",
    "Deflect Attack: Redirect Attack": "the same reduction; the redirected damage is in the plan",
    "Unarmed Strike": "the Martial Arts die its words name for lower levels; the sheet's die is the one rolled",
    "Soul Coin": "Drain Life's Temporary Hit Points: needs an item recipe",
}
