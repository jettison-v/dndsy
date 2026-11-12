"""Show the Math (Brett chose A, B, D and E, Nov 12; docs/mockups/show-the-math/): every number askdnd rolls with can
say how it adds up, so a player new to askdnd can check it without asking. One shape everywhere, a list of rows:

    {"n": 2 | "1d6", "what": "Dexterity modifier (Martial Arts)", "src": "sheet"}

`src` says where the part comes from, most often the D&D Beyond sheet's own numbers (SOURCES). The rows are made once,
on the server, from what askdnd already adds up (app/ddb_sheet.py's parts, the Wild Shape form's, a spell's recipe),
carried on each roll button's plan (`math`), sent with the roll and kept on it (`TableRoll.detail["math"]`), so the roll
card (A) and Table rolls (B) say the same parts, as they were when it was rolled. A list is only kept when it adds up to
the number it explains: a breakdown never disagrees with its total. Check your numbers (E, app/check_numbers.py) lists
them per character."""

import json
import re

SOURCES = {"sheet": "Sheet", "rules": "2024 rules", "dm": "Your DM", "form": "The form", "ddb": "D&D Beyond's data",
           "read": "Its words", "added": "Added"}
# Where a roll plan's dice come from (app/roll_plan.py `sources`), as a part's source
FROM_PLAN = {"correction": "dm", "checked": "rules", "sheet": "sheet", "rule": "rules", "ddb": "ddb", "text": "read"}
DIE = re.compile(r"^\d{1,2}d\d{1,3}$")
MAX_ROWS = 8


def row(what: str, n, src: str = "sheet") -> dict:
    return {"n": n, "what": str(what), "src": src if src in SOURCES else "sheet"}


def _src_of(what: str, src: str) -> str:
    """A part's own words can say it's the form's (Wild Shape: "Dexterity modifier (form)") or kept by the DM's ruling."""
    low = what.lower()
    if "(form)" in low or "form's" in low:
        return "form"
    return src


def rows(parts, src: str = "sheet") -> list[dict]:
    """[(what, amount)] as the sheet reader gives them (app/ddb_sheet.py) into rows; a zero part says nothing."""
    out = []
    for p in parts or []:
        what, n = (p["what"], p["n"]) if isinstance(p, dict) else (p[0], p[1])
        if isinstance(n, str) and (v := _signed_int(n)) is not None:
            n = v  # (a label, "+2")
        if n in (0, "", None):
            continue
        out.append(row(what, n, _src_of(str(what), p.get("src", src) if isinstance(p, dict) else src)))
    return out


def adds_up(rs: list[dict], total) -> bool:
    """The rows' numbers come to `total` (dice rows aside)."""
    try:
        return sum(int(r["n"]) for r in rs if not isinstance(r["n"], str)) == int(total)
    except (TypeError, ValueError):
        return False


def checked(rs: list[dict], total) -> list[dict]:
    """The rows if they add up to the total, else none (a breakdown never disagrees with its number)."""
    return rs if rs and adds_up(rs, total) else []


def _signed_int(text) -> int | None:
    t = str(text or "").strip().replace("−", "-")
    return int(t) if re.fullmatch(r"[+-]?\d+", t) else None


# ------------------------------------------------------------------ an option's numbers (Battle, Search)

def _sheet_attack(sheet: dict, o: dict) -> dict | None:
    from app.roll_plan import UNARMED_ROW

    attacks = sheet.get("attacks") or []
    a = next((a for a in attacks if a.get("key") == o.get("key") or a.get("name") == o.get("name")), None)
    if a is None and UNARMED_ROW.search(f"{o.get('name') or ''} {o.get('meta') or ''}"):
        a = next((a for a in attacks if a.get("key") == "attack:unarmed"), None)  # (Flurry of Blows: the Unarmed Strike's)
    return a


def _caster(sheet: dict, o: dict) -> list[dict]:
    """The spellcasting blocks a spell can use: its own class's first."""
    blocks = sheet.get("spellcasting") or []
    sp = next((x for x in sheet.get("spells") or [] if x.get("key") == o.get("key") or x.get("name") == o.get("name")), None)
    mine = set((sp or {}).get("sources") or [])
    return sorted(blocks, key=lambda b: b.get("class") not in mine)


