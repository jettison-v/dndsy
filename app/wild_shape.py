"""Wild Shape for druids (2024 Player's Handbook): which Beasts a druid can learn,
and what a form looks like with the druid's own stats carried over.

The Beast list is app/data/beasts_2024.json (SRD 5.2 stat blocks, CC-BY-4.0, with
pictures linked from D&D Beyond; refresh with scripts/wild_shape_beasts.py). Forms
the druid already knows come from D&D Beyond (sheet["creatures"]); their stat block
from the list is used when the names match, D&D Beyond's otherwise.

The rules applied are the Druid's Wild Shape feature and, for Circle of the Moon,
Circle Forms and Improved Circle Forms, as their text reads on the sheet. They
inform; the DM makes every ruling (e.g. which other class features work in a form).
"""

import json
import re
from functools import cache
from pathlib import Path

from app import character_views as views

DATA = Path(__file__).parent / "data" / "beasts_2024.json"
ABILITIES = (("str", "Strength", "Str"), ("dex", "Dexterity", "Dex"), ("con", "Constitution", "Con"),
             ("int", "Intelligence", "Int"), ("wis", "Wisdom", "Wis"), ("cha", "Charisma", "Cha"))
KEPT = ("int", "wis", "cha")  # Wild Shape keeps your Intelligence, Wisdom and Charisma
SKILL_ABILITY = {"Acrobatics": "dex", "Animal Handling": "wis", "Arcana": "int", "Athletics": "str", "Deception": "cha",
                 "History": "int", "Insight": "wis", "Intimidation": "cha", "Investigation": "int", "Medicine": "wis",
                 "Nature": "int", "Perception": "wis", "Performance": "cha", "Persuasion": "cha", "Religion": "int",
                 "Sleight of Hand": "dex", "Stealth": "dex", "Survival": "wis"}
CR_LABELS = {0.0: "0", 0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}
MOON_SPELLS = ((3, ("Cure Wounds", "Moonbeam", "Starry Wisp")), (5, ("Conjure Animals",)), (7, ("Fount of Moonlight",)), (9, ("Mass Cure Wounds",)))
COSTLY = re.compile(r"worth|\bGP\b|consume", re.I)  # Beast Spells: no costly or consumed Material components
ATTACK = re.compile(r"(Melee or Ranged|Melee|Ranged) Attack Roll:\s*([+−-]\d+)")
DAMAGE = re.compile(r"(\d+)(?: \((\d+d\d+(?:\s*[+−-]\s*\d+)?)\))? (\w+) damage")
SAVE = re.compile(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) Saving Throw:\s*DC (\d+)")


def _mod(score: int) -> int:
    return (score - 10) // 2


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{-n}"


def cr_label(cr: float) -> str:
    return CR_LABELS.get(cr, str(int(cr)))


@cache
def _catalog() -> tuple[dict, ...]:
    return tuple(json.loads(DATA.read_text(encoding="utf-8"))["beasts"])


def credit() -> str:
    return json.loads(DATA.read_text(encoding="utf-8"))["credit"]


def catalog_beast(name: str) -> dict | None:
    return next((b for b in _catalog() if b["name"].lower() == name.lower()), None)


# ------------------------------------------------------------------ the druid


