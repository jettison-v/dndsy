"""What an item would mean for a character (Brett's feedback note 1, Nov 3; docs/mockups/item-for-you/): the item
browser's details say it in a For <character> section, and each row of its list has an icon, can use it or can with a
catch (Brett: "A, details only, but it should have some sort of iconography for the ability to use it or not").

Worked out from the character's D&D Beyond sheet (as askdnd shows it) and the item's 2024 rules as D&D Beyond keeps them
(app/giving.py `_item`): weapon proficiency and the attack it would make, armor training and the Armor Class it would give
(what it replaces), Strength and Stealth, attunement and what a magic item grants. Facts only, never which to pick
(inform, don't advise); the DM rules. Anyone can pick up anything: "a catch" is a cost the rules attach, never "can't".

Compared number by number (Brett chose both A and B, Nov 4, docs/mockups/gear-compare/): `compare` lists, for each thing
the item could take the place of (a weapon: each attack on the sheet; armor: what gives the AC now), rows of now and with
it and by how much, and `chips` the row's few biggest changes for the list. Never sorted or marked "best".
"""

import re

MASTERIES = {"Cleave", "Graze", "Nick", "Push", "Sap", "Slow", "Topple", "Vex"}
ARMOR = {1: "Light Armor", 2: "Medium Armor", 3: "Heavy Armor", 4: "Shields"}
KIND = {1: "light", 2: "medium", 3: "heavy"}
ABILITY = {"strength": "Strength", "dexterity": "Dexterity", "constitution": "Constitution", "intelligence": "Intelligence",
           "wisdom": "Wisdom", "charisma": "Charisma"}
BASE_PART = re.compile(r"\((light|medium|heavy) armor\)$|^No armor$|^Dexterity modifier|^Unarmored Defense")
ATTUNE_MAX = 3


def _mod(score: int) -> int:
    return (score - 10) // 2


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{abs(n)}"


def _with(dice: str, n: int) -> str:
    return f"{dice} {'+' if n >= 0 else '−'} {abs(n)}" if n else dice


def _avg(text: str) -> float | None:
    """The average of a damage like "1d6+3 bludgeoning", "1d8 − 1" or "8": the formula before the words, as Table rolls
    reads it (table_rolls.parse_formula)."""
    from app.table_rolls import parse_formula

    m = re.match(r"[\dd+−-]+", (text or "").replace(" ", ""))
    if not m:
        return None
    if m.group(0) == "0":
        return 0.0
    parsed = parse_formula(m.group(0))
    return sum(c * (sides + 1) / 2 for c, sides in parsed[0]) + parsed[1] if parsed else None


def _num(n: float) -> str:
    return f"{n:g}"


def _row(k: str, now: str, then: str, delta: float | None = None, chip: str = "", why: str = "", lost: bool = False) -> dict:
    """One number, now and with it: up, down, the same, or lost (a feature that stops working)."""
    if lost:
        return {"k": k, "now": now, "then": then, "dir": "lost", "d": "Lost", "why": why, "chip": chip}
    if delta is None:
        delta = 0
    d = "up" if delta > 0 else "down" if delta < 0 else "same"
    mark = {"up": "▲ ", "down": "▼ ", "same": ""}[d]
    return {"k": k, "now": now, "then": then, "dir": d, "d": (mark + _num(abs(delta))) if delta else "Same", "why": why,
            "chip": f"{chip} {mark.strip()}{_num(abs(delta))}" if chip and delta else ""}  # (the list shows only what changes)


def _scores(sheet: dict) -> dict:
    return {a["key"]: a["score"] for a in sheet.get("abilities") or []}


def fit(sheet: dict | None, item: dict, name: str = "") -> dict:
    """{"icon": "ok" | "warn" | None, "why": a few words for the icon, "lines": [(kind, text)]}: kind "ok", "warn",
    "change" or "note". Nothing to say (rope, a potion): no icon and no lines."""
    if not sheet:
        return {"icon": None, "why": "", "lines": [], "compare": [], "chips": []}
    who = name or (sheet.get("name") or "").split()[0] or "They"
    lines, catches, goods = [], [], []
    compare = [{"place": "", "rows": []}]  # (a weapon's: one per attack it could take the place of)
    if item.get("weapon_cat"):
        compare = _weapon(sheet, item, who, lines, catches, goods)
    elif item.get("armor_type") in (1, 2, 3):
        _armor(sheet, item, who, lines, catches, goods, compare[0])
    elif item.get("armor_type") == 4:
        _shield(sheet, item, who, lines, catches, goods, compare[0])
    if item.get("attune"):
        _attunement(sheet, item, who, lines, catches, goods, compare)
    _granted(sheet, item, lines, compare)
    compare = [c for c in compare if c["rows"]]
    chips = [r["chip"] for r in (compare[0]["rows"] if compare else []) if r["chip"]][:3]
    out = {"lines": lines, "compare": compare, "chips": chips}
    if catches:
        return {"icon": "warn", "why": catches[0], **out}
    return {"icon": "ok" if goods else None, "why": goods[0] if goods else "", **out}


