"""The numbers the D&D Beyond bridge follows on a character (app/ddb_bridge.py): how to read each, how to say it changed,
and the request the sheet itself sends to change it.

A field is a key: "hp", "item:<inventory id>". `steps(field)` says where D&D Beyond keeps it in a character's JSON, as
steps the extension follows too (extension/askdnd-bridge/ddb-page.js `pick`), so askdnd's read-back, the extension's
check before writing and its check of the open sheet always read a value the same way:

- a key reads a dict's entry ("removedHitPoints"),
- {"id": X} picks the element of a list whose id is X,
- {"read": {name: steps}} reads several values at once, as a dict,
- {"or": X} stands for a value D&D Beyond left out (it leaves out temporary hit points when there are none).

Anything else missing on D&D Beyond reads as None.
"""

HP_PATH = "/character/v5/life/hp/damage-taken"
ITEM_PATH = "/character/v5/inventory/item/quantity"
WRITES = {("PUT", HP_PATH), ("PUT", ITEM_PATH)}  # the only requests the extension makes (and its own list matches)


def pick(data, steps: list):
    """Follow `steps` into a D&D Beyond character (or into what the open sheet holds); None where it stops."""
    v = data
    for s in steps:
        if isinstance(s, dict) and "or" in s:
            v = s["or"] if v is None else v
        elif v is None:
            continue
        elif isinstance(s, str):
            v = v.get(s) if isinstance(v, dict) else None
        elif "id" in s:
            v = next((x for x in v if isinstance(x, dict) and x.get("id") == s["id"]), None) if isinstance(v, list) else None
        elif "read" in s:
            v = {k: pick(v, sub) for k, sub in s["read"].items()}
    return v


def steps(field: str) -> list:
    kind, _, arg = field.partition(":")
    if kind == "hp":
        return [{"read": {"removedHitPoints": ["removedHitPoints", {"or": 0}], "temporaryHitPoints": ["temporaryHitPoints", {"or": 0}]}}]
    if kind == "item":
        return ["inventory", {"id": int(arg)}, "quantity"]
    raise ValueError(f"Not a field the bridge follows: {field}")


def value(data: dict, field: str):
    return pick(data, steps(field))


def tracked(data: dict | None) -> dict:
    """Every field the bridge follows on this character, with its value on D&D Beyond."""
    if not data:
        return {}
    out = {"hp": value(data, "hp")}
    for i in data.get("inventory") or []:
        if isinstance(i, dict) and i.get("id") is not None:
            out[f"item:{i['id']}"] = value(data, f"item:{i['id']}")
    return out


def item_name(data: dict | None, item_id: int) -> str:
    i = pick(data or {}, ["inventory", {"id": item_id}])
    return ((i or {}).get("definition") or {}).get("name") or "an item"


def name(data: dict | None, field: str) -> str:
    """What a person calls it: "hit points", "Potion of Healing"."""
    kind, _, arg = field.partition(":")
    return "hit points" if kind == "hp" else item_name(data, int(arg))


def max_hp(summary: dict | None) -> int:
    return ((summary or {}).get("hit_points") or {}).get("max") or 0


def show(data: dict | None, field: str, v, max_hit_points: int = 0) -> str:
    """A value as the log and the make-by-hand list say it: "hit points 31 + 5 temporary", "Candle ×9"."""
    if field == "hp":
        if v is None:
            return "hit points ?"
        temp = v["temporaryHitPoints"]
        return f"hit points {max_hit_points - v['removedHitPoints']}" + (f" + {temp} temporary" if temp else "")
    return f"{name(data, field)} ×{v}"


def changed(data: dict | None, field: str, before, after, max_hit_points: int = 0) -> str:
    """One change seen on D&D Beyond, for the log: "hit points 37 → 31", "Potion of Healing ×2 → ×3"."""
    if field == "hp":
        if before["removedHitPoints"] == after["removedHitPoints"]:
            return f"temporary hit points {before['temporaryHitPoints']} → {after['temporaryHitPoints']}"
        a, b = show(data, field, before, max_hit_points), show(data, field, after, max_hit_points)
        return f"{a} → {b.removeprefix('hit points ')}"
    return f"{name(data, field)} ×{before} → ×{after}"


def write(ddb_id: int, field: str, v) -> dict:
    """The request the sheet itself sends to set this field to `v`."""
    kind, _, arg = field.partition(":")
    if kind == "hp":
        return {"method": "PUT", "path": HP_PATH, "body": {"characterId": ddb_id, **v}}
    if kind == "item":
        return {"method": "PUT", "path": ITEM_PATH, "body": {"characterId": ddb_id, "id": int(arg), "quantity": v}}
    raise ValueError(f"Not a field the bridge writes: {field}")
