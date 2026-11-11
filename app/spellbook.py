"""The Spell Book (Character › Battle): every spell the character can cast now, grouped by what it
does, with the average roll at each slot level so upcasting is counted. Concentration tracking
lives here too: which spell, at what level, and the round count (Brett, 2026-10-21).

Averages come from the same audited recipes the roll window uses (app/roll_recipes.py), resolved
like app.js resolve(): upcast dice per slot level above the spell's, cantrip dice by character
level. Inform, don't advise: the Spell Book shows numbers and lets the player sort; it never
ranks spells as "best".
"""

import re

from app import house_rules
from app import roll_recipes as rr

EFFECTS = [("damage", "Damage"), ("heal", "Heal"), ("control", "Control"), ("support", "Support"), ("utility", "Utility")]
ORD = {0: "cantrip", 1: "1st", 2: "2nd", 3: "3rd"}
PART = re.compile(r"^(?:(\d+)d(\d+)([+-]\d+)?|([+-]?\d+))(?:\s+(.+))?$")


def ordinal(n: int) -> str:
    return ORD.get(n, f"{n}th")


def effect_of(sp: dict) -> str:
    """One group per spell, from what it rolls and D&D Beyond's tags: damage first (Moonbeam is
    Damage and Control), then healing, control, support (protection and buffs), and everything else."""
    tags = set(sp.get("tags") or [])
    if sp.get("casting_time") == "Reaction" and "Warding" in tags:
        return "support"  # Absorb Elements, Shield: protection that happens to roll a little damage
    if sp.get("damage") or "Damage" in tags:
        return "damage"
    if sp.get("healing") or "Healing" in tags:
        return "heal"
    if tags & {"Control", "Debuff", "Banishment", "Negation"}:
        return "control"
    if tags & {"Warding", "Buff"}:
        return "support"
    return "utility"


def resolve(recipe: dict, event: dict, slot: int, char_level: int) -> dict | None:
    """An event's parts and count when cast at this slot level: app/roll_plan.py at_level, the one place it's worked out."""
    from app.roll_plan import at_level

    r = at_level(recipe, event, slot, char_level)
    return {**event, **r} if r else None


def _main_event(recipe: dict | None) -> dict | None:
    """The event the average is about: the first one that rolls damage or healing."""
    for ev in (recipe or {}).get("events") or []:
        if ev.get("on") in ("hit", "save", "auto", "rider", "heal", "temp") and ev.get("parts"):
            return ev
    return None


def average(recipe: dict | None, slot: int, char_level: int, spell_mod: int = 0) -> dict | None:
    """{"avg": 16.5, "dice": "3d10 radiant", "per": "on a failed save"} at this slot level, or None."""
    ev = _main_event(recipe)
    if not ev:
        return None
    e = resolve(recipe, ev, slot, char_level)
    if not e:
        return None
    from app.roll_plan import _part_text

    total, shown = 0.0, []
    for p in e["parts"]:
        x = rr.parse_part(p)
        if not x:
            continue
        total += x[0] * (x[1] + 1) / 2 + x[2]
        shown.append(_part_text(*x).replace(" or ", "/"))
    if e.get("mod"):
        total += spell_mod
        shown.append(str(spell_mod))
    total *= e["count"]
    per = {"hit": "on a hit", "save": "on a failed save", "auto": "each", "rider": "each hit", "heal": "healed", "temp": "Temporary HP"}[e["on"]]
    count = f"{e['count']} × " if e["count"] > 1 else ""
    return {"avg": round(total, 1), "dice": count + " + ".join(shown), "per": per}


def slot_levels(sheet: dict) -> list[dict]:
    """The spell slot levels this character has, with how many are left (pact slots included)."""
    ss = sheet.get("spell_slots") or {}
    out = [{"level": s["level"], "left": s["max"] - s["used"], "max": s["max"]} for s in ss.get("slots") or [] if s.get("max")]
    if ss.get("pact"):
        p = ss["pact"]
        out.append({"level": p["level"], "left": p["max"] - p["used"], "max": p["max"], "pact": True})
    return sorted(out, key=lambda s: s["level"])


