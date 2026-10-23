"""Shapes the parsed D&D Beyond sheets (app/ddb.py) into what the Battle,
Character and Party pages show. Plain functions over the summary dicts, so
they're easy to test without a browser."""

import re
from urllib.parse import quote

from app import advantage, class_rules, conditions, house_rules
from app import roll_recipes as rr

COSTS = ["Action", "Bonus action", "Reaction", "Other"]
COLUMN_LIMIT = 7  # options shown in a Battle column before "See all"


def _cost(activation: str) -> str:
    return activation if activation in ("Action", "Bonus action", "Reaction") else "Other"


ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def ordinal(n: int) -> str:
    return ORDINAL.get(n, f"{n}th")


def _spend(resource: dict, amount: int | None) -> dict:
    """One thing an option uses up, with what's left of it now."""
    unit = resource["name"].split(":")[0].strip()
    if amount is not None and unit.endswith("Points") and amount == 1:
        unit = unit[:-1]
    label = f"{amount} {unit}" if amount is not None and unit.endswith(("Point", "Points")) else (
        f"{amount} use of {unit}" if amount == 1 else f"{amount} uses of {unit}" if amount else unit)
    if resource["name"].startswith("Lay On Hands") and amount:
        label = f"{amount} HP from the pool"
    return {"label": label, "of": resource["name"], "uses": resource["uses"]}


def resource_spends(sheet: dict, name: str, key: str, text: str) -> list[dict]:
    """Which limited resources an option uses ("expend 1 Focus Point", or a
    "Channel Divinity: …" option drawing on Channel Divinity), with how many are left."""
    out = []
    if "Regain" in name:  # e.g. Wild Resurgence: Regain Wild Shape gives a use back
        return out
    for r in sheet.get("actions") or []:
        if not r.get("uses") or r.get("key") == key:
            continue
        base = r["name"].split(":")[0].strip()
        forms = {re.escape(f) for f in (r["name"], base, base[:-1] if base.endswith("s") else base)}
        alt = "|".join(sorted(forms, key=len, reverse=True))
        m = re.search(rf"(?:expend|spend|use)s?\s+(\d+|an?|one|two|three|four|five)\s+(?:uses?\s+of\s+)?(?:your\s+)?(?:{alt})\b", text, re.I)
        amount = None
        if m:
            amount = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1).lower()]
        elif base == "Lay On Hands" and name.startswith(base):
            hp = re.search(r"expend\s+(\d+)\s+Hit Points?\s+from", text)
            amount = int(hp.group(1)) if hp else None
        # "Channel Divinity: Divine Sense" draws on Channel Divinity; "Lay On Hands: Heal" on its pool.
        # (Siblings like "Wild Resurgence: Regain …" are separate abilities.)
        same_family = name.split(":")[0].strip() == base and name != r["name"] and (r["name"] == base or "Pool" in r["name"])
        if not (m or same_family or re.search(rf"(?:use|expend|spend)\s+(?:your\s+)?(?:{alt})\b", text, re.I)):
            continue
        if amount is None and same_family and base in ("Channel Divinity", "Wild Shape"):
            amount = 1
        out.append(_spend(r, amount))
    return out


def slot_spends(sheet: dict, sp: dict) -> list[dict]:
    """Free casts first (from a feat, species or item), then a slot of the spell's
    level (pact slots for Warlock spells) if a slot can be used."""
    free = [{"label": "Free cast" if sp["uses"]["max"] == 1 else "Free casts", "of": "Free casts", "uses": sp["uses"]}] if sp.get("uses") else []
    if not sp.get("level") or (sp.get("uses") and not sp.get("uses_slot")):
        return free
    return free + [{**x, "label": ("or " if free else "") + x["label"]} for x in _slot(sheet, sp)]


def _slot(sheet: dict, sp: dict) -> list[dict]:
    slots = sheet.get("spell_slots") or {}
    pact = slots.get("pact")
    regular = {s["level"]: s for s in slots.get("slots") or []}
    if pact and pact["level"] >= sp["level"] and ("Warlock" in (sp.get("sources") or []) or not regular):
        return [{"label": f"Pact ({ordinal(pact['level'])})", "of": "Pact Magic",
                 "uses": {"left": pact["max"] - pact["used"], "max": pact["max"]}}]
    s = regular.get(sp["level"])
    if not s:
        return []
    # "1st-level", not "1st-level slot": players know what it spends (Brett, 2026-10-22)
    return [{"label": f"{ordinal(sp['level'])}-level", "of": "Spell slots", "uses": {"left": s["max"] - s["used"], "max": s["max"]},
             "higher": [{"level": ordinal(x["level"]), "left": x["max"] - x["used"], "max": x["max"]}
                        for lvl, x in sorted(regular.items()) if lvl > sp["level"]]}]