def druid(sheet: dict | None) -> dict | None:
    """What this character's Wild Shape allows, or None if they don't have it yet."""
    if not sheet:
        return None
    k = next((c for c in sheet.get("classes") or [] if c["name"] == "Druid"), None)
    level = k["level"] if k else 0
    if level < 2:
        return None
    feats = {f["name"] for f in sheet.get("features") or []}
    moon = "Circle Forms" in feats or "Moon" in (k.get("subclass") or "")
    known, max_cr, fly = (8, 1.0, True) if level >= 8 else (6, 0.5, False) if level >= 4 else (4, 0.25, False)
    table_cr = max_cr
    if moon:
        max_cr = max(max_cr, float(level // 3))
    ws = next((a for a in sheet.get("actions") or [] if a["name"] == "Wild Shape"), None)
    names = " | ".join(feats | {a["name"] for a in sheet.get("actions") or []})
    fury = "Primal Strike" if "Primal Strike" in names else "Potent Spellcasting" if "Potent Spellcasting" in names else ""
    return {
        "level": level, "moon": moon, "circle": k.get("subclass") or "", "known": known, "max_cr": max_cr,
        "max_cr_label": cr_label(max_cr), "table_cr": table_cr, "fly": fly, "uses": ws["uses"] if ws else None,
        "hours": level // 2, "temp_hp": level * (3 if moon else 1),
        "lunar_radiance": "Improved Circle Forms" in feats, "toughness": "Improved Circle Forms" in feats,
        "lunar_form": moon and level >= 14,
        # Circle of the Moon Spells can be cast in a form; Beast Spells (level 18) opens up the rest
        "moon_spells": [n for lvl, ns in MOON_SPELLS for n in ns if moon and level >= lvl],
        "beast_spells": level >= 18,
        # Elemental Fury (level 7): which option, if the sheet says ("" = not chosen yet or not shown)
        "elemental_fury": level >= 7, "fury": fury, "primal_strike": ("2d8" if level >= 15 else "1d8") if level >= 7 else "",
    }


def other_uses(sheet: dict) -> list[dict]:
    """Features that spend Wild Shape on something else (Wild Companion, Wild Resurgence,
    Land's Aid, Starry Form…), read from the sheet so every Circle is covered."""
    out, seen = [], set()
    for f in list(sheet.get("actions") or []) + list(sheet.get("features") or []):
        text = f.get("text") or ""
        if f["name"].startswith("Wild Shape") or any(n.startswith(f["name"]) for n in seen) or not re.search(r"uses? of (your )?Wild Shape", text):
            continue
        seen.add(f["name"])
        out.append({"name": f["name"], "key": f.get("key", ""), "summary": f.get("summary") or _clip(text, 160)})
    return out


def why_not(d: dict, beast: dict) -> str:
    """Why a Beast can't be learned right now ("" if it can)."""
    if beast["cr"] > d["max_cr"]:
        return f"CR {beast['cr_label']} is above your max of {d['max_cr_label']}"
    if beast.get("speed", {}).get("fly") and not d["fly"]:
        return "Has a Fly Speed (Druid level 8)"
    return ""


def _speed_text(speed: dict) -> str:
    return ", ".join(f"{v} ft." if k == "walk" else f"{k} {v} ft." for k, v in speed.items())


def _first_attack(beast: dict) -> str:
    """One line for the list: what the form mostly does on its turn."""
    acts = beast.get("actions") or []
    multi = next((a for a in acts if a["name"].startswith("Multiattack")), None)
    if multi:
        return multi["text"].split(". ")[0].rstrip(".")
    for a in acts:
        m = DAMAGE.search(a["text"])
        if m:
            return f"{a['name']}: {m.group(1)}" + (f" ({m.group(2)})" if m.group(2) else "") + f" {m.group(3)}"
    return acts[0]["name"] if acts else ""


def forms(sheet: dict, fav: set[str]) -> list[dict]:
    """Every Beast the druid could learn now, plus anything they know or shortlisted."""
    d = druid(sheet)
    if not d:
        return []
    known = {c["kind"].lower(): c for c in sheet.get("creatures") or [] if c.get("group") == "Wild Shape form"}
    rows, seen = [], set()
    for b in list(_catalog()) + [c["block"] for c in known.values() if c.get("block") and not catalog_beast(c["kind"])]:
        if b["name"].lower() in seen:
            continue
        seen.add(b["name"].lower())
        key = f"form:{b['name']}"
        is_known = b["name"].lower() in known
        reason = why_not(d, b)
        if reason and not is_known and key not in fav:
            continue
        rows.append({
            "key": key, "name": b["name"], "cr": b["cr"], "cr_label": b["cr_label"], "size": b.get("size", ""),
            "ac": b["ac"], "speed": _speed_text(b.get("speed") or {}), "moves": sorted(k for k in b.get("speed") or {} if k != "walk"),
            "image": b.get("image", ""), "known": is_known, "why_not": reason, "summary": _first_attack(b),
            "card": card(sheet, b),
        })
    rows.sort(key=lambda r: (not r["known"], r["cr"], r["name"]))
    return rows


def beast_for(sheet: dict, name: str) -> dict | None:
    """The stat block for a form by name: the Beast list first, then D&D Beyond's known forms."""
    b = catalog_beast(name)
    if b:
        return b
    c = next((c for c in sheet.get("creatures") or [] if c["kind"].lower() == name.lower() and c.get("block")), None)
    return c["block"] if c else None


def label_for(ref: str) -> str:
    """Easy to forget text for a form that isn't on the sheet."""
    name = ref.removeprefix("form:")
    b = catalog_beast(name)
    return f"{b['name']} (Wild Shape, CR {b['cr_label']}): {_first_attack(b)}" if b else ""


# ------------------------------------------------------------------ in a form


def _entry(e: dict, cost: str, d: dict) -> dict:
    """A stat block action as a Battle option."""
    text = e["text"]
    att, dmg, save = ATTACK.search(text), _damages(text), SAVE.search(text)
    reach = re.search(r"(reach \d+ ft\.|range [\d/]+ ft\.)", text)
    meta = []
    if reach:
        meta.append(reach.group(1).rstrip("."))
    if dmg:
        kinds = " + ".join(f"{a} ({b}) {c}" if b else f"{a} {c}" for a, b, c in dmg)
        meta.append(kinds + (" (or Radiant)" if d.get("lunar_radiance") and att else ""))
    if att and d.get("lunar_form"):
        meta.append("+2d10 Radiant once per turn")
    if att and d.get("fury") == "Primal Strike":
        meta.append(f"+{d['primal_strike']} Cold/Fire/Lightning/Thunder once per turn")
    hit = att.group(2).replace("-", "−") if att else (f"DC {save.group(2)} {save.group(1)[:3]}" if save else "")
    return {"key": f"beast:{e['name']}", "name": e["name"], "cost": cost, "hit": hit, "meta": " · ".join(meta) or _clip(text),
            "text": text, "tags": ["Form"], "uses": None, "spends": [], "starred": False, "source": "form"}


def _clip(text: str, n: int = 110) -> str:
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= n else first[: n - 1].rsplit(" ", 1)[0] + "…"


NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
CONDITIONS = ("Grappled", "Restrained", "Prone", "Poisoned", "Blinded", "Frightened", "Stunned", "Paralyzed", "Incapacitated", "Charmed", "Deafened")


def _damages(text: str) -> list[tuple[str, str, str]]:
    """Each "9 (1d8 + 5) Slashing damage" in an attack, leaving out alternatives
    ("…, or 6 (2d4) Piercing damage if the swarm is Bloodied")."""
    return [m.groups() for m in DAMAGE.finditer(text) if not text[max(0, m.start() - 3):m.start()].endswith("or ")]


def _hit_sentence(text: str) -> tuple[str, str]:
    """The sentence with an attack's normal damage, and the rest (extra damage that
    needs something more, like the Rhinoceros's charge, is in the rest)."""
    m = DAMAGE.search(text)
    if not m:
        return text, ""
    end = re.search(r"\.(\s|$)", text[m.end():])
    cut = m.end() + (end.end() if end else len(text) - m.end())
    return text[:cut], text[cut:]


def _avg(text: str) -> int:
    """Average damage of one hit, all damage types added up (not conditional extras)."""
    return sum(int(a) for a, _, _ in _damages(_hit_sentence(text)[0]))


def turn_attacks(beast: dict) -> dict:
    """What the form does with its Attack action: Multiattack spelled out, average damage
    if everything hits, and the best attack bonus."""
    acts = [a for a in beast.get("actions") or [] if not a["name"].startswith("Multiattack")]
    attacks = [a for a in acts if ATTACK.search(a["text"])]
    best = max(attacks, key=lambda a: _avg(a["text"]), default=None)
    multi = next((a for a in beast.get("actions") or [] if a["name"].startswith("Multiattack")), None)
    parts = []
    if multi:
        first = re.split(r"(?<=\.)\s", multi["text"], maxsplit=1)[0]
        for n, name in re.findall(r"\b(one|two|three|four|five) ([A-Z][\w' -]*?) attacks?\b", first):
            a = next((x for x in acts if x["name"].lower().startswith(name.lower())), None)
            if a:
                parts.append((NUMBERS[n], a))
        m = re.search(r"\bmakes (one|two|three|four|five) attacks\b", first)
        if not parts and m and best:
            parts.append((NUMBERS[m.group(1)], best))
    if not parts and best:
        parts.append((1, best))

    def one(a):
        base, rest = _hit_sentence(a["text"])
        att, dmg, more = ATTACK.search(a["text"]), _damages(base), _damages(rest)
        hit = att.group(2).replace("-", "−") if att else ""
        dmg_text = " + ".join(f"{x} {k}" for x, _, k in dmg) + "".join(f"; +{x} {k} if…" for x, _, k in more)
        return f"{a['name']} ({hit}{', ' + dmg_text if dmg_text else ''})"

    return {
        "text": ", ".join(f"{n} × {one(a)}" if n > 1 else one(a) for n, a in parts),
        "per_turn": sum(n * _avg(a["text"]) for n, a in parts),
        "hit": (ATTACK.search(best["text"]).group(2).replace("-", "−") if best else ""),
        "hit_value": int(ATTACK.search(best["text"]).group(2).replace("−", "-")) if best else -99,
    }


def card(sheet: dict, beast: dict) -> dict:
    """Everything the Wild Shape list shows for one form, with this druid's numbers."""
    f = shaped(sheet, beast, lite=True)
    d = f["druid"]
    t = turn_attacks(beast)
    extra = []
    if d.get("lunar_form"):
        extra.append("+2d10 Radiant once per turn")
    if d.get("fury") == "Primal Strike":
        extra.append(f"+{d['primal_strike']} elemental once per turn")
    texts = " ".join(e["text"] for k in ("actions", "bonus_actions", "reactions") for e in beast.get(k) or [])
    effects = [c for c in CONDITIONS if re.search(rf"\b{c}\b", texts)]
    saves = {s["key"]: s for s in f["saves"]}
    skills = [s for s in f["skills"] if s["name"] in ("Perception", "Stealth", "Athletics", "Acrobatics", "Survival")]
    speed = beast.get("speed") or {}
    return {
        "ac": f["ac"], "ac_moon": d.get("moon") and f["ac"] > beast["ac"], "temp_hp": f["temp_hp"],
        "attack": t["text"], "hit": t["hit"], "hit_value": t["hit_value"], "per_turn": t["per_turn"], "radiant": d.get("lunar_radiance", False), "extra": extra,
        "speed": _speed_text(speed), "fastest": max(speed.values(), default=0), "senses": beast.get("senses", ""),
        "resist": ", ".join(x for x in (beast.get("resist"), beast.get("immune")) if x),
        "saves": [saves[k] for k in ("str", "dex", "con")], "skills": skills,
        "traits": [x["name"] for x in beast.get("traits") or []],
        "bonus": [x["name"] for x in beast.get("bonus_actions") or []], "reactions": [x["name"] for x in beast.get("reactions") or []],
        "effects": effects,
    }


def shaped(sheet: dict, beast: dict, lite: bool = False) -> dict:
    """The druid in this form: the Beast's stat block with what Wild Shape keeps
    (Hit Points, Int/Wis/Cha, proficiencies, class features) and Circle of the Moon's
    changes. Each number says where it comes from."""
    d = druid(sheet) or {"level": 0, "moon": False, "temp_hp": 0, "lunar_radiance": False, "toughness": False, "uses": None, "hours": 0}
    pb = sheet.get("proficiency_bonus") or 2
    mine = {a["key"][:3]: a["score"] for a in sheet.get("abilities") or []}
    scores = {k: (mine.get(k, 10) if k in KEPT else (beast.get("abilities") or {}).get(k, 10)) for k, _, _ in ABILITIES}
    wis = _mod(scores["wis"])

    abilities = [{"key": k, "short": short, "score": scores[k], "label": _signed(_mod(scores[k])), "from": "yours" if k in KEPT else "form"}
                 for k, _, short in ABILITIES]

    my_saves = {s["short"].lower(): s for s in sheet.get("saves") or []}
    saves = []
    for k, name, short in ABILITIES:
        prof = bool((my_saves.get(k) or {}).get("proficient"))
        parts = [(f"{short} modifier ({'yours' if k in KEPT else 'form'})", _mod(scores[k]))]
        if prof:
            parts.append(("Your Proficiency Bonus", pb))
        if k == "con" and d["toughness"]:
            parts.append(("Increased Toughness (Wisdom modifier)", wis))
        yours = sum(v for _, v in parts)
        stat = (beast.get("saves") or {}).get(k)
        use_form = stat is not None and stat > yours
        saves.append({"key": k, "short": short, "bonus": stat if use_form else yours, "label": _signed(stat if use_form else yours),
                      "proficient": prof, "from": "form's stat block (higher)" if use_form else " + ".join(f"{n} {_signed(v)}" for n, v in parts)})

    my_skills = {s["name"]: s for s in sheet.get("skills") or []}
    skills = []
    for name, ab in SKILL_ABILITY.items():
        level = (my_skills.get(name) or {}).get("proficiency", "")
        prof = pb * 2 if level == "expertise" else pb if level == "proficient" else 0
        yours = _mod(scores[ab]) + prof
        stat = (beast.get("skills") or {}).get(name)
        if not prof and stat is None:
            continue
        use_form = stat is not None and stat > yours
        skills.append({"name": name, "bonus": stat if use_form else yours, "label": _signed(stat if use_form else yours),
                       "from": "form" if use_form else ("your expertise" if level == "expertise" else "your proficiency")})
    perception = next((s["bonus"] for s in skills if s["name"] == "Perception"), _mod(scores["wis"]))

    ac_parts = [(f"The {beast['name']}'s AC" + (f" ({beast['ac_note']})" if beast.get("ac_note") else ""), beast["ac"])]
    ac = beast["ac"]
    if d["moon"]:
        moon_ac = 13 + wis
        ac_parts.append((f"Circle Forms: 13 + your Wisdom modifier ({_signed(wis)}) = {moon_ac}", moon_ac))
        ac = max(ac, moon_ac)

    hp = sheet.get("hit_points") or {}
    cols = {"Action": [], "Bonus action": [], "Reaction": []}
    for e in beast.get("actions") or []:
        cols["Action"].append(_entry(e, "Action", d))
    for e in beast.get("bonus_actions") or []:
        cols["Bonus action"].append(_entry(e, "Bonus action", d))
    for e in beast.get("reactions") or []:
        cols["Reaction"].append(_entry(e, "Reaction", d))
    cols["Bonus action"].append({"key": "wild-shape:leave", "name": "Leave the form", "cost": "Bonus action", "hit": "", "tags": [],
                                 "meta": "Back to your normal form; also if you're Incapacitated or die", "uses": None, "spends": [],
                                 "starred": False, "source": "rule"})
    if d["uses"]:
        cols["Bonus action"].append({"key": "wild-shape:again", "name": "Wild Shape into another known form", "cost": "Bonus action",
                                     "hit": "", "tags": [], "meta": "Uses Wild Shape again", "uses": d["uses"], "spends": [],
                                     "starred": False, "source": "rule"})
    # Spells you can still cast: Circle of the Moon Spells, or (Beast Spells, level 18) any
    # spell without a costly or consumed Material component
    castable = []
    options = [] if lite else views.options(sheet)  # lite: the form's own numbers only (the list of forms)
    for o in options:
        if o["kind"] != "spell" or o["cost"] not in cols:
            continue
        sp = next((x for x in sheet.get("spells") or [] if x["key"] == o["key"]), {})
        if o["name"] in d.get("moon_spells", []):
            tag = "Circle spell"
        elif d.get("beast_spells") and not COSTLY.search(sp.get("material") or ""):
            tag = "Beast Spells"
        else:
            continue
        castable.append(o["name"])
        cols[o["cost"]].append({**o, "tags": [tag] + o["tags"], "source": "spell", "starred": False})
    # Class features and feats you keep (no weapons or items; nothing that casts a spell unless you can cast in a form)
    for o in options:
        if o["kind"] != "feature" or o["cost"] not in cols or o["name"].startswith(("Wild Shape", "Unarmed Strike")):
            continue
        if not d.get("beast_spells") and ("Spell" in o["name"] or o["name"].startswith("Wild Companion")):
            continue
        cols[o["cost"]].append({**o, "tags": ["Yours"], "source": "yours", "starred": False})

    notes = [
        f"You keep your Hit Points ({hp.get('current', '?')} of {hp.get('max', '?')}) and gain {d['temp_hp']} Temporary Hit Points"
        + (" (three times your Druid level, Circle Forms)." if d["moon"] else " (your Druid level)."),
        f"Lasts up to {d['hours']} hour{'s' if d['hours'] != 1 else ''}, until you use Wild Shape again, have the Incapacitated condition, or die.",
        ("Beast Spells: you can cast your spells in this form, except any with a Material component that has a cost or is consumed."
         if d.get("beast_spells") else
         f"You can't cast spells, except your Circle of the Moon Spells ({', '.join(d['moon_spells'])}): those you can cast in a form."
         if d.get("moon_spells") else "You can't cast spells.")
        + " Shape-shifting doesn't break Concentration on a spell you already cast.",
        "Strength, Dexterity and Constitution are the form's; Intelligence, Wisdom and Charisma stay yours. You keep your skill and "
        "saving throw proficiencies (with your Proficiency Bonus) and use the form's modifier where it's higher.",
        "Your equipment falls, merges into the form (no effect) or is worn by it, your choice; the DM decides what the form can wear.",
    ]
    if d["lunar_radiance"]:
        notes.append("Lunar Radiance: each of your attacks in this form can deal its normal damage type or Radiant damage, chosen on each hit.")
    if d["toughness"]:
        notes.append("Increased Toughness: your Wisdom modifier is added to Constitution saving throws (included above).")
    if d.get("lunar_form"):
        notes.append("Lunar Form: once per turn, a target you hit with this form's attack takes an extra 2d10 Radiant damage (shown on the attacks).")
    if d.get("elemental_fury"):
        if d["fury"] == "Primal Strike":
            notes.append(f"Primal Strike: once on each of your turns when you hit with this form's attack, add {d['primal_strike']} Cold, "
                         "Fire, Lightning or Thunder damage (choose on the hit).")
        elif not d["fury"]:
            notes.append(f"Elemental Fury: if you chose Primal Strike, this form's attacks can add {d['primal_strike']} Cold, Fire, "
                         "Lightning or Thunder damage once on each of your turns. (Potent Spellcasting only affects cantrips.)")
    notes.append("Your other class features and feats stay with you (marked Yours). Whether one works in this body is the DM's call.")

    return {
        "beast": beast, "druid": d, "ac": ac, "ac_parts": ac_parts, "temp_hp": d["temp_hp"], "hp": hp,
        "speed": _speed_text(beast.get("speed") or {}), "abilities": abilities, "saves": saves, "skills": skills,
        "passive_perception": 10 + perception, "initiative": _signed(_mod(scores["dex"])),
        "columns": {k: {"shown": v, "all": v, "count": len(v)} for k, v in cols.items()},
        "traits": beast.get("traits") or [], "notes": notes, "castable": castable,
        "magic_action": bool(castable) or d.get("beast_spells", False),
    }
