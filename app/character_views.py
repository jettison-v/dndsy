"""Shapes the parsed D&D Beyond sheets (app/ddb.py) into what the Battle,
Character and Party pages show. Plain functions over the summary dicts, so
they're easy to test without a browser."""

import re

COSTS = ["Action", "Bonus action", "Reaction", "Other"]
COLUMN_LIMIT = 7  # options shown in a Battle column before "See all"


def _cost(activation: str) -> str:
    return activation if activation in ("Action", "Bonus action", "Reaction") else "Other"


def options(sheet: dict, starred: set[str] | None = None) -> list[dict]:
    """Everything the character can do on a turn, as one list: attacks, spells,
    features and items, each with what it costs (action, bonus action…)."""
    starred = starred or set()
    attacks = {a["name"]: a for a in sheet.get("attacks") or []}
    out = []

    def add(**o):
        o.setdefault("tags", [])
        o.setdefault("uses", None)
        o.setdefault("hit", "")
        o.setdefault("meta", "")
        o.setdefault("text", "")
        o.setdefault("summary", "")
        o["starred"] = o["key"] in starred
        o.setdefault("oref", o["key"])
        moved = (sheet.get("_overrides") or {}).get(f"{o['oref']}|cost")
        if moved:
            o["cost"] = moved
        out.append(o)

    for a in sheet.get("attacks") or []:
        add(key=a["key"], oref=f"attack:{a['name']}", kind="attack", cost="Action", name=a["name"], hit=a["to_hit"],
            meta=" · ".join(x for x in (a["range"], a["damage"], ", ".join(a["properties"])) if x),
            common=True)
    for sp in sheet.get("spells") or []:
        cost = sp["casting_time"] if sp["casting_time"] in ("Action", "Bonus action", "Reaction") else None
        if not cost:
            continue
        level = "cantrip" if not sp["level"] else f"level {sp['level']}"
        effect = sp["damage"] or (f"heals {sp['healing']}" if sp["healing"] else "")
        tags = [level] + (["Conc."] if sp["concentration"] else []) + ([f"{sp['uses']['max']} free"] if sp["uses"] else [])
        add(key=sp["key"], kind="spell", cost=cost, name=sp["name"], hit=sp["attack"] or sp["save"], tags=tags,
            meta=" · ".join(x for x in (sp["range"], effect, sp["trigger"] if cost == "Reaction" else "") if x),
            text=sp.get("text") or sp["summary"], summary=sp["summary"],
            common=cost == "Reaction" or (not sp["level"] and bool(sp["attack"] or sp["save"]) and bool(sp["damage"])))
    for a in sheet.get("actions") or []:
        cost = _cost(a["activation"])
        hit, meta, unarmed = "", "", a["name"].startswith("Unarmed Strike")
        if unarmed:
            if a["name"] != "Unarmed Strike" or cost == "Action":
                continue  # the attack is listed once, from the attacks; "(Dex.)" variants are the same strike
            u = attacks.get("Unarmed Strike") or {}
            hit, meta = u.get("to_hit", ""), u.get("damage", "")
        add(key=a["key"], kind="feature", cost=cost, name=a["name"], hit=hit, meta=meta, uses=a["uses"], text=a["text"],
            summary=a.get("summary", ""),
            common=not a.get("rule") and (unarmed or cost == "Reaction" or bool(a["uses"] and a["source"] in ("class", "feat", "race"))))
    for it in sheet.get("inventory") or []:
        if not it["battle"]:
            continue
        uses = it["charges"] if it["charges"] and it["charges"]["reset"] != "Used up" else None
        first = re.split(r"(?<=[.!?])\s", it["summary"] or "", maxsplit=1)[0]
        add(key=it["key"], oref=f"item:{it['base_name']}", kind="item", cost="Action", name=f"Use an item: {it['name']}", uses=uses,
            tags=[f"×{it['quantity']}"] if it["quantity"] > 1 else [], meta=first if len(first) <= 120 else first[:119].rsplit(" ", 1)[0] + "…",
            text=it.get("text") or it["summary"], summary=it["summary"], common="healing" in it["name"].lower())
    return out


def _battle_override(sheet: dict, oref: str) -> str | None:
    return (sheet.get("_overrides") or {}).get(f"{oref}|battle")


