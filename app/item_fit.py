"""What an item would mean for a character (Brett's feedback note 1, Nov 3; docs/mockups/item-for-you/): the item
browser's details say it in a For <character> section, and each row of its list has an icon, can use it or can with a
catch (Brett: "A, details only, but it should have some sort of iconography for the ability to use it or not").

Worked out from the character's D&D Beyond sheet (as askdnd shows it) and the item's 2024 rules as D&D Beyond keeps them
(app/giving.py `_item`): weapon proficiency and the attack it would make, armor training and the Armor Class it would give
(what it replaces), Strength and Stealth, attunement and what a magic item grants. Facts only, never which to pick
(inform, don't advise); the DM rules. Anyone can pick up anything: "a catch" is a cost the rules attach, never "can't".
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


def _scores(sheet: dict) -> dict:
    return {a["key"]: a["score"] for a in sheet.get("abilities") or []}


def fit(sheet: dict | None, item: dict, name: str = "") -> dict:
    """{"icon": "ok" | "warn" | None, "why": a few words for the icon, "lines": [(kind, text)]}: kind "ok", "warn",
    "change" or "note". Nothing to say (rope, a potion): no icon and no lines."""
    if not sheet:
        return {"icon": None, "why": "", "lines": []}
    who = name or (sheet.get("name") or "").split()[0] or "They"
    lines, catches, goods = [], [], []
    if item.get("weapon_cat"):
        _weapon(sheet, item, who, lines, catches, goods)
    elif item.get("armor_type") in (1, 2, 3):
        _armor(sheet, item, who, lines, catches, goods)
    elif item.get("armor_type") == 4:
        _shield(sheet, item, who, lines, catches, goods)
    if item.get("attune"):
        _attunement(sheet, item, who, lines, catches, goods)
    _granted(sheet, item, lines)
    if catches:
        return {"icon": "warn", "why": catches[0], "lines": lines}
    return {"icon": "ok" if goods else None, "why": goods[0] if goods else "", "lines": lines}


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
    else:
        ab, m = "Strength", strm
    magic = sum(int(x["value"] or 0) for x in item.get("mods") or [] if x["sub"] == "magic")
    pb = sheet.get("proficiency_bonus") or 2
    hit = m + (pb if proficient else 0) + magic
    parts = f"{ab} {_signed(m)}{why}" + (f", Proficiency {_signed(pb)}" if proficient else "") + (f", magic {_signed(magic)}" if magic else "")
    if item.get("dice"):
        dmg = _with(item["dice"], m + magic)
        two = props.get("Versatile")
        lines.append(("change", f"Attack {_signed(hit)} to hit ({parts}), {dmg} {item.get('damage_type') or ''}".rstrip()
                      + (f"; with two hands {_with(two, m + magic)}." if two else ".")))
    mastery = next((p for p in props if p in MASTERIES), None)
    if mastery:
        has = any(f.get("name") == "Weapon Mastery" for f in sheet.get("features") or [])
        lines.append(("note", f"Its mastery, {mastery}: {who}'s if chosen for Weapon Mastery." if has
                      else f"Its mastery, {mastery}, needs the Weapon Mastery feature: {who} doesn't have it."))


def _ac_parts(sheet):
    return (sheet.get("armor_parts") or {}).get("parts") or []


def _unarmored(sheet) -> str:
    return next((n for n, _ in _ac_parts(sheet) if n.startswith("Unarmored Defense")), "")


def _armor(sheet, item, who, lines, catches, goods):
    trained = ARMOR[item["armor_type"]] in set((sheet.get("proficiencies") or {}).get("armor") or [])
    if trained:
        lines.append(("ok", f"Trained: {ARMOR[item['armor_type']]}."))
        goods.append(f"Trained: {ARMOR[item['armor_type']]}")
    else:
        lines.append(("warn", f"No {ARMOR[item['armor_type']]} training. Wearing it: Disadvantage on every D20 Test that uses "
                              "Strength or Dexterity, and no spellcasting."))
        catches.append(f"Not trained: {ARMOR[item['armor_type']]}")
    dex = _mod(_scores(sheet).get("dexterity", 10))
    add = dex if item["armor_type"] == 1 else min(dex, 2) if item["armor_type"] == 2 else 0
    others = [(n, v) for n, v in _ac_parts(sheet) if not BASE_PART.search(n)]
    now = sheet.get("armor_class") or 0
    new = (item.get("ac") or 0) + add + sum(v for _, v in others)
    ud = _unarmored(sheet)
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
    if item.get("stealth_dis"):
        lines.append(("warn", "Disadvantage on Dexterity (Stealth) checks."))
    if ud:
        lines.append(("note", f"{ud.split(' (')[0]} works only without armor."))


def _shield(sheet, item, who, lines, catches, goods):
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
    if ud and "Wisdom" in ud:  # (a Monk's Unarmored Defense needs no shield; a Barbarian's allows one)
        parts = dict(_ac_parts(sheet))
        lose = parts.get(ud, 0)
        lines.append(("change", f"AC {now} → {now - lose + gain}: {ud} doesn't work with a Shield."))
    else:
        lines.append(("change", f"AC {now} → {now + gain}."))


def _attunement(sheet, item, who, lines, catches, goods):
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


def _granted(sheet, item, lines):
    """What a magic item grants, from D&D Beyond's modifiers: Armor Class, saving throws, an ability score."""
    sc = _scores(sheet)
    for m in item.get("mods") or []:
        v, sub = m["value"], m["sub"] or ""
        if not isinstance(v, int) or sub == "magic":
            continue
        when = " while attuned" if m["attuned"] else ""
        if sub == "armor-class" and m["type"] == "bonus" and not item.get("armor_type"):
            now = sheet.get("armor_class") or 0
            lines.append(("change", f"AC {now} → {now + v}{when}."))
        elif sub == "saving-throws" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to every saving throw{when}."))
        elif sub == "spell-attacks" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to spell attack rolls{when}."))
        elif sub == "spell-save-dc" and m["type"] == "bonus":
            lines.append(("change", f"{_signed(v)} to their spell save DC{when}."))
        elif sub.endswith("-score") and sub[:-6] in ABILITY:
            key, now = sub[:-6], sc.get(sub[:-6], 10)
            new = max(now, v) if m["type"] == "set" else now + v
            if new != now:
                lines.append(("change", f"{ABILITY[key]} {now} → {new}{when}: its checks and saves {_signed(_mod(now))} → {_signed(_mod(new))}."))
            else:
                lines.append(("note", f"{ABILITY[key]} {v}{when}: {_signed(_mod(now))} already, no change."))
