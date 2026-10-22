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

from app import advantage
from app import character_views as views

DATA = Path(__file__).parent / "data" / "beasts_2024.json"
ABILITIES = (("str", "Strength", "Str"), ("dex", "Dexterity", "Dex"), ("con", "Constitution", "Con"),
             ("int", "Intelligence", "Int"), ("wis", "Wisdom", "Wis"), ("cha", "Charisma", "Cha"))
ABILITY_NAMES = {k: name for k, name, _ in ABILITIES}
KEPT = ("int", "wis", "cha")  # Wild Shape keeps your Intelligence, Wisdom and Charisma
SKILL_ABILITY = {"Acrobatics": "dex", "Animal Handling": "wis", "Arcana": "int", "Athletics": "str", "Deception": "cha",
                 "History": "int", "Insight": "wis", "Intimidation": "cha", "Investigation": "int", "Medicine": "wis",
                 "Nature": "int", "Perception": "wis", "Performance": "cha", "Persuasion": "cha", "Religion": "int",
                 "Sleight of Hand": "dex", "Stealth": "dex", "Survival": "wis"}
CR_LABELS = {0.0: "0", 0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}
MOON_SPELLS = ((3, ("Cure Wounds", "Moonbeam", "Starry Wisp")), (5, ("Conjure Animals",)), (7, ("Fount of Moonlight",)), (9, ("Mass Cure Wounds",)))
ASI = re.compile(r"Ability Score (Improvement|Increase)s?$", re.I)  # background and level ASIs are listed as feats
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


def forms(sheet: dict, fav: set[str], keep=None) -> list[dict]:
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
            "card": card(sheet, b, keep),
            # for the shared list's filters (templates/_form_list.html)
            "status_label": "Known" if is_known else "Locked" if reason else "Can learn",
            "move_labels": [m.capitalize() for m in sorted(k for k in b.get("speed") or {} if k != "walk")],
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
    """Reminders text for a form that isn't on the sheet."""
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
    recipe = beast_recipe(e, d.get("damage_bonus", 0) if att else 0)
    if dmg:
        first = recipe["events"][0]["parts"] if recipe else []
        kinds = " + ".join(f"{a} ({b}) {c}" if b else f"{a} {c}" for a, b, c in _damages(_hit_sentence(text)[0]) if b) or \
            " + ".join(f"{a} ({b}) {c}" if b else f"{a} {c}" for a, b, c in dmg)
        meta.append(kinds + (" (or Radiant)" if d.get("lunar_radiance") and att else ""))
        for ev in (recipe["events"][1:] if recipe else []):
            more = [p for p in ev["parts"] if p not in first]
            meta.append(f"{ev['name']}: {' + '.join(more) if ev['parts'][:len(first)] == first else ' + '.join(ev['parts'])}")
    if att and d.get("lunar_form"):
        meta.append("+2d10 Radiant once per turn")
    if att and d.get("fury") == "Primal Strike":
        meta.append(f"+{d['primal_strike']} Cold/Fire/Lightning/Thunder once per turn")
    if att and d.get("damage_bonus") and dmg:
        meta.append(f"{_signed(d['damage_bonus'])} damage (worn item)")
    hit = _signed(int(att.group(2).replace("−", "-")) + d.get("attack_bonus", 0)) if att else (
        f"DC {save.group(2)} {save.group(1)[:3]}" if save else "")
    adv = (advantage.for_attack(d.get("advs") or [], melee=att.group(1).startswith("Melee")) + advantage.in_attack(e["name"], text)) if att else []
    return {"key": f"beast:{e['name']}", "name": e["name"], "cost": cost, "hit": hit, "meta": " · ".join(meta) or _clip(text),
            "text": text, "tags": ["Form"], "uses": None, "spends": [], "starred": False, "source": "form", "adv": adv,
            "recipe": recipe}


def _clip(text: str, n: int = 110) -> str:
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= n else first[: n - 1].rsplit(" ", 1)[0] + "…"


NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
CONDITIONS = ("Grappled", "Restrained", "Prone", "Poisoned", "Blinded", "Frightened", "Stunned", "Paralyzed", "Incapacitated", "Charmed", "Deafened")


def _damages(text: str) -> list[tuple[str, str, str]]:
    """Each "9 (1d8 + 5) Slashing damage" in an attack, leaving out alternatives
    ("…, or 6 (2d4) Piercing damage if the swarm is Bloodied")."""
    return [m.groups() for m in DAMAGE.finditer(text) if not text[max(0, m.start() - 3):m.start()].endswith("or ")]