def _entry(sp: dict, sheet: dict, top: int, castable_in_form: set[str] | None = None) -> dict:
    """One spell as a list row: its numbers per slot level (up to `top`), its filter values, and the plan each of its
    roll buttons plays (app/roll_plan.py: the same plan as its row on Battle)."""
    from app import roll_plan

    recipe = house_rules.spell(sp["name"]) or sp.get("roll")
    level = sp.get("level") or 0
    char_level, mod = sheet.get("level") or 1, roll_plan.spell_mod(sheet, sp["name"]) or 0
    avgs = {}
    for slot in ([0] if not level else range(level, max(level, top) + 1)):
        a = average(recipe, slot, char_level, mod)
        if a:
            avgs[slot] = a
    e = {
        "key": sp["key"], "name": sp["name"], "level": level, "level_label": ordinal(level),
        "effect": effect_of(sp), "time": sp.get("casting_time") or "", "range": sp.get("range") or "",
        "duration": sp.get("duration") or "", "conc": bool(sp.get("concentration")), "ritual": bool(sp.get("ritual")),
        "attack": sp.get("attack") or "", "save": sp.get("save") or "", "summary": sp.get("summary") or "",
        "recipe": recipe if recipe and recipe.get("events") else None, "avgs": avgs,
        "ws": bool(castable_in_form and sp["name"] in castable_in_form),
        "rounds": rounds(sp.get("duration") or ""),
        # A free use (a species' or feat's spell, once per Long Rest) and where it's from: the Cast window offers it first
        "uses": sp.get("uses"), "from": sp.get("free_from") or "", "use_id": sp.get("use_id"),
        # A higher slot does more (its text says so, or its dice grow): else the Cast window says it changes nothing
        "higher": bool(HIGHER.search(sp.get("text") or "")) or len({str(v) for v in avgs.values()}) > 1,
    }
    e |= _facts(e, _main_event(e["recipe"]))
    e["f"] = facets(e)
    if e["recipe"]:
        o = {"name": sp["name"], "kind": "spell", "level": sp.get("level") or 0, "hit": e["attack"] or e["save"], "recipe": e["recipe"], "tags": [],
             "meta": sp.get("summary") or "", "text": sp.get("text") or "", "summary": sp.get("summary") or ""}
        e["plan"] = roll_plan.plan(sheet, o) if o["hit"] else None
        e["rolls"] = {"hit": roll_plan.effects(e["recipe"], sheet, sp["name"], True), "other": roll_plan.effects(e["recipe"], sheet, sp["name"], False)}
    return e


HIGHER = re.compile(r"Higher-Level Spell Slot|At Higher Levels|(?:spell )?slot level above", re.I)


def riders(sheet: dict, conc: dict | None) -> list[dict]:
    """Battle's On a hit for the spell being concentrated on, when it adds damage to each hit while it lasts (Hunter's
    Mark, Hex; feedback 48, Nov 7): {"name", "when", "effect", "source"}, as class_rules.turn's riders. Adding its dice to
    a damage roll is the roll workflows' (the component library, next)."""
    sp = next((s for s in (sheet or {}).get("spells") or [] if conc and s.get("name") == conc.get("spell")), None)
    recipe = (house_rules.spell(sp["name"]) or sp.get("roll")) if sp else None
    out = []
    for ev in (recipe or {}).get("events") or []:
        e = resolve(recipe, ev, conc.get("level") or 0, sheet.get("level") or 1) if ev.get("on") == "rider" else None
        if e and e["parts"]:
            out.append({"name": sp["name"], "when": "Each hit while it lasts", "source": "Concentration",
                        "effect": "+" + " + ".join(e["parts"]) + " damage (the spell says which hits count)"})
    return out


def concentrating(e: dict, level: int) -> dict:
    """What a character's Concentration on this spell holds, cast at this level."""
    return {"spell": e["name"], "key": e["key"], "level": max(level, e["level"]), "round": 1, "rounds": e["rounds"]}