def _ability_dc(sheet: dict, ability: str) -> list[dict]:
    """A DC from an ability (a Breath Weapon's {dc:constitution}): 8 + its modifier + the Proficiency Bonus."""
    ab = next((a for a in sheet.get("abilities") or [] if a.get("key") == ability.lower() or a.get("name", "").lower() == ability.lower()), None)
    if not ab:
        return []
    return [row("Base", 8), row("Proficiency Bonus", sheet.get("proficiency_bonus") or 2), row(f"{ab['name']} modifier", ab["modifier"])]


def option_math(sheet: dict, o: dict, plan: dict | None) -> dict:
    """How an option's numbers add up: its to-hit (`bonus`), its save's DC (`dc`) and a weapon's damage (`dmg`, the die
    with what it is and the flat parts), each only when it adds up. `dice` says where the plan's dice come from."""
    out: dict = {}
    if o.get("math"):  # (a Wild Shape form's attack says its own: app/wild_shape.py)
        out.update(o["math"])
    plan = plan or {}
    srcs = plan.get("sources") or {}
    bonus = (plan.get("attack") or {}).get("bonus")
    if bonus is None:
        bonus = _signed_int(o.get("hit"))
    if bonus is not None and "bonus" not in out:
        a = _sheet_attack(sheet, o) if o.get("kind") != "spell" else None
        got = checked(rows((a or {}).get("hit_parts")), bonus)
        if not got and (o.get("kind") == "spell" or srcs.get("attack") == "sheet"):
            for b in _caster(sheet, o):
                if got := checked(rows(b.get("attack_parts")), bonus):
                    break
        out["bonus"] = got or [row("The sheet's number for it", bonus, "sheet")]
        if a and a.get("damage_parts"):
            dmg = rows(a["damage_parts"])
            dice = [r for r in dmg if isinstance(r["n"], str)]
            for r in dice:
                r["src"] = "rules" if r["what"].startswith("Martial Arts") else "sheet"
            out["dmg"] = dmg
    save = plan.get("save") or {}
    if save.get("dc") and "dc" not in out:
        got = []
        recipe_dc = next((e.get("dc") for e in ((o.get("recipe") or {}).get("events") or []) if isinstance(e.get("dc"), str)), "")
        if m := re.fullmatch(r"\{dc:(\w+)\}", recipe_dc or ""):
            got = checked(_ability_dc(sheet, m.group(1)), save["dc"])
        if not got:
            for b in _caster(sheet, o):
                if got := checked(rows(b.get("dc_parts")), save["dc"]):
                    break
        out["dc"] = got or [row("Its own DC" if srcs.get("save") != "sheet" else "The sheet's number for it", save["dc"],
                                FROM_PLAN.get(srcs.get("save") or "sheet", "sheet"))]
    dice_src = srcs.get("damage") or srcs.get("heal")
    if dice_src:
        out["dice"] = FROM_PLAN.get(dice_src, "sheet")
    return out


# ------------------------------------------------------------------ kept with a roll (sent by the card, checked here)

def _clean_rows(raw, limit: int = MAX_ROWS) -> list[dict]:
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        n = r.get("n")
        if isinstance(n, bool) or not (isinstance(n, int) and abs(n) <= 99 or isinstance(n, str) and DIE.match(n)):
            continue
        what = " ".join(str(r.get("what") or "").split())[:70]
        if what:
            out.append(row(what, n, str(r.get("src") or "")))
    return out[:limit]


def clean(raw: str, modifier: int | None) -> dict:
    """The math the roll card sends with a roll, checked and kept short (TableRoll.detail["math"]): the to-hit or
    check's parts only if they come to the roll's own bonus; the damage parts and the dice's source as they are (the
    damage is rolled later, and checked then); `why`, a line about the dice (a spell cast above its level)."""
    try:
        m = json.loads(raw) if raw else None
    except ValueError:
        return {}
    if not isinstance(m, dict):
        return {}
    out = {}
    if modifier is not None and (b := _clean_rows(m.get("bonus"))) and adds_up(b, modifier):
        out["bonus"] = b
    if d := _clean_rows(m.get("dmg")):
        out["dmg"] = d
    if (src := m.get("dice")) in SOURCES:
        out["dice"] = src
    if why := " ".join(str(m.get("why") or "").split())[:160]:
        out["why"] = why
    return out