def battle_columns(sheet: dict, starred: set[str], order: dict[str, list[str]] | None = None) -> dict:
    """Action / Bonus action / Reaction columns: starred first, then the common
    options (or the player's own drag-and-drop order); the rest is behind "See all"."""
    cols, order = {}, order or {}
    for cost in ("Action", "Bonus action", "Reaction"):
        everything = []
        for o in options(sheet, starred):
            v = _battle_override(sheet, o["oref"])
            if o["cost"] != cost or (v == "hide" and not o["starred"]):
                continue
            everything.append({**o, "common": o["common"] if v is None else v == "common"})
        shown = [o for o in everything if o["starred"]] + [o for o in everything if o["common"] and not o["starred"]]
        if order.get(cost):
            rank = {k: i for i, k in enumerate(order[cost])}
            shown.sort(key=lambda o: rank.get(o["key"], len(rank)))  # stable: new ones keep their place after
        cols[cost] = {"shown": shown[:COLUMN_LIMIT], "all": everything, "count": len(everything)}
    return cols


def find(sheet: dict, ref: str) -> dict | None:
    """The thing a star or reminder points at, wherever it lives on the sheet."""
    for section in ("situational", "actions", "spells", "features", "inventory", "creatures", "attacks"):
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
    if x is None and not ref.startswith("attack:"):
        return None
    opt = next((o for o in options(sheet, set(starred)) if o["key"] == ref), None)
    if x is None:
        x = {"name": opt["name"], "section": "attacks"} if opt else None
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
    return {"x": x, "opt": opt, "section": x["section"]}


def label_for(sheet: dict, ref: str) -> str:
    """Short text for Easy to forget."""
    x = find(sheet, ref)
    if not x:
        return ""
    if x["section"] == "situational":
        return x["text"] + (f" ({x['source']})" if x["source"] else "")
    detail = x.get("summary") or x.get("text") or ""
    detail = re.split(r"(?<=[.!?])\s", detail, maxsplit=1)[0]
    return f"{x['name']}: {detail}" if detail else x["name"]


def reminders(sheet: dict, remind: dict[str, str], order: list[str] | None = None) -> list[dict]:
    """Reminders in the player's order (drag and drop), else the order they were
    added; today's sheet text when the thing still exists, the saved label otherwise."""
    out = [{"ref": ref, "text": label_for(sheet, ref) or saved} for ref, saved in remind.items() if label_for(sheet, ref) or saved]
    if order:
        rank = {k: i for i, k in enumerate(order)}
        out.sort(key=lambda r: rank.get(r["ref"], len(rank)))
    return out


# ------------------------------------------------------------------ party


def party_row(character, sheet: dict | None) -> dict:
    if not sheet:
        return {"c": character, "sheet": None}
    saves = sorted(sheet["saves"], key=lambda s: -s["bonus"])[:2]
    big = [r for r in sheet.get("resources") or [] if not r.get("text")][:2]
    slots = next((r["text"] for r in sheet.get("resources") or [] if r.get("text")), "")
    return {
        "c": character,
        "sheet": sheet,
        "classes": " / ".join(f"{k['name']} {k['level']}" for k in sheet["classes"]),
        "best_saves": ", ".join(f"{s['short']} {s['label']}" for s in saves),
        "resources": " · ".join([f"{r['name']} {r['left']}/{r['max']}" for r in big] + ([slots] if slots else [])),
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


def pooled_spells(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Everyone's spells for planning: each spell once, with who can cast it."""
    spells: dict[str, dict] = {}
    for r in rows:
        if not r["sheet"]:
            continue
        who = r["c"].entity.name
        for sp in r["sheet"]["spells"]:
            entry = spells.setdefault(sp["name"], {**sp, "who": []})
            note = f"{sp['uses']['max']}/{sp['uses']['reset']}" if sp["uses"] and not sp["uses_slot"] else (
                "item" if sp["sources"] == ["Item"] else "")
            entry["who"].append(f"{who} ({note})" if note else who)
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
        who = r["c"].entity.name
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
            entry = items.setdefault((group, it["name"]), {"name": it["name"], "summary": it["summary"], "who": []})
            label = who + (f" ×{it['quantity']}" if it["quantity"] > 1 else "")
            if ch and ch["reset"] != "Used up":
                label += f" {ch['left']}/{ch['max']}"
            entry["who"].append(label)
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
# are stored by name (sheet_overrides) so they apply to every character.

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
FIELD_LABELS = {"hide": "Show in askdnd", "cost": "Section (what it costs)", "battle": "On the Battle page",
                "feature_group": "Features group", "situ_group": "Situational group", "item_group": "Inventory group"}
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
            "battle" if it["battle"] else "equipped" if it["equipped"] else CATEGORY_GROUPS.get(it.get("category"), "Gear"))
        items.append({**it, "group": group, "battle": group == "battle"})
    sheet["inventory"] = items
    sheet["_overrides"] = {f"{r}|{fld}": v for (r, fld), v in overrides.items()}
    return sheet
