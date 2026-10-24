"""Check scripts/srd_import.py's reading of the SRD against Open5e's conversion (srd-2024).

Two readings made independently should agree on the numbers; where they don't, one of them misread
the book, and the PDF settles it. Run through `uv run scripts/srd_import.py --compare`. Open5e's copy is
of SRD 5.2, ours of 5.2.1, so a few differences are the 5.2.1 corrections.
"""

import json
import re
import time
import urllib.request

API = "https://api.open5e.com/v2/{kind}/?document__key=srd-2024&limit=100"
ABBR = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}


def fetch(kind: str) -> list[dict]:
    url, out = API.format(kind=kind), []
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "askdnd (private table companion)"})
        data = json.loads(urllib.request.urlopen(req, timeout=60).read())
        out += [r for r in data["results"] if (r.get("document") or {}).get("key", "srd-2024") == "srd-2024"]
        url = data.get("next")
        time.sleep(0.1)
    return out


def _name(n: str) -> str:
    return n.replace("’", "'").lower()


def _dice(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").replace("−", "-"))


def monsters(ours: list[dict], theirs: list[dict]) -> list[str]:
    out = []
    by = {_name(c["name"]): c for c in theirs}
    for m in ours:
        c = by.get(_name(m["name"]))
        if not c:
            out.append(f"monster only here: {m['name']}")
            continue
        speed = {k: v for k, v in (c.get("speed") or {}).items() if k in ("walk", "burrow", "climb", "fly", "swim") and v}
        checks = {
            "AC": (m["ac"], c["armor_class"]), "HP": (m["hp"], c["hit_points"]),
            "hit dice": (_dice(m["hit_dice"]), _dice(c.get("hit_dice"))), "CR": (m["cr"], float(c["challenge_rating"])),
            "XP": (m["xp"], c.get("experience_points")), "initiative": (m["initiative"], c.get("initiative_bonus")),
            "speed": (m["speed"], speed), "size": (m["size"], (c.get("size") or {}).get("name")),
            "abilities": (m["abilities"], {ABBR[k]: v for k, v in c["ability_scores"].items()}),
            "saves": (m["saves"], {ABBR[k]: v for k, v in (c.get("saving_throws_all") or {}).items()}),
            "skills": ({k.lower(): v for k, v in m["skills"].items()}, {k.replace("_", " "): v for k, v in (c.get("skill_bonuses") or {}).items()}),
            "passive Perception": (m["passive_perception"], c.get("passive_perception")),
            "actions": (len(m["actions"]) + len(m["bonus_actions"]) + len(m["reactions"]) + len(m["legendary_actions"]), len(c.get("actions") or [])),
        }
        out += [f"{m['name']}: {k} {a!r} here, {b!r} in Open5e" for k, (a, b) in checks.items() if a != b]
    names = {_name(m["name"]) for m in ours}
    out += [f"monster only in Open5e: {c['name']}" for c in theirs if _name(c["name"]) not in names]
    return out


def spells(ours: list[dict], theirs: list[dict]) -> list[str]:
    out = []
    by = {_name(s["name"]): s for s in theirs}
    for s in ours:
        o = by.get(_name(s["name"]))
        if not o:
            out.append(f"spell only here: {s['name']}")
            continue
        comps = [c for c, on in (("V", o.get("verbal")), ("S", o.get("somatic")), ("M", o.get("material"))) if on]
        checks = {
            "level": (s["level"], o["level"]), "school": (s["school"].lower(), (o.get("school") or {}).get("key")),
            "classes": (sorted(s["classes"]), sorted(c["name"] for c in o.get("classes") or [])),
            "ritual": (s["ritual"], o.get("ritual")), "concentration": (s["concentration"], o.get("concentration")),
            "components": (s["components"], comps), "range": (s["range"].lower(), (o.get("range_text") or "").lower()),
            "material": (s["material"].lower().rstrip("."), (o.get("material_specified") or "").lower().rstrip(".")),
        }
        out += [f"{s['name']}: {k} {a!r} here, {b!r} in Open5e" for k, (a, b) in checks.items() if a != b]
    names = {_name(s["name"]) for s in ours}
    out += [f"spell only in Open5e: {o['name']}" for o in theirs if _name(o["name"]) not in names]
    return out


def magic_items(ours: list[dict], theirs: list[dict]) -> list[str]:
    """Open5e makes one item per variant ("Flame Tongue Longsword"); ours are as the book prints them."""
    out = []
    by = {_name(i["name"]): i for i in theirs}
    for it in ours:
        o = by.get(_name(it["name"]))
        if not o:
            continue  # a variant item: checked by eye
        rarity = ((o.get("rarity") or {}).get("name") or "").lower()
        checks = {"rarity": (it["rarity"].lower(), rarity), "attunement": (it["attunement"], bool(o.get("requires_attunement")))}
        out += [f"{it['name']}: {k} {a!r} here, {b!r} in Open5e" for k, (a, b) in checks.items() if a != b]
    return out


def report(mons: list[dict], sp: list[dict], items: list[dict]) -> None:
    diffs = monsters(mons, fetch("creatures")) + spells(sp, fetch("spells")) + magic_items(items, fetch("magicitems"))
    print(f"\n{len(diffs)} differences from Open5e:")
    for d in diffs:
        print("  " + d)