def options(sheet: dict, starred: set[str] | None = None) -> list[dict]:
    """Everything the character can do on a turn, as one list: attacks, spells,
    features and items, each with what it costs (action, bonus action…)."""
    starred = starred or set()
    attacks = {a["name"]: a for a in sheet.get("attacks") or []}
    advs = sheet.get("attack_adv") or []
    rules = class_rules.turn(sheet)
    mastered = class_rules.masteries(sheet)
    action_names = {a["name"] for a in sheet.get("actions") or []}
    out = []

    def add(**o):
        o.setdefault("tags", [])
        o.setdefault("uses", None)
        o.setdefault("hit", "")
        o.setdefault("meta", "")
        o.setdefault("text", "")
        o.setdefault("summary", "")
        o.setdefault("spends", [])
        o.setdefault("adv", [])
        o["starred"] = o["key"] in starred
        o.setdefault("oref", o["key"])
        moved = (sheet.get("_overrides") or {}).get(f"{o['oref']}|cost")
        if moved:
            o["cost"] = moved
        out.append(o)

    for a in sheet.get("attacks") or []:
        mastery = _mastery(a, mastered)
        props = [p for p in a["properties"] if p not in class_rules.MASTERIES]  # a mastery only counts if you've mastered the weapon
        tags = ([f"×{rules['attacks']} per Attack action"] if rules["attacks"] > 1 else []) + ([f"Mastery: {mastery}"] if mastery else [])
        add(key=a["key"], oref=f"attack:{a['name']}", kind="attack", cost="Action", name=a["name"], hit=a["to_hit"], tags=tags,
            adv=advantage.for_attack(advs, melee="/" not in (a.get("range") or "")),
            meta=" · ".join(x for x in (a["range"], a["damage"], ", ".join(props)) if x),
            text=f"{mastery}: {class_rules.MASTERIES[mastery]}." if mastery else "",
            common=True)
    for sp in sheet.get("spells") or []:
        cost = sp["casting_time"] if sp["casting_time"] in ("Action", "Bonus action", "Reaction") else None
        if not cost:
            continue
        level = "cantrip" if not sp["level"] else ordinal(sp["level"])
        effect = sp["damage"] or (f"heals {sp['healing']}" if sp["healing"] else "")
        spends = slot_spends(sheet, sp)
        says_level = any(x["of"] == "Spell slots" for x in spends)  # "1st-level slot" already gives the level
        tags = ([] if says_level else [level]) + (["Conc."] if sp["concentration"] else [])
        add(key=sp["key"], kind="spell", cost=cost, name=sp["name"], hit=sp["attack"] or sp["save"], tags=tags, level=sp["level"] or 0,
            adv=advantage.for_attack(advs, spell=True) if sp["attack"] else [],
            spends=spends,
            meta=" · ".join(x for x in (sp["range"], effect, sp["trigger"] if cost == "Reaction" else "") if x),
            text=sp.get("text") or sp["summary"], summary=sp["summary"], recipe=house_rules.spell(sp["name"]) or sp.get("roll"),
            # Smites are cast right after you hit, so they belong with the fight (tool correction built in, 2026-10-23)
            common=cost == "Reaction" or (not sp["level"] and bool(sp["attack"] or sp["save"]) and bool(sp["damage"]))
            or (cost == "Bonus action" and sp["name"].endswith(" Smite")))
    for a in sheet.get("actions") or []:
        cost = _cost(a["activation"])
        if _not_an_action(a, cost, rules, action_names):
            continue
        hit, meta, unarmed = "", "", a["name"].startswith("Unarmed Strike")
        if unarmed:
            if a["name"] != "Unarmed Strike" or cost == "Action":
                continue  # the attack is listed once, from the attacks; "(Dex.)" variants are the same strike
            u = attacks.get("Unarmed Strike") or {}
            hit, meta = u.get("to_hit", ""), u.get("damage", "")
        add(key=a["key"], kind="feature", cost=cost, name=a["name"], hit=hit, meta=meta, uses=a["uses"], text=a["text"],
            spends=[] if a["uses"] else resource_spends(sheet, a["name"], a["key"], a["text"] or ""),
            summary=a.get("summary", ""),
            common=not a.get("rule") and (unarmed or cost == "Reaction" or bool(a["uses"] and a["source"] in ("class", "feat", "race"))))
    have = {class_rules._norm(o["name"]) for o in out}
    for r in rules["options"]:
        if class_rules._norm(r["name"]) not in have:
            add(key=f"rule:{r['name']}", kind="feature", cost=r["cost"], name=r["name"], meta=r["meta"], text=r["meta"],
                tags=[r["source"]], common=True)
    _general_options(sheet, add, mastered, have)
    for it in sheet.get("inventory") or []:
        for a in conditions.item_actions(it):  # magic items that grant an action (Ring of Invisibility…)
            add(key=a["key"], oref=f"item:{it['base_name']}#{a['key'].split('#')[1]}", kind="item", cost=a["cost"], name=a["name"],
                meta=a["meta"], text=a["text"], summary=a["text"], starts=a.get("starts"), ends=a.get("ends"), item=a["item"], note=a.get("note", ""),
                common=False)  # in See all; the player pins what they'd use
        if not it["battle"]:
            continue
        uses = it["charges"] if it["charges"] and it["charges"]["reset"] != "Used up" else None
        first = re.split(r"(?<=[.!?])\s", it["summary"] or "", maxsplit=1)[0]
        add(key=it["key"], oref=f"item:{it['base_name']}", kind="item", cost="Action", name=f"Use an item: {it['name']}", uses=uses,
            tags=[f"×{it['quantity']}"] if it["quantity"] > 1 else [], meta=first if len(first) <= 120 else first[:119].rsplit(" ", 1)[0] + "…",
            text=it.get("text") or it["summary"], summary=it["summary"], common="healing" in it["name"].lower(),
            recipe=rr.item(it["base_name"]) or rr.item(it["name"]),
            **({"starts": ou["starts"], "note": ou.get("note", ""), "item": it["name"], "track": True} if (ou := conditions.on_use(it)) else {}))
    unarmed = attacks.get("Unarmed Strike")
    for o in out:
        rollable(o, unarmed)
    return out


