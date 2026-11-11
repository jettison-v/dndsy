"""The roll engine's hand-written rules (app/data/rules/<book>.json; the Roll Data Review, Nov 10,
docs/artifacts/roll-data-review.html), read the one way the engine needs them.

Each book file holds entries (a spell, feature, feat, item…) and the book's named `scales` (Rage damage, the Martial
Arts die, Sneak Attack's dice…). An entry has what it rolls when used (`rolls`), what it does to another roll (`adds`:
`when`, `to`, `with`, `amount` or `op`, `once`, `cost`…) and, for a class feature or feat, when a character has it
(`class` and `level`, `sub`, `needs`, `group`: the highest of a group only). scripts/roll_audit.py compiles the `rolls`
into app/data/roll_recipes.json; everything about `adds` is read from here.

Numbers come from the sheet through one set of tokens (`fill`): {level:Class}, {half:Class}, {mod:ability},
{dc:ability}, {pb}, a book's named scale ({rage}, N{martial_arts}…), and the older ones class_rules' words use
({lv}, {half}, {ma}, {mod_wis}, {dc_wis}), each relative to the entry's own class.
"""

import json
import re
from functools import cache
from pathlib import Path

BOOKS = Path(__file__).parent / "data" / "rules"
ABILITY = {"str": "strength", "dex": "dexterity", "con": "constitution", "int": "intelligence", "wis": "wisdom", "cha": "charisma"}


@cache
def books() -> dict:
    return {f.stem: json.loads(f.read_text()) for f in sorted(BOOKS.glob("*.json"))}


@cache
def entries() -> tuple[dict, ...]:
    return tuple(e | {"_book": b, "_norm": _norm(e["name"])} for b, data in books().items() for e in data["entries"])


@cache
def scales() -> dict:
    out = {}
    for data in books().values():
        out |= data.get("scales") or {}
    return out