def _weapon(sheet, item, who, lines, catches, goods):
    profs = set((sheet.get("proficiencies") or {}).get("weapons") or [])
    kind = "Martial Weapons" if item["weapon_cat"] == 2 else "Simple Weapons"
    base = item.get("base_name") or item["name"]
    proficient = kind in profs or base in profs
    if proficient:
        lines.append(("ok", f"Proficient: {kind if kind in profs else base}."))
        goods.append(f"Proficient: {kind if kind in profs else base}")
    else:
        lines.append(("warn", f"Not proficient with {kind.lower()} (theirs: {', '.join(sorted(profs)) or 'none'}): no Proficiency Bonus to hit."))
        catches.append(f"Not proficient: {kind.lower()}")
    sc = _scores(sheet)
    strm, dexm = _mod(sc.get("strength", 10)), _mod(sc.get("dexterity", 10))
    props = item.get("props") or {}
    why = ""
    if item.get("attack_type") == 2:
        ab, m = "Dexterity", dexm
    elif "Finesse" in props:
        (ab, m), why = (("Dexterity", dexm) if dexm > strm else ("Strength", strm)), ", Finesse"
    elif _monk_weapon(sheet, item, props) and dexm > strm:  # (Martial Arts: a Monk weapon may use Dexterity)
        (ab, m), why = ("Dexterity", dexm), ", Martial Arts"
    else:
        ab, m = "Strength", strm
    magic = sum(int(x["value"] or 0) for x in item.get("mods") or [] if x["sub"] == "magic")
    pb = sheet.get("proficiency_bonus") or 2
    hit = m + (pb if proficient else 0) + magic
    parts = f"{ab} {_signed(m)}{why}" + (f", Proficiency {_signed(pb)}" if proficient else "") + (f", magic {_signed(magic)}" if magic else "")
    dmg = _with(item["dice"], m + magic) if item.get("dice") else ""
    if dmg:
        two = props.get("Versatile")
        lines.append(("change", f"Attack {_signed(hit)} to hit ({parts}), {dmg} {item.get('damage_type') or ''}".rstrip()
                      + (f"; with two hands {_with(two, m + magic)}." if two else ".")))
    mastery = next((p for p in props if p in MASTERIES), None)
    if mastery:
        has = any(f.get("name") == "Weapon Mastery" for f in sheet.get("features") or [])
        lines.append(("note", f"Its mastery, {mastery}: {who}'s if chosen for Weapon Mastery." if has
                      else f"Its mastery, {mastery}, needs the Weapon Mastery feature: {who} doesn't have it."))
    # Against each attack on the sheet it could take the place of (the ones in hand first, Unarmed Strike last)
    attacks = sorted(sheet.get("attacks") or [], key=lambda a: a.get("key") == "attack:unarmed")
    out = []
    for a in attacks or [{"name": "", "to_hit": "", "damage": ""}]:
        now_hit = int((a.get("to_hit") or "").replace("−", "-") or 0) if a.get("to_hit") else None
        rows = [_row("To hit", a.get("to_hit") or "—", _signed(hit), hit - now_hit if now_hit is not None else None, "Hit", parts)]
        if dmg:
            was, new = _avg(a.get("damage") or ""), _avg(dmg)
            now_text = re.sub(r"\s+[a-z]+$", "", a.get("damage") or "") or "—"
            delta = (round((new - was) * 2) / 2) if was is not None and new is not None else None
            rows.append(_row("Damage", now_text, dmg, delta, "Dmg",
                             f"average {_num(was)} → {_num(new)}" if was is not None and new is not None else ""))
        out.append({"place": a["name"], "rows": rows})
    return out


def _monk_weapon(sheet, item, props) -> bool:
    """2024 Martial Arts: Simple Melee weapons and Martial Melee weapons with the Light property, for a Monk."""
    monk = any(a.get("martial_arts") for a in sheet.get("attacks") or [])
    return monk and item.get("attack_type") == 1 and (item.get("weapon_cat") == 1 or "Light" in props)