# What an option rolls (the roll buttons: _char.html hit()): its to-hit, else dice in its details,
# else dice its text says you regain ("regains 2d4 + 2 Hit Points") or deal ("1d6 fire damage").
# Features that make Unarmed Strikes (Flurry of Blows) roll the Unarmed Strike.
DICE = r"(\d+d\d+(?:\s*[+\u2212-]\s*\d+(?!d))?)"
HEALS = re.compile(r"\b(?:regains?|restores?|heals?)\s+" + DICE, re.I)
DEALS = re.compile(DICE + r"\s+(?:[a-z]+\s+){0,2}damage\b", re.I)
MAKES_UNARMED = re.compile(r"\bmake (?:one|two|three|an?) Unarmed Strikes?\b", re.I)


def _dice(text: str) -> str:
    m = re.search(DICE, text or "")
    return re.sub(r"\s+", "", m.group(1)).replace("\u2212", "-") if m else ""


def rollable(o: dict, unarmed: dict | None = None) -> dict:
    """Sets o["dice"] (damage or healing dice, "" if none) and o["heal"]; gives a feature that
    makes Unarmed Strikes the Unarmed Strike's to-hit and damage."""
    recipe = o.get("recipe")
    if recipe and recipe.get("events"):  # an audited (or D&D Beyond) recipe says exactly what rolls
        other = [e for e in recipe["events"] if e["on"] != "hit"]
        o["dice"] = (other or recipe["events"])[0]["parts"][0] if (other or recipe["events"])[0].get("parts") else ""
        o["heal"] = bool(other) and other[0]["on"] == "heal"
        return o
    text = f"{o.get('summary') or ''} {o.get('text') or ''}"
    if not o.get("hit") and unarmed and o.get("kind") == "feature" and MAKES_UNARMED.search(text):
        o["hit"] = unarmed.get("to_hit", "")
        o["meta"] = o.get("meta") or unarmed.get("damage", "")
    meta = o.get("meta") or ""
    o["dice"], o["heal"] = _dice(meta), "heals " in meta or "healing" in (o.get("name") or "").lower()
    if not o["dice"]:
        m = HEALS.search(text)
        d = None if m else DEALS.search(text)
        o["dice"], o["heal"] = (_dice(m.group(1)), True) if m else (_dice(d.group(1)), False) if d else ("", o["heal"])
    return o