def _part(dice: str, kind: str, bonus: int = 0) -> str:
    """'1d6 + 2', 'Piercing' -> '1d6+2 piercing' (a roll recipe part, app/roll_recipes.py)."""
    m = re.fullmatch(r"(\d+d\d+)(?:\s*([+−-])\s*(\d+))?", dice.strip())
    if not m:  # a fixed amount ("1 Bludgeoning damage")
        return f"{dice.strip()} {kind.lower()}"
    flat = ((-1 if m.group(2) in "−-" else 1) * int(m.group(3)) if m.group(3) else 0) + bonus
    return f"{m.group(1)}{f'{flat:+d}' if flat else ''} {kind.lower()}"


def _when(clause: str) -> str:
    """A short name for a condition: 'if the swarm is Bloodied' -> 'Swarm Bloodied'."""
    if re.search(r"moved 20\+ feet straight", clause):
        return "After a 20-ft charge"
    m = re.search(r"if (?:the|it|its) (\w+)? ?(?:is|has) (?:the )?(\w+)", clause)
    return f"{(m.group(1) or '').title()} {m.group(2)}".strip() if m else clause.strip().capitalize()[:40]


def beast_recipe(e: dict, damage_bonus: int = 0) -> dict | None:
    """How a stat block action rolls (audited by scripts/roll_audit.py): the normal hit (or failed
    save), and as other choices the alternatives ("…, or 2 (1d4) Piercing damage if the swarm is
    Bloodied") and conditional extras ("If … moved 20+ feet straight toward it …, an extra 9 (2d8)").
    A worn item's damage bonus goes on the first part of an attack."""
    text = e["text"]
    att, save = ATTACK.search(text), SAVE.search(text)
    hit, rest = _hit_sentence(text)
    base = [m for m in DAMAGE.finditer(hit) if not hit[max(0, m.start() - 4):m.start()].rstrip("—").endswith("or ")]
    if not base or not any(m.group(2) for m in DAMAGE.finditer(text)):
        return None
    bonus = damage_bonus if att else 0
    parts = [_part(m.group(2) or str(max(int(m.group(1)) + (bonus if i == 0 else 0), 1)), m.group(3), bonus if i == 0 and m.group(2) else 0)
             for i, m in enumerate(base)]
    on = "hit" if att else "save" if save else "auto"
    first = {"name": e["name"], "on": on, "parts": parts}
    if save:
        first |= {"save": save.group(1)[:3], "success": "half" if re.search(r"Success: Half damage", text) else "none"}
    rep = re.search(r"at the (?:start|end) of each of [\w' ]+ turns", text)
    if rep and not att:
        first["repeat"] = rep.group(0).removeprefix("at the ")
    events = [first]
    for m in DAMAGE.finditer(hit):  # "…, or 2 (1d4) Piercing damage if the swarm is Bloodied"
        if m.group(2) and hit[max(0, m.start() - 4):m.start()].rstrip("—").endswith("or "):
            cond = re.match(r"\s*(if [^—.]+)", hit[m.end():])
            alt = [_part(m.group(2), m.group(3), bonus)] + parts[1:]
            events.append({**first, "name": _when(cond.group(1)) if cond else "Otherwise", "parts": alt})
    for sent in re.split(r"(?<=\.)\s+", rest):  # "If … moved 20+ feet …, the target takes an extra 9 (2d8) …"
        extra = [m for m in DAMAGE.finditer(sent) if m.group(2)]
        if extra and re.search(r"\bextra\b", sent):
            events.append({**first, "name": _when(sent), "parts": parts + [_part(m.group(2), m.group(3)) for m in extra]})
    return {"level": 0, "events": events}


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


def turn_attacks(beast: dict, atk: int = 0, dmg_bonus: int = 0) -> dict:
    """What the form does with its Attack action: Multiattack spelled out, average damage
    if everything hits, and the best attack bonus (with any kept item's bonus)."""
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
        hit = _signed(int(att.group(2).replace("−", "-")) + atk) if att else ""
        dmg_text = " + ".join(f"{int(x) + (dmg_bonus if i == 0 else 0)} {k}" for i, (x, _, k) in enumerate(dmg)) + \
            "".join(f"; +{x} {k} if…" for x, _, k in more)
        return f"{a['name']} ({hit}{', ' + dmg_text if dmg_text else ''})"

    return {
        "text": ", ".join(f"{n} × {one(a)}" if n > 1 else one(a) for n, a in parts),
        "per_turn": sum(n * (_avg(a["text"]) + (dmg_bonus if _damages(a["text"]) else 0)) for n, a in parts),
        "hit": _signed(int(ATTACK.search(best["text"]).group(2).replace("−", "-")) + atk) if best else "",
        "hit_value": int(ATTACK.search(best["text"]).group(2).replace("−", "-")) + atk if best else -99,
    }