def _norm(name: str | None) -> str:
    """'Oath of Conquest (XGtE)' -> 'oath of conquest'; curly quotes straightened (class_rules' own matching)."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\(.*\)$", "", (name or "").replace("’", "'"))).strip().lower()


def _levels(sheet: dict) -> dict:
    return {c.get("name"): c.get("level") or 0 for c in sheet.get("classes") or []}


def _scale(name: str, sheet: dict, n: str = "") -> str | None:
    s = scales().get(name)
    if not s:
        return None
    lv = sum(_levels(sheet).values()) if s["by"] == "character" else _levels(sheet).get(s["by"], 0)
    v = next((x for at, x in sorted(((int(a), x) for a, x in s["at"].items()), reverse=True) if lv >= at), 0)
    if not v:
        return ""
    return f"{n or 1}d{v}" if s.get("die") else str(v)


def fill(text: str, sheet: dict | None, cls: str | None = None) -> str:
    """An entry's {tokens} from the sheet (see the module's words). `cls`: the entry's own class, for {lv}, {half}."""
    sheet = sheet or {}
    lv = _levels(sheet)
    mods = {}
    for a in sheet.get("abilities") or []:  # (by its key, "dexterity", or its short name, "dex")
        short = str(a.get("short") or "").lower()[:3]
        full = a.get("key") or ABILITY.get(short)
        for k in (full, short or next((s for s, f in ABILITY.items() if f == full), None)):
            if k:
                mods[k] = a.get("modifier") or 0
    pb = sheet.get("proficiency_bonus") or 2
    own = lv.get(cls, 0) if cls else sum(lv.values())

    def value(m):
        n, k = m.group(1), m.group(2)
        if (s := _scale(k, sheet, n)) is not None:
            return s
        head, _, arg = k.partition(":")
        if head == "level":
            out = str(lv.get(arg, 0))
        elif head == "half":
            out = str(lv.get(arg, 0) // 2)
        elif head in ("mod", "dc") or k.startswith(("mod_", "dc_")):
            ab = arg or k.split("_", 1)[1]
            m_ = mods.get(ab, mods.get(ABILITY.get(ab, ab), 0))
            out = str(8 + m_ + pb) if head == "dc" or k.startswith("dc_") else (f"{m_:+d}" if k.startswith("mod_") else str(m_))
        elif k == "pb":
            out = str(pb)
        elif k == "lv":
            out = str(own)
        elif k == "half":
            out = str(own // 2)
        elif k == "ma":
            return _scale("martial_arts", sheet) or m.group(0)
        else:
            return m.group(0)
        return n + out
    out = re.sub(r"(\d*)\{([^}]+)\}", value, text or "").replace("+-", "-").replace("++", "+")
    return re.sub(r"\+0\b(?!d)", "", out)


def _has(sheet: dict, text: str) -> bool:
    names = [x.get("name") or "" for x in (sheet.get("features") or []) + (sheet.get("actions") or [])]
    return any(_norm(text) in _norm(n) for n in names)


def has_names(sheet: dict) -> set[str]:
    """What the character has by name: features, actions, spells, and an item marked with its kind ("<item>: <kind>")."""
    names = {a.get("name") for a in sheet.get("actions") or []} | {s.get("name") for s in sheet.get("spells") or []}
    names |= {f.get("name") for f in sheet.get("features") or [] if isinstance(f, dict)}
    choices = sheet.get("_item_choices") or {}
    for it in sheet.get("inventory") or []:
        if (kind := choices.get(str(it.get("key", "")).split(":", 1)[-1])) and it.get("equipped"):
            names.add(f"{(it.get('base_name') or it.get('name') or '').split(' (')[0]}: {kind}")
    return {_norm(n) for n in names if n}


def active(sheet: dict | None) -> list[dict]:
    """The entries that apply to this character: a class feature at its level (its subclass's, what it `needs`), a feat
    it has, or anything else it has by name (a spell, a feature D&D Beyond lists, a marked item); the highest of a group."""
    sheet = sheet or {}
    lv = _levels(sheet)
    subs = {c.get("name"): _norm(c.get("subclass")) for c in sheet.get("classes") or []}
    feats = {_norm(f["name"]) for f in sheet.get("features") or [] if f.get("source") == "Feat"}
    names = has_names(sheet)
    carried = [_norm(n) for it in sheet.get("inventory") or [] for n in (it.get("name"), it.get("base_name")) if n]
    out = []
    for e in entries():
        if (e["kind"] == "item" and e.get("adds") and not any(": " in a["name"] for a in e["adds"])
                and any(c.startswith(e["_norm"]) for c in carried)):
            pass  # (a magic weapon's own adds, when the character carries one: Flame Tongue; one that needs its kind marked,
            #      "Dragon-Touched Focus: Chromatic", goes by that name below)
        elif e["kind"] == "feat":
            if e["_norm"] not in feats and not (e.get("needs") and _norm(e["needs"]) in feats):
                continue
        elif e.get("class"):
            if lv.get(e["class"], 0) < e.get("level", 1) or (e.get("sub") and subs.get(e["class"]) != _norm(e["sub"])):
                continue
            if e.get("needs") and not _has(sheet, e["needs"]):
                continue
        elif e["_norm"] not in names and not any(_norm(a["name"]) in names for a in e.get("adds") or []):
            continue
        out.append(e)
    top = {}
    for e in out:
        if e.get("group") and e.get("level", 0) >= top.get(e["group"], 0):
            top[e["group"]] = e.get("level", 0)
    return [e for e in out if not e.get("group") or e.get("level", 0) == top[e["group"]]]


_ADDS: dict = {}  # (a page asks once per Battle option: what it's worked out from -> the adds)


def _inputs(sheet: dict) -> tuple:
    """Everything `_adds` reads from a sheet, and nothing else: the cache's key, so two sheets that agree on all of it
    share one answer and any change to it is worked out again (the outside review's R8, Nov 10; tests/test_rules_books.py
    changes each one). A new field `_adds` (or `active`, `fill`) reads goes here too."""
    def names(k: str) -> tuple:
        return tuple(x.get("name") or "" for x in sheet.get(k) or [] if isinstance(x, dict))

    return (tuple((c.get("name"), c.get("level"), c.get("subclass")) for c in sheet.get("classes") or []),
            names("features"), tuple(x.get("source") for x in sheet.get("features") or [] if isinstance(x, dict)), names("actions"), names("spells"),
            tuple((x.get("name"), x.get("base_name"), x.get("key"), x.get("equipped")) for x in sheet.get("inventory") or [] if isinstance(x, dict)),
            tuple(sorted((sheet.get("_item_choices") or {}).items())), sheet.get("proficiency_bonus"),
            tuple((a.get("key"), a.get("short"), a.get("modifier")) for a in sheet.get("abilities") or []))


def adds(sheet: dict | None) -> list[dict]:
    """What this character can do to a roll, from every entry that applies: each add with its numbers filled in and
    where it's from (`source`: a subclass, a class, "Feat", or the entry's own name). Worked out once for what the sheet
    says (a Battle asks for each of its options), again when its classes, things, marks or numbers change."""
    sheet = sheet or {}
    key = _inputs(sheet)
    if (hit := _ADDS.get(key)) is not None:
        return [dict(a) for a in hit]
    out = _adds(sheet)
    if len(_ADDS) > 256:
        _ADDS.clear()
    _ADDS[key] = out
    return [dict(a) for a in out]


def _adds(sheet: dict) -> list[dict]:
    out = []
    for e in active(sheet):
        for a in e.get("adds") or []:
            filled = {k: fill(v, sheet, e.get("class")) if isinstance(v, str) and k in ("amount", "reduces", "says", "effect", "trigger", "dc") else v
                      for k, v in a.items()}
            out.append(filled | {"source": e.get("sub") or e.get("class") or ("Feat" if e["kind"] == "feat" else e["name"]),
                                 "_kind": e["kind"], **({"item": e["name"]} if e["kind"] == "item" else {})})
    return out


def entry(kind: str, name: str) -> dict | None:
    want = _norm(name)
    return next((e for e in entries() if e["kind"] == kind and e["_norm"] == want), None)