def _mastery(attack: dict, mastered: dict[str, str]) -> str | None:
    """The mastery property this character can use with this weapon, if any."""
    kind = (attack.get("base") or "").lower()
    name = attack["name"].lower()
    for weapon, mastery in mastered.items():
        if weapon == kind or re.search(rf"\b{re.escape(weapon)}\b", name):
            return mastery
    return None


def _not_an_action(a: dict, cost: str, rules: dict, action_names: set[str]) -> bool:
    """D&D Beyond actions that aren't options on a turn: weapon masteries ("Vex
    (Dart)", shown on the weapon), riders on a hit (Stunning Strike, shown under
    "On a hit"), resource pools (Sorcery Points) and the bare Channel Divinity pool
    when its options are listed separately."""
    name = a["name"]
    if class_rules.is_mastery_action(name) or name in rules["replaced"]:
        return True
    if cost in ("Action", "Bonus action") and (name in class_rules.RESOURCE_ACTIONS or name.endswith(": Healing Pool")):
        return True
    return name == "Channel Divinity" and any(n.startswith("Channel Divinity:") for n in action_names)


def _general_options(sheet: dict, add, mastered: dict[str, str], have: set[str]) -> None:
    """Options every character has from the core rules: the Opportunity Attack and
    the Light weapon's extra attack."""
    attacks = sheet.get("attacks") or []
    melee = [a for a in attacks if "/" not in (a.get("range") or "") and "(" not in (a.get("range") or "")]
    best = max(melee, key=lambda a: int(a["to_hit"].replace("−", "-") or 0), default=None)
    if "opportunity attack" not in have and best:
        add(key="rule:Opportunity Attack", kind="feature", cost="Reaction", name="Opportunity Attack", hit=best["to_hit"],
            meta=f"When a creature you can see leaves your reach: one melee attack ({best['name']})",
            text="When a creature you can see leaves your reach (using its action, Bonus Action, Reaction or movement), "
                 "you can take a Reaction to make one melee attack with a weapon or an Unarmed Strike against it, right before it leaves.",
            common=True)
    light = [a for a in melee if "Light" in a["properties"]]
    if len(light) >= 2:
        nick = any(_mastery(a, mastered) == "Nick" for a in light)
        add(key="rule:Light weapon extra attack", kind="feature", cost="Action" if nick else "Bonus action", name="Light weapon extra attack",
            meta=("Part of the Attack action (Nick), once per turn: " if nick else "After attacking with a Light weapon in the Attack action: ")
            + "one attack with your other Light weapon; no ability modifier to its damage unless negative",
            common=True)


def _battle_override(sheet: dict, oref: str) -> str | None:
    return (sheet.get("_overrides") or {}).get(f"{oref}|battle")


def battle_columns(sheet: dict, starred: set[str], order: dict[str, list[str]] | None = None, pinned_only: bool = False) -> dict:
    """Action / Bonus action / Reaction columns: pinned first, then the common options (or the
    player's own drag-and-drop order); the rest is behind "See all". With `pinned_only` (anyone who
    can see the player's pins), only what the player pinned: Battle shows their plan
    (Brett, 2026-10-21: fewer automatic choices, to encourage planning and learning)."""
    cols, order = {}, order or {}
    for cost in ("Action", "Bonus action", "Reaction"):
        everything = []
        for o in options(sheet, starred):
            v = _battle_override(sheet, o["oref"])
            if o["cost"] != cost or (v == "hide" and not o["starred"]):
                continue
            everything.append({**o, "common": o["common"] if v is None else v == "common"})
        shown = [o for o in everything if o["starred"]] + ([] if pinned_only else [o for o in everything if o["common"] and not o["starred"]])
        if order.get(cost):
            rank = {k: i for i, k in enumerate(order[cost])}
            shown.sort(key=lambda o: rank.get(o["key"], len(rank)))  # stable: new ones keep their place after
        cols[cost] = {"shown": shown[:COLUMN_LIMIT], "all": everything, "count": len(everything)}
    rules = class_rules.turn(sheet)
    for cost, col in cols.items():
        col["notes"] = rules["notes"][cost]
    if rules["attacks"] > 1:
        cols["Action"]["sub"] = f"One per turn · the Attack action makes {rules['attacks']} attacks"
        cols["Action"]["notes"].insert(0, f"From {rules['attacks_from']}")
    return cols