def card(sheet: dict, beast: dict, keep=None) -> dict:
    """Everything the Wild Shape list shows for one form, with this druid's numbers."""
    f = shaped(sheet, beast, lite=True, keep=keep)
    d = f["druid"]
    t = turn_attacks(beast, d.get("attack_bonus", 0), d.get("damage_bonus", 0))
    extra = []
    if d.get("lunar_form"):
        extra.append("+2d10 Radiant once per turn")
    if d.get("fury") == "Primal Strike":
        extra.append(f"+{d['primal_strike']} elemental once per turn")
    texts = " ".join(e["text"] for k in ("actions", "bonus_actions", "reactions") for e in beast.get(k) or [])
    effects = [c for c in CONDITIONS if re.search(rf"\b{c}\b", texts)]
    saves = {s["key"]: s for s in f["saves"]}
    skills = [s for s in f["skills"] if s["name"] in ("Perception", "Stealth", "Athletics", "Acrobatics", "Survival")]
    attack_adv = []
    for o in f["columns"]["Action"]["all"]:
        attack_adv += [a for a in o.get("adv") or [] if o["source"] == "form" and a not in attack_adv]
    speed = f["speed_dict"]
    return {
        "ac": f["ac"], "ac_moon": d.get("moon") and f["ac"] > beast["ac"], "temp_hp": f["temp_hp"],
        "attack": t["text"], "hit": t["hit"], "hit_value": t["hit_value"], "per_turn": t["per_turn"], "radiant": d.get("lunar_radiance", False), "extra": extra,
        "speed": _speed_text(speed), "fastest": max(speed.values(), default=0), "senses": beast.get("senses", ""),
        "resist": ", ".join(x for x in (beast.get("resist"), beast.get("immune")) if x),
        "saves": [saves[k] for k in ("str", "dex", "con")], "skills": skills,
        "traits": [x["name"] for x in beast.get("traits") or []],
        "bonus": [x["name"] for x in beast.get("bonus_actions") or []], "reactions": [x["name"] for x in beast.get("reactions") or []],
        "effects": effects, "attack_adv": attack_adv, "save_adv_all": f["save_adv_all"],
    }


def kept(sheet: dict, keep) -> dict:
    """What the player keeps in Wild Shape (the DM's ruling, saved per character):
    totals of worn items' bonuses, and class features that change the numbers."""
    opts = sheet.get("form_options") or {"items": [], "features": []}
    keep = set(keep or [])
    items = [i for i in opts["items"] if i["key"] in keep]
    total = {k: sum(i["effects"].get(k, 0) for i in items)
             for k in ("saves", "checks", "initiative", "ac", "attack", "damage", "speed", "str_score", "dex_score", "con_score")}
    by = {k: [(i["name"], i["effects"][k]) for i in items if i["effects"].get(k)] for k in total}
    feats = {f["key"]: f for f in opts["features"] if f["key"] in keep}
    return {"total": total, "by": by, "features": feats, "items": items,
            "names": [i["name"] for i in items] + [f["name"] for f in feats.values()]}


def options_for(sheet: dict, keep) -> list[dict]:
    """The toggles to show, in two groups: Traits (class features) and Equipment (worn items),
    each with what it does in a form and whether it's kept. Keys are the saved choices."""
    keep = set(keep or [])
    labels = {"saves": "saves", "checks": "ability checks", "initiative": "Initiative", "ac": "AC",
              "attack": "to hit with natural weapons and unarmed strikes", "damage": "damage with natural weapons and unarmed strikes",
              "speed": "speed",
              "str_score": "to the form's Strength score", "dex_score": "to the form's Dexterity score",
              "con_score": "to the form's Constitution score"}
    opts = sheet.get("form_options") or {"items": [], "features": []}
    out = [{"key": f["key"], "name": f["name"], "what": f["text"], "kind": "Class feature", "group": "traits", "on": f["key"] in keep}
           for f in opts["features"]]
    out += [{"key": i["key"], "name": i["name"], "kind": "Worn item", "group": "equipment", "on": i["key"] in keep,
             "what": ", ".join(f"{_signed(v)} {labels[k]}" for k, v in i["effects"].items())} for i in opts["items"]]
    return out