# ------------------------------------------------------------------ a roll as it was rolled (the card's result, Table rolls)

def _dice_row(formula: str, dice: list, total: int, what: str = "", src: str = "") -> dict:
    """A die rolled: "1d6, Martial Arts die (Monk 2)"; several say each ("2d10 (3, 9) radiant")."""
    shown = formula + (f" ({', '.join(str(d) for d in dice)})" if dice and len(dice) > 1 else "")
    what = what.strip()
    if not what or what == formula:
        return {"n": total, "what": shown, "src": src}
    kind = what.islower() and " " not in what  # (a damage type, "radiant": "2d10 radiant"; else "1d6, Martial Arts die")
    return {"n": total, "what": f"{shown} {what}" if kind else f"{shown}, {what}", "src": src}


def _extras(extras: list) -> list[dict]:
    return [{"n": x["total"], "what": x["label"] + (f" ({x['formula']})" if x.get("dice") else ""), "src": "added"} for x in extras or []]


def d20_lines(r, math: dict, bonus=None) -> dict | None:
    """A d20 roll's parts: the die, the bonus's parts (or the bonus), what was added, and the total."""
    if r.parts and len(r.parts) > 1:
        return None  # (several rays: each shows its own line already)
    kept = r.kept if r.kept is not None else (r.dice[0] if r.dice else None)
    if kept is None:
        return None
    many = len(r.dice) > 1
    mode = {"adv": "Advantage", "dis": "Disadvantage"}.get(r.mode, "")
    die = {"n": kept, "what": "the d20" + (f" ({mode}: {' and '.join(str(d) for d in r.dice)}, the {'higher' if r.mode == 'adv' else 'lower'})"
                                           if many and mode else ""), "src": ""}
    parts = (math or {}).get("bonus") or []
    out = [die] + (parts if parts and adds_up(parts, r.modifier) else [{"n": r.modifier, "what": "Bonus", "src": ""}] if r.modifier else [])
    out += _extras(r.extras)
    total = r.total
    if bonus is not None:
        out += [{"n": bonus.total, "what": bonus.label + (f" ({bonus.formula})" if bonus.dice else ""), "src": "added"}]
        total += bonus.total
    return {"rows": out, "total": total}


def dice_lines(r, math: dict) -> dict | None:
    """A damage, healing or dice roll's parts: each die rolled with what it is, the flat parts, what was added, and the
    total; a critical's doubled dice say so; `why` says how a spell's dice grew."""
    math = math or {}
    src = math.get("dice") or ""
    named = [x for x in math.get("dmg") or [] if isinstance(x["n"], str)]
    flats = [x for x in math.get("dmg") or [] if not isinstance(x["n"], str)]
    out = []
    if r.parts:
        for p in r.parts:
            if p.get("dice"):
                out.append(_dice_row(p["formula"], p["dice"], p["total"], (p.get("label") + " " if p.get("label") else "") + (p.get("kind") or ""), src))
            elif p.get("total"):
                out.append({"n": p["total"], "what": (p.get("kind") or "Bonus").replace("spellcasting modifier", "Spellcasting modifier"),
                            "src": "sheet" if "modifier" in (p.get("kind") or "") else src})
    else:
        dice_total = sum(r.dice or [])
        if r.dice:
            base = re.split(r"[+\-]", r.formula or "")[0]
            what = (named[0]["what"] if named else "") + (" · doubled for a critical" if r.crit else "")
            out.append(_dice_row(base, r.dice, dice_total, what, named[0]["src"] if named else src))
        mod = r.modifier or 0
        if mod or not r.dice:
            out += flats if flats and adds_up(flats, mod) else [{"n": mod, "what": "Bonus" if r.dice else "Flat damage", "src": ""}]
    out += _extras(r.extras)
    if not out:
        return None
    return {"rows": out, "total": r.total, **({"why": math["why"]} if math.get("why") else {})}