def find(sheet: dict, ref: str) -> dict | None:
    """The thing a pin or reminder points at, wherever it lives on the sheet. A spell's key looks in
    the spells first: a situational rule can share it (Absorb Elements' "Reaction spell: …"). An item's
    action ("item:12#turn-invisible") opens the item."""
    ref = ref.split("#", 1)[0]
    order = ("situational", "actions", "spells", "features", "inventory", "creatures", "attacks")
    if ref.startswith("spell:"):
        order = ("spells",) + tuple(s for s in order if s != "spells")
    for section in order:
        for x in sheet.get(section) or []:
            if x.get("key") == ref:
                return {**x, "section": section}
    for book in sheet.get("spellbook") or []:  # spells you could prepare but don't have yet
        for x in book["spells"]:
            if x.get("key") == ref:
                return {**x, "section": "spells", "class": book["class"]}
    return None


def detail(sheet: dict, ref: str, starred: set[str] = frozenset()) -> dict | None:
    """Everything the side panel shows for one thing: the thing itself, how it
    works on a turn (if it's an option), and where it comes from."""
    x = find(sheet, ref)
    if x is None and not ref.startswith(("attack:", "rule:")):
        return None
    opt = next((o for o in options(sheet, set(starred)) if o["key"] == ref), None)
    if x is None:
        x = {"name": opt["name"], "section": "attacks", "text": opt.get("text", "")} if opt else None
    if x is None:
        return None
    if x["section"] == "situational":  # point at the feature or spell it comes from
        x["related"] = next((f for f in sheet.get("features") or [] if f["name"] == x.get("source")), None)
    if x["section"] == "spells":
        for book in sheet.get("spellbook") or []:
            same = next((s for s in book["spells"] if s["name"] == x["name"]), None)
            if same:
                x.setdefault("state", same["state"])
                x.setdefault("class", book["class"])
    roll = opt
    if roll is None and x["section"] in ("spells", "inventory", "attacks", "actions", "features", "creatures"):
        weapon = next((a for a in sheet.get("attacks") or [] if a["name"] == x.get("name")), None)
        effect = x.get("damage") or (f"heals {x['healing']}" if x.get("healing") else "")
        recipe = house_rules.spell(x.get("name") or "") or x.get("roll") if x["section"] == "spells" else rr.item(x.get("name") or "")
        roll = rollable({"name": x.get("name") or "", "kind": "spell" if x["section"] == "spells" else "item", "recipe": recipe,
                         "hit": x.get("attack") or x.get("save") or (weapon or {}).get("to_hit", ""), "meta": effect if isinstance(effect, str) else "",
                         "summary": x.get("summary") or "", "text": x.get("text") or "", "adv": []})
    if roll is not None and not (roll.get("dice") or (roll.get("hit") or "")[:1] in ("+", "-", "\u2212")):
        roll = None
    return {"x": x, "opt": opt, "section": x["section"], "roll": roll}


def label_for(sheet: dict, ref: str) -> str:
    """Short text for Reminders."""
    x = find(sheet, ref)
    if not x:
        return ""
    if x["section"] == "situational":
        return x["text"] + (f" ({x['source']})" if x["source"] else "")
    if x["section"] == "creatures":
        return f"{x['name']} ({x.get('group') or 'form'}, CR {x.get('cr')})"
    detail = x.get("summary") or x.get("text") or ""
    detail = re.split(r"(?<=[.!?])\s", detail, maxsplit=1)[0]
    return f"{x['name']}: {detail}" if detail else x["name"]


def reminders(sheet: dict, remind: dict[str, str], order: list[str] | None = None, notes: dict[str, str] | None = None) -> list[dict]:
    """Reminders in the player's order (drag and drop), else the order they were
    added; today's sheet text when the thing still exists, the saved label otherwise,
    with the player's note on why."""
    notes = notes or {}
    out = [{"ref": ref, "text": label_for(sheet, ref) or saved, "note": notes.get(ref, "")}
           for ref, saved in remind.items() if label_for(sheet, ref) or saved]
    if order:
        rank = {k: i for i, k in enumerate(order)}
        out.sort(key=lambda r: rank.get(r["ref"], len(rank)))
    return out


# ------------------------------------------------------------------ party


