"""Save a trimmed copy of a public D&D Beyond character as a test fixture.

    uv run python -m scripts.ddb_fixture 75423618 cole          # fetch from D&D Beyond
    uv run python -m scripts.ddb_fixture path/to/saved.json cole  # or use a saved response

Writes tests/fixtures/ddb/<name>.json. Player notes are removed (app.ddb.sanitize)
and so are fields the parser never reads (images, marketing copy, the campaign
roster), so fixtures stay small. Tests never touch the network.
"""

import json
import sys
from pathlib import Path

from app import ddb

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ddb"
DROP_KEYS = {"moreDetailsUrl", "campaign", "userId", "username", "readonlyUrl",
             "providedFrom", "activeSourceCategories", "preferences", "configuration", "optionalOrigins",
             "optionalClassFeatures", "choiceDefinitions", "definitionKeyNameMap", "highlights", "classFantasy",
             "iconicGear", "equipmentDescription", "multiClassDescription", "infusionRules", "creatureRules",
             "atHigherLevels", "levelScales", "grantedModifiers", "weaponBehaviors", "lifestyle", "campaignSetting"}


def trim(value):
    if isinstance(value, dict) and isinstance(value.get("sources"), list):  # keep which book, drop the rest
        value = {**value, "sources": [{"sourceId": x.get("sourceId")} for x in value["sources"] if isinstance(x, dict)]}
    if isinstance(value, dict):
        return {k: trim(v) for k, v in value.items()
                if k not in DROP_KEYS and not k.lower().endswith(("avatarurl", "avatarid", "pageurl"))}
    if isinstance(value, list):
        return [trim(v) for v in value]
    return value


def main(source: str, name: str) -> None:
    path = Path(source)
    if path.exists():
        payload = json.loads(path.read_text())
        data = payload.get("data", payload)
    else:
        data = ddb.fetch_character(ddb.ddb_id_from(source))
    data = ddb.sanitize(data)
    portrait = (data.get("decorations") or {}).get("avatarUrl")
    data = trim(data)
    data["decorations"] = {"avatarUrl": portrait}  # the only decoration the parser reads
    for c in data.get("classes") or []:  # the class's own copy of every feature, at every level
        for key in ("definition", "subclassDefinition"):
            if isinstance(c.get(key), dict):
                c[key].pop("classFeatures", None)
                c[key].pop("description", None)
    for item in data.get("inventory") or []:
        df = item.get("definition") or {}
        if not df.get("magic"):
            df.pop("description", None)
            df.pop("snippet", None)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.json"
    out.write_text(json.dumps({"data": data}, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