def entries(sheet: dict, castable_in_form: set[str] | None = None) -> list[dict]:
    """Every spell the character can cast now, for the Spell Book."""
    top = max([s["level"] for s in slot_levels(sheet)] or [0])
    out = [_entry(sp, sheet, top, castable_in_form) for sp in sheet.get("spells") or []]
    return sorted(out, key=lambda e: (e["level"], e["name"]))


READY = ("always", "prepared", "known", "granted")
STATE_LABELS = {"always": "Always prepared", "prepared": "Prepared", "known": "Known", "spellbook": "In spellbook",
                "available": "Not prepared", "granted": ""}


def sheet_entries(sheet: dict) -> list[dict]:
    """Every spell on Sheet › Spells: each class's list (prepared or not) and spells from species,
    feats and items. Numbers at the spell's own level only (Sheet has no "Cast at")."""
    from app.character_views import granted_spells  # character_views imports this module's neighbours

    books = sheet.get("spellbook") or []
    out, seen = [], set()
    for b in books:
        for sp in b["spells"]:
            if sp["key"] in seen:
                continue
            seen.add(sp["key"])
            out.append(_entry(sp, sheet, 0) | {
                "state": sp["state"], "from": b["class"] if len(books) > 1 else "", "source": b["class"],
                "core": sp.get("core"), "book": sp.get("book") or ""})
    for sp in granted_spells(sheet):
        if sp["key"] not in seen:
            seen.add(sp["key"])
            out.append(_entry(sp, sheet, 0) | {
                "state": "granted", "from": ", ".join(sp.get("sources") or []), "source": "Species, feats and items",
                "core": sp.get("core"), "book": sp.get("book") or "", "uses": sp.get("uses")})
    for e in out:
        e["ready"] = e["state"] in READY
        e["state_label"] = STATE_LABELS.get(e["state"], "")
        e["f"]["from"] = e["source"]
        e["f"]["prep"] = "Prepared" if e["ready"] else "Not prepared"  # with the Shortlist view: what to prepare next
    return sorted(out, key=lambda e: (e["level"], e["name"]))


def sheet_filter_groups(items: list[dict]) -> list[dict]:
    """Sheet › Spells: Prepared first (Shortlist + Not prepared = spells you're considering but haven't
    prepared on D&D Beyond), then the Spell Book's groups, plus where a spell comes from when there's a choice."""
    groups = [{"key": "prep", "label": "Prepared", "values": ["Prepared", "Not prepared"]}] + filter_groups(items)
    froms = list(dict.fromkeys(e["f"]["from"] for e in items if e["f"].get("from")))
    if len(froms) > 1:
        groups.insert(5, {"key": "from", "label": "From", "values": froms})
    return groups


# What a successful save does to the damage, from the audited recipe: half, none, or the damage
# needs no save at all (Heat Metal: the save only decides whether you keep holding the object).
ON_SAVE = {"half": "Half damage", "none": "No damage", "lands": "Damage needs no save"}
AREA = re.compile(r"\b(cube|sphere|cone|line|cylinder|emanation|radius|square|wall)\b", re.I)


def _facts(e: dict, ev: dict | None) -> dict:
    on_save = None
    if e["save"] and ev and ev.get("on") == "save" and ev.get("success") in ("half", "none"):
        on_save = ev["success"]
    elif e["save"] and ev and ev.get("on") == "auto":
        on_save = "lands"
    types = []
    for part in (ev or {}).get("parts") or [] if (ev or {}).get("on") in ("hit", "save", "auto") else []:
        m = PART.match(part.strip())
        if m and m.group(5):
            types += [t.strip().capitalize() for t in m.group(5).split(" or ") if t.strip()]
    return {"on_save": on_save, "dmg_types": list(dict.fromkeys(types)), "area": bool(AREA.search(e["range"]))}


def _range_bucket(rng: str) -> str:
    low = rng.lower()
    if low.startswith(("self", "touch")):
        return "Self or touch"
    m = re.match(r"(\d+)\s*(ft|feet|mile)", low)
    if not m:
        return "Other"
    feet = int(m.group(1)) * (5280 if m.group(2) == "mile" else 1)
    return "Up to 30 ft" if feet <= 30 else "60 ft" if feet <= 60 else "90 ft or more"