def party_row(character, sheet: dict | None) -> dict:
    if not sheet:
        return {"c": character, "sheet": None}
    saves = sorted(sheet["saves"], key=lambda s: -s["bonus"])[:2]
    ss = sheet.get("spell_slots") or {}
    slots = [{"label": ordinal(s["level"]), "uses": {"left": s["max"] - s["used"], "max": s["max"]}} for s in ss.get("slots") or []]
    if ss.get("pact"):
        p = ss["pact"]
        slots.append({"label": f"Pact ({ordinal(p['level'])})", "uses": {"left": p["max"] - p["used"], "max": p["max"]}})
    return {
        "c": character,
        "sheet": sheet,
        "classes": " / ".join(f"{k['name']} {k['level']}" for k in sheet["classes"]),
        "best_saves": ", ".join(f"{s['short']} {s['label']}" for s in saves),
        "top_saves": saves,
        # limited uses (Wild Shape, Focus Points…) and spell slots, each with dots for what's left
        "resources": [{"name": a["name"], "uses": a["uses"]} for a in sheet.get("actions") or []
                      if a.get("uses") and a.get("source") in ("class", "feat", "race")],
        "slots": slots,
    }


SPELL_GROUPS = [
    ("Healing and recovery", lambda s: bool(s["healing"]) or "Healing" in s["tags"]),
    ("Rituals (no slot needed, +10 minutes)", lambda s: s["ritual"]),
    ("Reactions", lambda s: s["casting_time"] == "Reaction"),
    ("Protection and buffs", lambda s: bool({"Buff", "Warding"} & set(s["tags"]))),
    ("Control and debuffs", lambda s: bool({"Control", "Debuff"} & set(s["tags"]))),
    ("Damage", lambda s: bool(s["damage"]) or "Damage" in s["tags"]),
    ("Getting around", lambda s: bool({"Movement", "Teleportation"} & set(s["tags"]))),
    ("Finding things out", lambda s: bool({"Detection", "Foreknowledge", "Scrying", "Communication"} & set(s["tags"]))),
]


def _panel_url(character, key: str) -> str:
    return f"/characters/{character.id}/detail?ref={quote(key, safe='')}"


