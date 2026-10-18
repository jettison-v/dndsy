"""Refresh app/data/beasts_2024.json: the Beasts a druid can choose for Wild Shape.

Stat blocks come from the System Reference Document 5.2 (the free 2024 rules, CC-BY-4.0),
read through Open5e's API. Each Beast's picture is a link to D&D Beyond's artwork for
the 2024 Monster Manual entry (looked up by name; we store the link, not the image).

    uv run python scripts/wild_shape_beasts.py
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

OPEN5E = "https://api.open5e.com/v2/creatures/?document__key=srd-2024&type=beast&limit=200"
DDB_SEARCH = "https://monster-service.dndbeyond.com/v1/Monster?search={q}&skip=0&take=20"
MM_2024 = 147  # D&D Beyond's source id for the 2024 Monster Manual
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "beasts_2024.json"
ABBR = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
SENSES = ("blindsight", "darkvision", "tremorsense", "truesight")
CR_LABELS = {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "askdnd (private table companion)"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def clean(text: str) -> str:
    return re.sub(r"_([^_]+)_", r"\1", (text or "").strip())


def limit(a: dict) -> str:
    u = a.get("usage_limits") or {}
    if u.get("type") == "PER_DAY":
        return f"{u.get('param')}/Day"
    if u.get("type") == "RECHARGE_ON_ROLL":
        return f"Recharge {u.get('param')}–6"
    return ""


def entry(a: dict) -> dict:
    name = a["name"] + (f" ({limit(a)})" if limit(a) else "")
    return {"name": name, "text": clean(a.get("desc", ""))}


def ddb_art(name: str) -> dict:
    try:
        found = get(DDB_SEARCH.format(q=urllib.parse.quote(name))).get("data") or []
    except Exception:  # noqa: BLE001 - a missing picture is fine
        return {}
    m = next((m for m in found if m.get("name") == name and m.get("sourceId") == MM_2024), None)
    return {"image": m.get("avatarUrl") or "", "ddb_url": m.get("url") or "", "ddb_id": m.get("id")} if m else {}


def beast(c: dict) -> dict:
    cr = float(c["challenge_rating"])
    speed = {k: v for k, v in (c.get("speed_all") or {}).items() if k in ("walk", "burrow", "climb", "fly", "swim") and v}
    ri = c.get("resistances_and_immunities") or {}
    senses = ", ".join(f"{s.title()} {c[s + '_range']} ft." for s in SENSES if c.get(s + "_range"))
    acts = c.get("actions") or []
    return {
        "name": c["name"],
        "cr": cr,
        "cr_label": CR_LABELS.get(cr, str(int(cr))),
        "size": (c.get("size") or {}).get("name", ""),
        "ac": c["armor_class"],
        "ac_note": c.get("armor_detail") or "",
        "hp": c["hit_points"],
        "hit_dice": c.get("hit_dice") or "",
        "speed": speed,
        "hover": bool((c.get("speed_all") or {}).get("hover")),
        "abilities": {ABBR[k]: v for k, v in c["ability_scores"].items()},
        "saves": {ABBR[k]: v for k, v in (c.get("saving_throws") or {}).items()},
        "skills": {k.replace("_", " ").title().replace("Of", "of"): v for k, v in (c.get("skill_bonuses") or {}).items()},
        "senses": senses,
        "passive_perception": c.get("passive_perception"),
        "resist": ri.get("damage_resistances_display") or "",
        "immune": ri.get("damage_immunities_display") or "",
        "vulnerable": ri.get("damage_vulnerabilities_display") or "",
        "condition_immune": ri.get("condition_immunities_display") or "",
        "traits": [{"name": t["name"], "text": clean(t.get("desc", ""))} for t in c.get("traits") or []],
        "actions": [entry(a) for a in acts if a["action_type"] == "ACTION"],
        "bonus_actions": [entry(a) for a in acts if a["action_type"] == "BONUS_ACTION"],
        "reactions": [entry(a) for a in acts if a["action_type"] == "REACTION"],
        "source": "SRD 5.2",
    }


def main() -> None:
    rows = get(OPEN5E)["results"]
    out = []
    for c in sorted(rows, key=lambda c: (float(c["challenge_rating"]), c["name"])):
        b = beast(c)
        b.update(ddb_art(b["name"]))
        out.append(b)
        time.sleep(0.2)  # be polite to D&D Beyond
    OUT.write_text(json.dumps({
        "credit": "Beast stat blocks from the System Reference Document 5.2 by Wizards of the Coast LLC, "
                  "licensed under CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/). Pictures link to D&D Beyond.",
        "beasts": out}, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} beasts ({sum(1 for b in out if b.get('image'))} with pictures) written to {OUT}")


if __name__ == "__main__":
    main()
