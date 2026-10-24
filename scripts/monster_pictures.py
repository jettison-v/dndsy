"""Refresh app/data/monster_pictures.json: links to D&D Beyond's art for the SRD's Beasts (Wild Shape's forms).

Each picture is the 2024 Monster Manual entry's art on D&D Beyond, looked up by name; we store the link, never
the image. The stat blocks themselves come from the SRD (app/data/srd/monsters.json, scripts/srd_import.py).

    uv run python scripts/monster_pictures.py
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rules_data  # noqa: E402

DDB_SEARCH = "https://monster-service.dndbeyond.com/v1/Monster?search={q}&skip=0&take=20"
MM_2024 = 147  # D&D Beyond's source id for the 2024 Monster Manual


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "askdnd (private table companion)"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def ddb_art(name: str) -> dict:
    try:
        found = get(DDB_SEARCH.format(q=urllib.parse.quote(name))).get("data") or []
    except Exception:  # noqa: BLE001 - a missing picture is fine
        return {}
    m = next((m for m in found if m.get("name") == name and m.get("sourceId") == MM_2024), None)
    return {"image": m.get("avatarUrl") or "", "ddb_url": m.get("url") or "", "ddb_id": m.get("id")} if m and m.get("avatarUrl") else {}


def main() -> None:
    data = json.loads(rules_data.PICTURES.read_text(encoding="utf-8"))
    pictures = {}
    for m in rules_data.srd("monster"):
        if m["type"] == "Beast":
            art = ddb_art(m["name"])
            if art:
                pictures[m["key"]] = art
            time.sleep(0.2)  # be polite to D&D Beyond
    data["pictures"] = dict(sorted(pictures.items()))
    rules_data.PICTURES.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(pictures)} pictures written to {rules_data.PICTURES}")


if __name__ == "__main__":
    main()
