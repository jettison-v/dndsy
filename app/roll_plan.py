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
# ...and dice that aren't this action's roll: how long something lasts, or the lower-level die a feature's words name
# ("roll 1d6 in place of the normal damage": the sheet already has this level's)
ASIDES = re.compile(r"\b\d+d\d+\s+(?:hours?|minutes?|days?|rounds?)\b|\broll \d+d\d+ in place of\b", re.I)
COUNTS = re.compile(r"\b(\d+)d(\d+)(?:\s*\+\s*\d+)?\s+(?:expended\s+)?(?:charges|doses|magic beads|beads)\b", re.I)
SAVE = re.compile(r"^(Str|Dex|Con|Int|Wis|Cha)\s+(\d+)$")
BONUS = re.compile(r"^[+−-]\d+$")
TRUSTED = ("correction", "checked", "sheet", "rule")
UNARMED = (("damage", "Damage", "an attack roll"), ("grapple", "Grapple", "the target saves: Grappled"),
           ("shove", "Shove", "the target saves: pushed 5 feet or Prone"))


def fill(part: str, sheet: dict) -> str:
    """A recipe part's {tokens} from the sheet: {level:Fighter}, {mod:dexterity}, N{martial_arts} (the Monk's die),
    {sneak} (Sneak Attack's d6s), {lands_aid} (Land's Aid's d6s), N{bardic} (the Bard's die)."""
    lv = {c.get("name"): c.get("level") or 0 for c in sheet.get("classes") or []}
    mods = {a["key"]: a.get("modifier") or 0 for a in sheet.get("abilities") or []}
    monk, bard = lv.get("Monk", 0), lv.get("Bard", 0)
    die = {"martial_arts": 0 if not monk else 6 if monk < 5 else 8 if monk < 11 else 10 if monk < 17 else 12,
           "bardic": 0 if not bard else 6 if bard < 5 else 8 if bard < 10 else 10 if bard < 15 else 12}
    part = re.sub(r"(\d*)\{(martial_arts|bardic)\}", lambda m: f"{m.group(1) or 1}d{die[m.group(2)]}" if die[m.group(2)] else "", part)
    druid = lv.get("Druid", 0)
    plain = {"sneak": str((lv.get("Rogue", 0) + 1) // 2), "lands_aid": str(2 + (druid >= 10) + (druid >= 14))}

    def value(m):
        k = m.group(1)
        return str(lv.get(k[6:], 0)) if k.startswith("level:") else str(mods.get(k[4:], 0)) if k.startswith("mod:") else plain.get(k, "")
    out = re.sub(r"\{([^}]+)\}", value, part).replace("+-", "-")
    return re.sub(r"\+0\b(?!d)", "", out)


def _part(text: str, src: str) -> dict | None:
    p = rr.parse_part((text or "").replace("\u2212", "-").replace("+-", "-"))  # (a weapon's 1d6+-1, Strength −1)
    if not p:
        return None
    n, d, flat, kind = p
    return {"dice": f"{n}d{d}" if n else "", "flat": flat, "type": kind, "from": src}


def _bonus(hit: str) -> int | None:
    hit = (hit or "").strip()
    return int(hit.replace("−", "-")) if BONUS.match(hit) else None


def _dice_in(text: str) -> set[str]:
    return {f"{n}d{d}" for n, d in DICE.findall(ASIDES.sub("", COUNTS.sub("", text or "")))}


def _recipe_source(o: dict) -> str | None:
    if o.get("kind") == "feature" and rr.feature(o["name"]) is not None:
        return "checked"
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

    recipe = rr.feature(o["name"]) if o.get("kind") == "feature" and rr.feature(o["name"]) is not None else o.get("recipe")
    rsrc = _recipe_source(o)
    events = (recipe or {}).get("events") or []
    if not events and (mod := rr.modifier(o["name"])):  # it changes another roll: Guidance, Sneak Attack, Deflect Attacks
        out["modifier"], src["modifier"] = _modifier(o["name"], mod, sheet), "checked"
        out["steps"], out["status"] = ["modify"], "ready"
        out["modifiers"] = []
        return out
    for e in events:
        parts = [p for p in (_part(fill(x, sheet), e.get("name") or o["name"]) for x in e.get("parts") or []) if p]
        if e.get("alt"):
            out.setdefault("alternatives", []).append({"of": e.get("name") or o["name"], "parts": [p for p in (_part(x, e.get("name") or o["name"]) for x in e["alt"]) if p], "says": e.get("note", "")})
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
    if out["save"] and not out["save"].get("dc"):  # a feature's: its words say the DC ("DC 14"), else it's the spell save DC
        said = re.search(r"\bDC (\d+)", f"{o.get('text') or ''} {o.get('summary') or ''} {o.get('meta') or ''}")
        out["save"]["dc"] = int(said.group(1)) if said else _spell_dc(sheet)
        src["save"] = "sheet"
    if events:
        src["damage" if out["damage"] or out["riders"] else "heal"] = rsrc
        if any(any(e.get("upcast") or []) or e.get("count_upcast") for e in events) and o.get("level"):
            levels = _slot_levels(sheet, o["level"])
            if len(levels) > 1:
                out["choice"], src["choice"] = {"ask": "At what level?", "options": [{"key": f"l{x}", "name": f"{x}", "says": ""} for x in levels]}, "sheet"
    elif recipe is not None and rsrc in ("checked", "correction"):
        pass  # (a checked recipe that rolls nothing: Shillelagh, Find Steed; never dice read from its words)
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
    out["modifiers"] = modifiers_for(sheet, "attack" if out["attack"] else "save" if out["save"] else "")

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


def _modifier(name: str, mod: dict, sheet: dict) -> dict:
    out = {"name": name, **{k: v for k, v in mod.items() if k not in ("why", "checked")}, "why": mod.get("why", "")}
    for k in ("adds", "reduces"):
        if mod.get(k):
            out[k] = fill(mod[k], sheet)
    return out


def _has(sheet: dict) -> set[str]:
    """The names of what the character has: features, actions, spells (what a modifier is named after)."""
    names = {a.get("name") for a in sheet.get("actions") or []} | {s.get("name") for s in sheet.get("spells") or []}
    names |= {f.get("name") for f in sheet.get("features") or [] if isinstance(f, dict)}
    return {n for n in names if n}


def modifiers_for(sheet: dict, roll: str) -> list[dict]:
    """What this character can do to a roll of this kind ("attack", "save", "check"): their own modifiers, each with
    when it applies (before, after a failure, on a hit). Bless and the like, given by others, come from the table."""
    if not roll:
        return []
    has = _has(sheet)
    out = []
    for name in sorted(has):
        mod = rr.modifier(name)
        if not mod or mod.get("gives") or mod.get("from"):
            continue
        if roll in mod.get("to") or (roll == "attack" and mod.get("when") == "on_hit"):
            out.append(_modifier(name, mod, sheet))
    return out


def _judge(out: dict, o: dict, rsrc: str | None) -> None:
    """The plan's status, and its gaps in plain words."""
    text = f"{o.get('meta') or ''} {o.get('text') or ''} {o.get('summary') or ''}"
    rolled = {p["dice"] for p in out["damage"] + out["heal"] if p.get("dice")}
    rolled |= {p["dice"] for r in out["riders"] for p in r.get("parts") or [] if p.get("dice")}
    for e in (o.get("recipe") or {}).get("events") or []:
        rolled |= {f"{n}d{d}" for x in e.get("upcast") or [] for n, d in DICE.findall(x)}
        times = {"dice": (2, 3, 4), "extra": (1, 2, 3)}.get(e.get("cantrip"), ())  # (a cantrip's dice grow at levels 5, 11 and 17)
        rolled |= {f"{int(n) * k}d{d}" for x in e.get("parts") or [] for n, d in DICE.findall(x) for k in times}
        rolled |= {f"{n}d{d}" for x in e.get("alt") or [] for n, d in DICE.findall(x)}  # (an alternative: Depth Charge underwater)
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
KNOWN_GAPS: dict[str, str] = {}  # (empty since Nov 9: every party gap has a recipe, a modifier or a reason it isn't a roll)