def _ac_parts(sheet):
    return (sheet.get("armor_parts") or {}).get("parts") or []


def _unarmored(sheet) -> str:
    return next((n for n, _ in _ac_parts(sheet) if n.startswith("Unarmored Defense")), "")


def _armor(sheet, item, who, lines, catches, goods, cmp):
    trained = ARMOR[item["armor_type"]] in set((sheet.get("proficiencies") or {}).get("armor") or [])
    if trained:
        lines.append(("ok", f"Trained: {ARMOR[item['armor_type']]}."))
        goods.append(f"Trained: {ARMOR[item['armor_type']]}")
    else:
        lines.append(("warn", (f"No {ARMOR[item['armor_type']]} training. Wearing it: Disadvantage on every D20 Test that uses "
                              "Strength or Dexterity, and no spellcasting.")))
        catches.append(f"Not trained: {ARMOR[item['armor_type']]}")
    dex = _mod(_scores(sheet).get("dexterity", 10))
    add = dex if item["armor_type"] == 1 else min(dex, 2) if item["armor_type"] == 2 else 0
    others = [(n, v) for n, v in _ac_parts(sheet) if not BASE_PART.search(n)]
    now = sheet.get("armor_class") or 0
    new = (item.get("ac") or 0) + add + sum(v for _, v in others)
    ud = _unarmored(sheet)
    cmp["place"] = ud.split(" (")[0] if ud else next((n.split(" (")[0] for n, _ in _ac_parts(sheet) if BASE_PART.search(n) and "armor)" in n), "")
    cmp["rows"].append(_row("Armor Class", str(now), str(new), new - now, "AC"))
    lines.append(("change", f"AC {now} → {new}: {item['name']}'s {item.get('ac')}"
                  + (f" + Dexterity {_signed(add)}" if add else "") + (f" + {', '.join(n for n, _ in others)}" if others else "")
                  + (f", replacing {ud}" if ud else "") + "."))
    req = item.get("str_req")
    if req and _scores(sheet).get("strength", 10) < req:
        lines.append(("warn", f"Needs Strength {req}; {who} has {_scores(sheet).get('strength', 10)}: Speed −10 ft."))
        catches.append(f"Strength {req} needed")
    speed = sheet.get("speed") or {}
    unarmored_move = next((v for n, v in speed.get("parts") or [] if n.startswith("Unarmored Movement")), 0)
    if unarmored_move or (req and _scores(sheet).get("strength", 10) < req):
        cut = unarmored_move + (10 if req and _scores(sheet).get("strength", 10) < req else 0)
        lines.append(("change", f"Speed {speed.get('walk', 0)} → {max(0, speed.get('walk', 0) - cut)} ft"
                      + (" (Unarmored Movement needs no armor)" if unarmored_move else "") + "."))
        cmp["rows"].append(_row("Speed", f"{speed.get('walk', 0)} ft", f"{max(0, speed.get('walk', 0) - cut)} ft", -cut, "Speed"))
    if item.get("stealth_dis"):
        lines.append(("warn", "Disadvantage on Dexterity (Stealth) checks."))
        stealth = next((k["label"] for k in sheet.get("skills") or [] if k["name"] == "Stealth"), "")
        cmp["rows"].append(_row("Stealth", stealth or "—", "Disadvantage", lost=True))
    if not trained and sheet.get("spellcasting"):
        cmp["rows"].append(_row("Spellcasting", "yes", "no", lost=True, chip="No spells"))
    if ud and "Wisdom" in ud:
        cmp["rows"].append(_row("Martial Arts", "yes", "no", lost=True, why="only without armor or a Shield"))
    if ud:
        lines.append(("note", f"{ud.split(' (')[0]} works only without armor."))


