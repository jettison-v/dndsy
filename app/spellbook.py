"""The Spell Book (Character › Play): every spell the character can cast now, grouped by what it
does, with the average roll at each slot level so upcasting is counted. Concentration tracking
lives here too: which spell, at what level, and the round count (Brett, 2026-10-21).

Averages come from the same audited recipes the roll window uses (app/roll_recipes.py), resolved
like app.js resolve(): upcast dice per slot level above the spell's, cantrip dice by character
level. Inform, don't advise: the Spell Book shows numbers and lets the player sort; it never
ranks spells as "best".
"""

import re

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


def _parse(part: str) -> dict | None:
    m = PART.match((part or "").strip())
    if not m:
        return None
    if m.group(4) is not None:
        return {"n": 0, "s": 0, "flat": int(m.group(4)), "kind": m.group(5) or ""}
    return {"n": int(m.group(1)), "s": int(m.group(2)), "flat": int(m.group(3) or 0), "kind": m.group(5) or ""}


def _grow(part: str, extra: str, times: int) -> str:
    p = _parse(part)
    if not p or not extra or times <= 0:
        return part
    if re.fullmatch(r"[+-]\d+", extra):
        p["flat"] += int(extra) * times
    else:
        e = _parse(extra)
        if not e or e["s"] != p["s"]:
            return part
        p["n"] += e["n"] * times
    return _text(p)


def _text(p: dict) -> str:
    dice = f"{p['n']}d{p['s']}" + (f"{p['flat']:+d}" if p["flat"] else "") if p["n"] else str(p["flat"])
    return dice + (f" {p['kind']}" if p["kind"] else "")


def _tier(level: int) -> int:
    return 1 + (level >= 5) + (level >= 11) + (level >= 17)


def resolve(recipe: dict, event: dict, slot: int, char_level: int) -> dict | None:
    """An event's parts and count when cast at this slot level (app.js resolve())."""
    level = recipe.get("level") or 0
    e = {**event, "parts": list(event.get("parts") or []), "count": event.get("count") or 1}
    if level and slot > level:
        times = (slot - level) // (event.get("every") or 1)
        e["parts"] = [_grow(p, (event.get("upcast") or [""] * 9)[i] if i < len(event.get("upcast") or []) else "", times)
                      for i, p in enumerate(e["parts"])]
        e["count"] += (event.get("count_upcast") or 0) * times
    if not level and event.get("cantrip"):
        t = _tier(char_level or 1)
        base = lambda p: p.split(" ")[0].split("+")[0].split("-")[0]  # noqa: E731
        if event["cantrip"] == "count":
            e["count"] *= t
        elif event["cantrip"] == "extra":
            if t == 1:
                return None
            e["parts"] = [_grow(p, base(p), t - 2) for p in e["parts"]]
        else:
            e["parts"] = [_grow(p, base(p), t - 1) for p in e["parts"]]
    return e


def _main_event(recipe: dict | None) -> dict | None:
    """The event the average is about: the first one that rolls damage or healing."""
    for ev in (recipe or {}).get("events") or []:
        if ev.get("on") in ("hit", "save", "auto", "heal", "temp") and ev.get("parts"):
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
    total, shown = 0.0, []
    for p in e["parts"]:
        x = _parse(p)
        if not x:
            continue
        total += x["n"] * (x["s"] + 1) / 2 + x["flat"]
        shown.append(_text(x).replace(" or ", "/"))
    if e.get("mod"):
        total += spell_mod
        shown.append(str(spell_mod))
    total *= e["count"]
    per = {"hit": "on a hit", "save": "on a failed save", "auto": "each", "heal": "healed", "temp": "Temporary HP"}[e["on"]]
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


def _spell_mod(sheet: dict) -> int:
    sc = (sheet.get("spellcasting") or [{}])[0]
    return next((v for k, v in sc.get("dc_parts") or [] if k.endswith(" modifier")), 0)


def entries(sheet: dict, castable_in_form: set[str] | None = None) -> list[dict]:
    """Every spell the character can cast now, for the Spell Book."""
    char_level = sheet.get("level") or 1
    mod = _spell_mod(sheet)
    top = max([s["level"] for s in slot_levels(sheet)] or [0])
    out = []
    for sp in sheet.get("spells") or []:
        recipe = rr.spell(sp["name"]) or sp.get("roll")
        level = sp.get("level") or 0
        avgs = {}
        for slot in ([0] if not level else range(level, max(level, top) + 1)):
            a = average(recipe, slot, char_level, mod)
            if a:
                avgs[slot] = a
        out.append({
            "key": sp["key"], "name": sp["name"], "level": level, "level_label": ordinal(level),
            "effect": effect_of(sp), "time": sp.get("casting_time") or "", "range": sp.get("range") or "",
            "duration": sp.get("duration") or "", "conc": bool(sp.get("concentration")), "ritual": bool(sp.get("ritual")),
            "attack": sp.get("attack") or "", "save": sp.get("save") or "", "summary": sp.get("summary") or "",
            "recipe": recipe if recipe and recipe.get("events") else None, "avgs": avgs,
            "ws": bool(castable_in_form and sp["name"] in castable_in_form),
            "rounds": rounds(sp.get("duration") or ""),
        })
    return sorted(out, key=lambda e: (e["level"], e["name"]))


def counts(items: list[dict]) -> dict[str, int]:
    return {k: sum(1 for e in items if e["effect"] == k) for k, _ in EFFECTS}


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