def facets(e: dict) -> dict:
    """The filter values one spell has, by filter group (a list where a spell can have several)."""
    roll = "Attack roll" if e["attack"] else (e["save"].split()[0] + " save") if e["save"] else "No roll"
    return {
        "level": "Cantrip" if not e["level"] else ordinal(e["level"]),
        "effect": dict(EFFECTS)[e["effect"]],
        "time": {"Action": "Action", "Bonus action": "Bonus", "Reaction": "Reaction"}.get(e["time"], "Longer"),
        "conc": "Conc." if e["conc"] else "No Conc.",
        "ws": "Castable in a form" if e["ws"] else "",
        "ritual": "Ritual" if e["ritual"] else "Not a ritual",
        "roll": roll,
        "on_save": ON_SAVE.get(e["on_save"] or "", ""),
        "area": "Area" if e["area"] else "No area",
        "dmg": e["dmg_types"],
        "range": _range_bucket(e["range"]),
    }


def filter_groups(items: list[dict], wild_shape: bool = False) -> list[dict]:
    """Filter groups for the Spell Book (DESIGN.md › Lists and filters): the first four always show,
    the rest are under More filters. Values in a fixed order; the More groups list only values
    that occur, and the main groups keep every value (greyed out when nothing matches)."""
    def present(key):
        seen = []
        for e in items:
            for v in (e["f"][key] if isinstance(e["f"][key], list) else [e["f"][key]]):
                if v and v not in seen:
                    seen.append(v)
        return seen
    levels = sorted({e["level"] for e in items})
    rolls = ["Attack roll"] + [f"{a} save" for a in ("Str", "Dex", "Con", "Int", "Wis", "Cha")] + ["No roll"]
    groups = [
        {"key": "level", "label": "Level", "values": ["Cantrip" if not n else ordinal(n) for n in levels]},
        {"key": "effect", "label": "Effect", "values": [label for _, label in EFFECTS]},
        {"key": "time", "label": "Casting time", "values": ["Action", "Bonus", "Reaction", "Longer"]},
        {"key": "conc", "label": "Concentration", "values": ["Conc.", "No Conc."]},
    ]
    if wild_shape:
        groups.append({"key": "ws", "label": "Wild Shape", "values": ["Castable in a form"]})
    more = [
        {"key": "ritual", "label": "Ritual", "values": [v for v in ("Ritual", "Not a ritual") if v in present("ritual")]},
        {"key": "roll", "label": "Attack or save", "values": [v for v in rolls if v in present("roll")]},
        {"key": "on_save", "label": "On a successful save", "values": [v for v in ON_SAVE.values() if v in present("on_save")]},
        {"key": "area", "label": "Area", "values": [v for v in ("Area", "No area") if v in present("area")]},
        {"key": "dmg", "label": "Damage type", "values": sorted(present("dmg"))},
        {"key": "range", "label": "Range", "values": [v for v in ("Self or touch", "Up to 30 ft", "60 ft", "90 ft or more", "Other") if v in present("range")]},
    ]
    return groups + [{**g, "more": True} for g in more if g["values"]]


# ------------------------------------------------------------------ concentration


def rounds(duration: str) -> int:
    """How many rounds a Concentration spell lasts at most (10 rounds a minute)."""
    m = re.search(r"(\d+)\s*(round|minute|hour)", duration or "", re.I)
    if not m:
        return 0
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"round": 1, "minute": 10, "hour": 600}[unit]


def concentration_dc(damage: int) -> int:
    """DC 10 or half the damage taken, whichever is higher, up to 30 (2024 rules)."""
    return min(30, max(10, int(damage) // 2))


def concentration_save(saves: list[dict]) -> dict | None:
    """The Constitution save with the Advantage that applies to keeping Concentration (War Caster,
    Eldritch Mind): those sources' conditions are met by definition, so they count as always on."""
    con = next((s for s in saves or [] if s.get("key") in ("con", "constitution") or s.get("short") == "Con"), None)
    if not con:
        return None
    advs = [{**a, "when": ""} for a in con.get("adv") or [] if not a.get("when") or "concentration" in a["when"].lower()]
    return {"label": con["label"], "adv": advs}