def _shield(sheet, item, who, lines, catches, goods, cmp):
    trained = "Shields" in set((sheet.get("proficiencies") or {}).get("armor") or [])
    if trained:
        lines.append(("ok", "Trained: Shields."))
        goods.append("Trained: Shields")
    else:
        lines.append(("warn", "No Shield training: no Armor Class from it."))
        catches.append("Not trained: Shields")
    now, ud = sheet.get("armor_class") or 0, _unarmored(sheet)
    held = any(i.get("equipped") and i.get("type") == "Shield" for i in sheet.get("inventory") or [])
    if held:
        lines.append(("note", f"{who} already holds a shield: one at a time."))
        return
    gain = (item.get("ac") or 2) if trained else 0
    cmp["place"] = "In your other hand"
    if ud and "Wisdom" in ud:  # (a Monk's Unarmored Defense needs no shield; a Barbarian's allows one)
        parts = dict(_ac_parts(sheet))
        lose = parts.get(ud, 0)
        lines.append(("change", f"AC {now} → {now - lose + gain}: {ud} doesn't work with a Shield."))
        cmp["rows"].append(_row("Armor Class", str(now), str(now - lose + gain), gain - lose, "AC", f"{ud.split(' (')[0]} stops with a Shield"))
        cmp["rows"].append(_row("Martial Arts", "yes", "no", lost=True, why="only without armor or a Shield"))
        speed = sheet.get("speed") or {}
        move = next((v for n, v in speed.get("parts") or [] if n.startswith("Unarmored Movement")), 0)
        if move:
            cmp["rows"].append(_row("Speed", f"{speed.get('walk', 0)} ft", f"{speed.get('walk', 0) - move} ft", -move, "Speed",
                                    "Unarmored Movement needs no Shield"))
    else:
        lines.append(("change", f"AC {now} → {now + gain}."))
        cmp["rows"].append(_row("Armor Class", str(now), str(now + gain), gain, "AC"))


def _attunement(sheet, item, who, lines, catches, goods, compare):
    have = sheet.get("attuned") or []
    for_whom = (item.get("attune_note") or "").strip()
    classes = {k.get("name") for k in sheet.get("classes") or []}
    if for_whom:
        caster = bool(sheet.get("spellcasting"))
        ok = (for_whom.lower() == "spellcaster" and caster) or any(c.lower() in for_whom.lower() for c in classes if c)
        if not ok:
            lines.append(("warn", f"Attunement by a {for_whom} only: {who} isn't one."))
            catches.append(f"Attunement: {for_whom} only")
    if len(have) >= ATTUNE_MAX:
        lines.append(("warn", f"Attunement full ({len(have)} of {ATTUNE_MAX}: {', '.join(have)}): ending one makes room."))
        catches.append("Attunement full")
    else:
        lines.append(("change", f"Attunement {len(have)} → {len(have) + 1} of {ATTUNE_MAX}" + (f" (now: {', '.join(have)})." if have else ".")))
        goods.append(f"Attunement {len(have) + 1} of {ATTUNE_MAX}")
        for c in compare:
            c["rows"].append(_row("Attuned", f"{len(have)} of {ATTUNE_MAX}", f"{len(have) + 1} of {ATTUNE_MAX}", why=", ".join(have)))


def _granted(sheet, item, lines, compare):
    """What a magic item grants, from D&D Beyond's modifiers: Armor Class, saving throws, an ability score."""
    sc = _scores(sheet)
    for m in item.get("mods") or []:
        v, sub = m["value"], m["sub"] or ""
        if not isinstance(v, int) or sub == "magic":
            continue
        when = " while attuned" if m["attuned"] else ""
        rows = []
        if sub == "armor-class" and m["type"] == "bonus" and not item.get("armor_type"):
            now = sheet.get("armor_class") or 0
            lines.append(("change", f"AC {now} → {now + v}{when}."))
            rows.append(_row("Armor Class", str(now), str(now + v), v, "AC", when.strip()))
        elif sub == "saving-throws" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to every saving throw{when}."))
            rows.append(_row("Every saving throw", "as now", f"{_signed(v)} each", v, "Saves", when.strip()))
        elif sub == "spell-attacks" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to spell attack rolls{when}."))
            rows.append(_row("Spell attack", "as now", _signed(v), v, "Spell hit", when.strip()))
        elif sub == "spell-save-dc" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to their spell save DC{when}."))
            rows.append(_row("Spell save DC", "as now", _signed(v), v, "DC", when.strip()))
        elif sub.endswith("-score") and sub[:-6] in ABILITY:
            key, now = sub[:-6], sc.get(sub[:-6], 10)
            new = max(now, v) if m["type"] == "set" else now + v
            if new != now:
                lines.append(("change", f"{ABILITY[key]} {now} → {new}{when}: its checks and saves {_signed(_mod(now))} → {_signed(_mod(new))}."))
                rows.append(_row(ABILITY[key], f"{now} ({_signed(_mod(now))})", f"{new} ({_signed(_mod(new))})", new - now, ABILITY[key][:3],
                                 f"its checks and saves{when}"))
            else:
                lines.append(("note", f"{ABILITY[key]} {v}{when}: {_signed(_mod(now))} already, no change."))
        for c in compare:
            c["rows"] += rows
