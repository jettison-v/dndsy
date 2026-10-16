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
        o["starred"] = o["key"] in starred
        out.append(o)

    for a in sheet.get("attacks") or []:
        add(key=a["key"], kind="attack", cost="Action", name=a["name"], hit=a["to_hit"],
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
            text=sp["summary"],
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
            common=unarmed or cost == "Reaction" or bool(a["uses"] and a["source"] in ("class", "feat", "race")))
    for it in sheet.get("inventory") or []:
        if not it["battle"]:
            continue
        uses = it["charges"] if it["charges"] and it["charges"]["reset"] != "Used up" else None
        first = re.split(r"(?<=[.!?])\s", it["summary"] or "", maxsplit=1)[0]
        add(key=it["key"], kind="item", cost="Action", name=f"Use an item: {it['name']}", uses=uses,
            tags=[f"×{it['quantity']}"] if it["quantity"] > 1 else [], meta=first if len(first) <= 120 else first[:119].rsplit(" ", 1)[0] + "…",
            text=it["summary"], common="healing" in it["name"].lower())
    return out


def battle_columns(sheet: dict, starred: set[str]) -> dict:
    """Action / Bonus action / Reaction columns: starred first, then the common
    options; everything else is behind "See all"."""
    cols = {}
    for cost in ("Action", "Bonus action", "Reaction"):
        everything = [o for o in options(sheet, starred) if o["cost"] == cost]
        shown = [o for o in everything if o["starred"]] + [o for o in everything if o["common"] and not o["starred"]]
        cols[cost] = {"shown": shown[:COLUMN_LIMIT], "all": everything, "count": len(everything)}
    return cols


def find(sheet: dict, ref: str) -> dict | None:
    """The thing a star or reminder points at, wherever it lives on the sheet."""
    for section in ("situational", "actions", "spells", "features", "inventory", "creatures", "attacks"):
        for x in sheet.get(section) or []:
            if x.get("key") == ref:
                return {**x, "section": section}
    return None


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


def reminders(sheet: dict, remind: dict[str, str]) -> list[dict]:
    """Reminders in the order they were added, using today's sheet text when the
    thing still exists and the saved label otherwise."""
    return [{"ref": ref, "text": label_for(sheet, ref) or saved} for ref, saved in remind.items() if label_for(sheet, ref) or saved]


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