def shaped(sheet: dict, beast: dict, lite: bool = False, keep=None) -> dict:
    """The druid in this form: the Beast's stat block with what Wild Shape keeps
    (Hit Points, Int/Wis/Cha, proficiencies, class features) and Circle of the Moon's
    changes. Each number says where it comes from."""
    d = druid(sheet) or {"level": 0, "moon": False, "temp_hp": 0, "lunar_radiance": False, "toughness": False, "uses": None, "hours": 0}
    kp = kept(sheet, keep)
    d = {**d, "attack_bonus": kp["total"]["attack"], "damage_bonus": kp["total"]["damage"]}
    pb = sheet.get("proficiency_bonus") or 2
    mine = {a["key"][:3]: a["score"] for a in sheet.get("abilities") or []}
    scores = {k: (mine.get(k, 10) if k in KEPT else (beast.get("abilities") or {}).get(k, 10)) for k, _, _ in ABILITIES}
    for k in ("str", "dex", "con"):  # kept score items (e.g. a learned Manual of Quickness) raise the form's score
        scores[k] = min(30, scores[k] + kp["total"][f"{k}_score"])
    wis = _mod(scores["wis"])

    abilities = [{"key": k, "short": short, "score": scores[k], "label": _signed(_mod(scores[k])),
                  "from": "yours" if k in KEPT else ("form + kept" if kp["total"].get(f"{k}_score") else "form")}
                 for k, _, short in ABILITIES]

    # Advantage that carries over (class features, feats, kept items; not species traits), and the form's own
    mine_adv = sheet.get("advantages") or []
    advs = advantage.carried(mine_adv, [i["name"] for i in kp["items"]]) + advantage.from_beast(beast)
    d["advs"] = advs

    def says(parts):
        return " + ".join(f"{n} {_signed(v)}" for n, v in parts)

    my_saves = {s["short"].lower(): s for s in sheet.get("saves") or []}
    saves = []
    for k, name, short in ABILITIES:
        mine_sv = my_saves.get(k) or {}
        prof = bool(mine_sv.get("proficient"))
        parts = [(f"{short} modifier ({'yours' if k in KEPT else 'form'})", _mod(scores[k]))]
        if prof:
            parts.append(("Your Proficiency Bonus", pb))
        if k == "con" and d["toughness"]:
            parts.append(("Increased Toughness (Wisdom modifier)", wis))
        parts += [(n, v) for n, v in mine_sv.get("kept_parts") or []]  # class features and feats stay
        parts += [(f"{n} (kept)", v) for n, v in kp["by"]["saves"]]
        yours = sum(v for _, v in parts)
        stat = (beast.get("saves") or {}).get(k)
        use_form = stat is not None and stat > yours
        saves.append({"key": k, "short": short, "bonus": stat if use_form else yours, "label": _signed(stat if use_form else yours),
                      "proficient": prof, "adv": advantage.for_save(advs, k),
                      "from": f"The form's stat block {_signed(stat)} (higher than yours: {says(parts)})" if use_form else says(parts)})

    my_skills = {s["name"]: s for s in sheet.get("skills") or []}
    skills = []
    for name, ab in SKILL_ABILITY.items():
        mine_sk = my_skills.get(name) or {}
        level = mine_sk.get("proficiency", "") if mine_sk.get("proficiency") in ("proficient", "expertise") else ""
        prof = pb * 2 if level == "expertise" else pb if level == "proficient" else 0
        parts = [(f"{ab.title()} modifier ({'yours' if ab in KEPT else 'form'})", _mod(scores[ab]))]
        if prof:
            parts.append(("Expertise (twice your Proficiency Bonus)" if level == "expertise" else "Your Proficiency Bonus", prof))
        kept_parts = [(n, v) for n, v in mine_sk.get("kept_parts") or []]  # e.g. Primal Order (Magician): + Wis to Arcana
        parts += kept_parts + [(f"{n} (kept)", v) for n, v in kp["by"]["checks"]]
        yours = sum(v for _, v in parts)
        stat = (beast.get("skills") or {}).get(name)
        if not prof and not kept_parts and stat is None:
            continue
        use_form = stat is not None and stat > yours
        skills.append({"name": name, "bonus": stat if use_form else yours, "label": _signed(stat if use_form else yours),
                       "level": level or ("form" if stat is not None else ""), "adv": advantage.for_check(advs, name, ab),
                       "from": f"The form's stat block {_signed(stat)} (higher than yours: {says(parts)})" if use_form else says(parts)})
    perception = next((s["bonus"] for s in skills if s["name"] == "Perception"), _mod(scores["wis"]) + kp["total"]["checks"])
    init_parts = ([("Dexterity modifier (form)", _mod(scores["dex"]))] + [(n, v) for n, v in sheet.get("initiative_kept") or []]
                  + [(f"{n} (kept)", v) for n, v in kp["by"]["initiative"]])

    ac_parts = [(f"The {beast['name']}'s AC" + (f" ({beast['ac_note']})" if beast.get("ac_note") else ""), beast["ac"])]
    ac = beast["ac"]
    if d["moon"]:
        moon_ac = 13 + wis
        ac_parts.append((f"Circle Forms: 13 + your Wisdom modifier ({_signed(wis)}) = {moon_ac}", moon_ac))
        ac = max(ac, moon_ac)
    ud = kp["features"].get("unarmored-defense")
    if ud:
        extra = _mod(scores.get(ud.get("ability", "wis"), 10))
        ud_ac = 10 + _mod(scores["dex"]) + extra
        ac_parts.append((f"Unarmored Defense (kept): 10 + the form's Dexterity ({_signed(_mod(scores['dex']))}) + "
                         f"{ud.get('ability', 'wis').title()} ({_signed(extra)}) = {ud_ac}", ud_ac))
        ac = max(ac, ud_ac)
    for name, v in kp["by"]["ac"]:
        ac_parts.append((f"{name} (worn): {_signed(v)}", v))
        ac += v
    speed = dict(beast.get("speed") or {})
    um = kp["features"].get("unarmored-movement")
    for k in speed:
        speed[k] += (um.get("bonus", 0) if um else 0) + kp["total"]["speed"]
    feat_speed = [(n, v) for n, v in sheet.get("speed_kept") or []]  # e.g. Mobile: your Speed (walking) +10 ft
    if "walk" in speed:
        speed["walk"] += sum(v for _, v in feat_speed)
    speed_parts = ([(f"The {beast['name']}'s speeds", 0)] + ([("Unarmored Movement (kept)", um.get("bonus", 0))] if um else [])
                   + [(f"{n} (kept)", v) for n, v in kp["by"]["speed"]] + [(f"{n} (walking)", v) for n, v in feat_speed])

    hp = sheet.get("hit_points") or {}
    cols = {"Action": [], "Bonus action": [], "Reaction": []}
    for e in beast.get("actions") or []:
        cols["Action"].append(_entry(e, "Action", d))
    for e in beast.get("bonus_actions") or []:
        cols["Bonus action"].append(_entry(e, "Bonus action", d))
    for e in beast.get("reactions") or []:
        cols["Reaction"].append(_entry(e, "Reaction", d))
    # Unarmed Strike: anyone has it, in any body (the form's Strength; a Monk may use Dexterity
    # and the Martial Arts die, and with Martial Arts makes one as a Bonus Action)
    feats = {f["name"] for f in sheet.get("features") or []}
    monk = next((c["level"] for c in sheet.get("classes") or [] if c["name"] == "Monk"), 0)
    martial = "Martial Arts" in feats and monk
    str_m, dex_m = _mod(scores["str"]), _mod(scores["dex"])
    um = max(str_m, dex_m) if martial else str_m
    die = 12 if monk >= 17 else 10 if monk >= 11 else 8 if monk >= 5 else 6
    u_hit = _signed(um + pb + d["attack_bonus"])
    bonus_n = um + d["damage_bonus"]
    u_dmg = (f"1d{die} {'+' if bonus_n >= 0 else '−'} {abs(bonus_n)}" if martial else str(max(1, 1 + bonus_n))) + " Bludgeoning"
    if d.get("lunar_radiance"):
        u_dmg += " (or Radiant)"
    u_dc = 8 + um + pb
    unarmed = {"name": "Unarmed Strike", "hit": u_hit, "tags": ["Yours"], "uses": None, "spends": [], "starred": False, "source": "unarmed",
               "adv": advantage.for_attack(advs, melee=True),
               "meta": f"reach 5 ft · {u_dmg} · or Grapple / Shove (DC {u_dc} Str or Dex save)",
               "text": "A punch, kick, head-butt or similar with the form's body. Choose Damage, Grapple or Shove each time."
                       + (" Martial Arts lets you use Dexterity and your Martial Arts die." if martial else "")}
    cols["Action"].insert(len(beast.get("actions") or []), {**unarmed, "key": "wild-shape:unarmed", "cost": "Action"})
    if martial:
        cols["Bonus action"].append({**unarmed, "key": "wild-shape:unarmed-bonus", "cost": "Bonus action",
                                     "name": "Unarmed Strike (Martial Arts)",
                                     "meta": unarmed["meta"] + " · Martial Arts needs no armor or shield; the DM decides in a form"})
    cols["Reaction"].append({"key": "wild-shape:opportunity", "name": "Opportunity Attack", "cost": "Reaction", "hit": "", "tags": [],
                             "uses": None, "spends": [], "starred": False, "source": "rule",
                             "meta": "When a creature you can see leaves your reach: one melee attack (a form's attack or an Unarmed Strike)"})
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
        cols[o["cost"]].append({**o, "tags": [tag] + o["tags"], "source": "spell", "starred": False,
                                "adv": advantage.for_attack(advs, spell=True) if sp.get("attack") else []})
    # Class features and feats you keep (no weapons or items, no species traits; nothing that casts a spell
    # unless you can cast in a form)
    species_keys = {a["key"] for a in sheet.get("actions") or [] if a.get("source") == "race"}
    for o in options:
        if o["kind"] != "feature" or o["cost"] not in cols or o["name"].startswith(("Wild Shape", "Unarmed Strike")) or o["key"] in species_keys:
            continue
        if o["name"] == "Reactive Spell" and castable and not d.get("beast_spells"):
            cols[o["cost"]].append({**o, "tags": ["Yours"], "source": "yours", "starred": False,
                                    "meta": f"Cast a spell instead of an Opportunity Attack: only one you can cast in this form ({', '.join(castable[:3])})"})
            continue
        if not d.get("beast_spells") and ("Spell" in o["name"] or o["name"].startswith("Wild Companion")):
            continue
        cols[o["cost"]].append({**o, "tags": ["Yours"], "source": "yours", "starred": False, "adv": []})

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
    if kp["names"]:
        notes.append(f"Kept by your DM's ruling (and included above): {', '.join(kp['names'])}.")
    feats = [f["name"] for f in sheet.get("features") or [] if f.get("source") == "Feat" and not ASI.search(f["name"])]
    if feats:
        notes.append(f"Your feats stay with you: {', '.join(feats)}. Their numbers are included above (hover a number for its parts).")
    for a in advantage.carried(mine_adv, [i["name"] for i in kp["items"]]):
        if a["when"]:  # e.g. War Caster: only Constitution saves to keep Concentration, not every Constitution save
            other = f"other {ABILITY_NAMES[a['target']]} saving throws" if a["on"] == "save" and a["target"] in ABILITY_NAMES else "every roll of that kind"
            notes.append(f"{a['source']}: {a['text'].split(' · ')[0]} only, not on {other} (marked Adv; hover it for when).")
    species = sheet.get("species") or ""
    lost = [f["name"] for f in sheet.get("features") or [] if species and f.get("source") == species]
    if lost:
        notes.append(f"Your species traits don't carry into a form ({', '.join(lost)}), so their Advantage and senses don't apply; "
                     "use the form's senses. Skill proficiencies they gave you stay, like every proficiency.")
    notes.append("You keep your creature type, Hit Point Dice and languages, and you can speak in a form (a 2024 change).")
    notes.append("Your other class features (from every class you have) stay with you (marked Yours). Whether one works in this body is the DM's call.")

    return {
        "beast": beast, "druid": d, "ac": ac, "ac_parts": ac_parts, "temp_hp": d["temp_hp"], "hp": hp,
        "speed": _speed_text(speed), "speed_dict": speed, "abilities": abilities, "saves": saves, "skills": skills,
        "passive_perception": 10 + perception, "initiative": _signed(sum(v for _, v in init_parts)), "initiative_parts": init_parts,
        "initiative_adv": advantage.initiative(advs), "save_adv_all": advantage.all_saves(advs), "speed_parts": speed_parts,
        "kept": kp,
        "columns": {k: {"shown": v, "all": v, "count": len(v)} for k, v in cols.items()},
        "traits": beast.get("traits") or [], "notes": notes, "castable": castable,
        "magic_action": bool(castable) or d.get("beast_spells", False),
    }