def pooled_spells(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Everyone's spells for planning: each spell once, with who can cast it.
    `url` opens the first caster's side panel; each `who` opens that caster's."""
    spells: dict[str, dict] = {}
    for r in rows:
        if not r["sheet"]:
            continue
        who = r["c"].name
        for sp in r["sheet"]["spells"]:
            entry = spells.setdefault(sp["name"], {**sp, "who": [], "url": _panel_url(r["c"], sp["key"])})
            note = f"{sp['uses']['max']}/{sp['uses']['reset']}" if sp["uses"] and not sp["uses_slot"] else (
                "item" if sp["sources"] == ["Item"] else "")
            entry["who"].append({"label": f"{who} ({note})" if note else who, "url": _panel_url(r["c"], sp["key"])})
    groups, placed = [], set()
    for title, test in SPELL_GROUPS:
        found = [s for n, s in sorted(spells.items(), key=lambda kv: (kv[1]["level"], kv[0])) if n not in placed and test(s)]
        placed |= {s["name"] for s in found}
        if found:
            groups.append((title, found))
    rest = [s for n, s in sorted(spells.items(), key=lambda kv: (kv[1]["level"], kv[0])) if n not in placed]
    if rest:
        groups.append(("Everything else", rest))
    return groups


def pooled_items(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Magic items and consumables across the party, with who carries them."""
    items: dict[tuple, dict] = {}
    for r in rows:
        if not r["sheet"]:
            continue
        who = r["c"].name
        for it in r["sheet"]["inventory"]:
            if not (it["magic"] or it["battle"]):
                continue
            ch = it["charges"]
            if "healing" in it["name"].lower() or "regain" in it["summary"].lower()[:120]:
                group = "Healing"
            elif ch and ch["reset"] == "Used up":
                group = "One use"
            elif it["type"] in ("Potion", "Scroll"):
                group = "One use"
            elif it["attunement"] == "required":
                group = "Needs attunement"
            elif ch:
                group = "Charges"
            else:
                group = "Other magic items"
            entry = items.setdefault((group, it["name"]), {"name": it["name"], "summary": it["summary"], "who": [],
                                                           "url": _panel_url(r["c"], it["key"])})
            label = who + (f" ×{it['quantity']}" if it["quantity"] > 1 else "")
            if ch and ch["reset"] != "Used up":
                label += f" {ch['left']}/{ch['max']}"
            entry["who"].append({"label": label, "url": _panel_url(r["c"], it["key"])})
    order = ["Healing", "One use", "Charges", "Needs attunement", "Other magic items"]
    return [(g, sorted((v for (gg, _), v in items.items() if gg == g), key=lambda v: v["name"])) for g in order
            if any(gg == g for gg, _ in items)]


def party_coins(rows: list[dict]) -> int:
    rate = {"pp": 10, "gp": 1, "ep": 0.5, "sp": 0.1, "cp": 0.01}
    return int(sum(v * rate.get(k, 0) for r in rows if r["sheet"] for k, v in r["sheet"]["currency"].items()))


def granted_spells(sheet: dict) -> list[dict]:
    """Spells from species, feats, items and class features that aren't on a class's spell list."""
    classes = {b["class"] for b in sheet.get("spellbook") or []}
    in_books = {sp["name"] for b in sheet.get("spellbook") or [] for sp in b["spells"] if sp["state"] != "available"}
    return [sp for sp in sheet.get("spells") or [] if not (set(sp["sources"]) & classes) and sp["name"] not in in_books]


# ------------------------------------------------------------------ admin regrouping
# An admin can correct how askdnd groups anything from D&D Beyond. Corrections
# are stored by name (tool_corrections) so they apply to every character.

ITEM_GROUPS = [("battle", "Usable in battle"), ("equipped", "Equipped"), ("Weapons", "Weapons"), ("Armor", "Armor"),
               ("Magic items", "Magic items"), ("Potions and scrolls", "Potions and scrolls"), ("Gear", "Gear")]
OVERRIDE_CHOICES = {
    "hide": [("hide", "Hidden everywhere in askdnd")],
    "cost": [("Action", "Action"), ("Bonus action", "Bonus action"), ("Reaction", "Reaction"), ("Other", "Other (not on your turn)")],
    "battle": [("common", "Shown on Battle"), ("normal", "Only in See all"), ("hide", "Not on Battle")],
    "feature_group": [("use", "Things you can use"), ("passive", "Always on (in your numbers)")],
    "situ_group": [("situational", "Situational"), ("in_numbers", "Already in your numbers")],
    "item_group": ITEM_GROUPS,
}
# Rule-term underlines (set from the term's pop-up, not the regrouping box); here so Manage › Characters can label them.
TERM_CHOICES = {"underline": [("on", "Underlined"), ("off", "Not underlined")]}
FIELD_LABELS = {"hide": "Show in askdnd", "cost": "Section (what it costs)", "battle": "On Battle",
                "feature_group": "Features group", "situ_group": "Situational group", "item_group": "Inventory group",
                "underline": "Underlined in descriptions"}
ITEM_KINDS = {"Other Gear": "Gear", "Wondrous item": "Wondrous", "Rod": "Rod, staff or wand", "Staff": "Rod, staff or wand", "Wand": "Rod, staff or wand"}
# By D&D Beyond's item type, before its category: ammunition is "Other Gear" there (tool correction built in, 2026-10-23)
TYPE_GROUPS = {"Ammunition": "Weapons"}
CATEGORY_GROUPS = {"Weapon": "Weapons", "Armor": "Armor", "Wondrous item": "Magic items", "Ring": "Magic items", "Rod": "Magic items",
                   "Staff": "Magic items", "Wand": "Magic items", "Potion": "Potions and scrolls", "Scroll": "Potions and scrolls"}


def override_ref(x: dict, section: str | None = None) -> str:
    """The name-based handle an override is stored under (same for every character)."""
    section = section or x.get("section", "")
    name = x.get("base_name") or x.get("name") or ""
    prefix = {"features": "feature", "inventory": "item", "attacks": "attack", "spells": "spell", "actions": "action",
              "creatures": "form"}.get(section)
    return f"{prefix}:{name}" if prefix else x.get("key", "")


def fields_for(section: str, opt: dict | None) -> list[str]:
    """Which corrections make sense for one thing (every thing can be hidden)."""
    fields = ["hide"]
    if opt:
        fields += ["cost", "battle"]
    fields += {"features": ["feature_group"], "situational": ["situ_group"], "inventory": ["item_group"]}.get(section, [])
    return fields


TURN_COSTS = ("Action", "Bonus action", "Reaction")
OPTION_KINDS = (("attack", "Attacks"), ("feature", "Features"), ("spell", "Spells"), ("item", "Items"), ("rule", "Rules"))


def option_groups(opts: list[dict]) -> list[dict]:
    """Battle's "See all" and "+ Add" panels, bucketed (Brett, 2026-10-22: the lists grow every level):
    attacks, features, spells by level, items, then rules everyone has (Opportunity Attack…). Each group
    says its kind, for the panel's filter chips."""
    def kind(o):
        return "rule" if o["key"].startswith("rule:") and o["kind"] == "feature" else o["kind"]
    out = []
    for k, label in OPTION_KINDS:
        mine = [o for o in opts if kind(o) == k]
        if k == "spell":
            for lvl in sorted({o.get("level") or 0 for o in mine}):
                rows = [o for o in mine if (o.get("level") or 0) == lvl]
                out.append({"kind": k, "label": "Cantrips" if not lvl else f"{ordinal(lvl)}-level spells", "opts": rows})
        elif mine:
            out.append({"kind": k, "label": label, "opts": mine})
    return out
# A feature's own words, when no Battle option carries it (Wild Companion: "As a Magic action, …")
TURN_WORDS = (("Reaction", re.compile(r"\b(?:as|take|use your|uses? a) (?:a )?Reaction\b", re.I)),
              ("Bonus action", re.compile(r"\b(?:as|take|use) a Bonus Action\b", re.I)),
              ("Action", re.compile(r"\b(?:as|take) (?:a|an|the \w+) (?:Magic )?action\b|\bMagic action\b", re.I)))


def feature_rows(sheet: dict, opts: list[dict]) -> list[dict]:
    """Sheet › Features as list rows (_feature_list.html): what each feature is used as on a turn (from the
    options it gives, matched by name: "Wild Shape", "Wild Shape: Circle Forms"…) and its limited uses."""
    def mine(name: str, n: str) -> bool:
        return name == n or name.startswith(n + ":") or name.startswith(n + " (")
    out = []
    for f in sheet.get("features") or []:
        n = f["name"]
        costs = {o["cost"] for o in opts if mine(o["name"], n)}
        turn = [c for c in TURN_COSTS if c in costs]
        if not turn and f.get("use"):
            text = f"{f.get('summary') or ''} {f.get('text') or ''}"
            turn = [next((cost for cost, rx in TURN_WORDS if rx.search(text)), "Other")]
        turn = turn or ["Always on"]
        uses = next((a["uses"] for a in sheet.get("actions") or [] if mine(a["name"], n) and a.get("uses")), None)
        out.append({**f, "turn": turn, "uses": uses})
    return out


def apply_overrides(sheet: dict, overrides: dict[tuple[str, str], str]) -> dict:
    """Return the sheet with admin regrouping applied."""
    if not sheet:
        return sheet
    sheet = dict(sheet)
    get = lambda x, section, field: overrides.get((override_ref(x, section), field))  # noqa: E731
    for section in ("features", "situational", "inventory", "creatures", "attacks", "actions", "spells"):
        sheet[section] = [x for x in sheet.get(section) or [] if get(x, section, "hide") != "hide"]
    sheet["spellbook"] = [{**b, "spells": [x for x in b["spells"] if get(x, "spells", "hide") != "hide"]}
                          for b in sheet.get("spellbook") or []]
    sheet["features"] = [{**f, "use": f["use"] if get(f, "features", "feature_group") is None else get(f, "features", "feature_group") == "use"}
                         for f in sheet["features"]]
    sheet["situational"] = [{**x, "in_numbers": (x["kind"] == "bonus") if get(x, "situational", "situ_group") is None
                             else get(x, "situational", "situ_group") == "in_numbers"} for x in sheet["situational"]]
    items = []
    for it in sheet["inventory"]:
        group = get(it, "inventory", "item_group") or (
            "battle" if it["battle"] else "equipped" if it["equipped"]
            else TYPE_GROUPS.get(it.get("type") or "") or CATEGORY_GROUPS.get(it.get("category"), "Gear"))
        items.append({**it, "group": group, "battle": group == "battle",
                      # the Inventory list's filter values (_item_list.html)
                      "kind_label": "Custom" if it.get("custom") else ITEM_KINDS.get(it.get("category") or "", it.get("category") or "Gear"),
                      "use_labels": (["Usable in battle"] if group == "battle" else []) + (["Has uses"] if it.get("charges") else []),
                      "attune_label": {"attuned": "Attuned", "required": "Needs attunement"}.get(it.get("attunement") or "", "")})
    sheet["inventory"] = items
    sheet["_overrides"] = {f"{r}|{fld}": v for (r, fld), v in overrides.items()}
    return sheet
