"""The numbers the D&D Beyond bridge follows on a character (app/ddb_bridge.py): how to read each, how to say it, and
the request the sheet itself sends to change it (each seen on Brett's test character's own sheet, 2026-10-27).

A field is a key: "hp", "death", "inspiration", "exhaustion", "condition:<id>", "hitdice:<class id>", "slot:<level>",
"pact:<level>", "uses:<action id>", "item:<inventory id>" (its count; None once removed),
"equipped:<id>", "attuned:<id>", "charges:<id>", "container:<id>", "coin:<cp|sp|ep|gp|pp>", "add:<definition id>" (how
many of that item the character has, in all). `steps(field)` says where D&D Beyond keeps it in a character's JSON, as
steps the extension follows too (extension/askdnd-bridge/ddb-page.js `pick`), so askdnd's read-back, the extension's
check before writing and its check of the open sheet always read a value the same way:

- a string reads a dict's entry ("removedHitPoints"),
- {key: value} picks the element of a list whose `key` is `value` ({"id": 7}, {"level": 1}; compared as text),
- "*" joins the lists in a dict into one ("actions": its race, class and feat lists),
- {"read": {name: steps}} reads several values at once, as a dict,
- {"or": X} stands for a value D&D Beyond left out (no temporary hit points, no Exhaustion),
- {"present": true} reads whether there is anything there at all (a condition),
- {"sum": [steps, value, key]} adds up `key` over the elements whose `steps` read `value` (one item over several rows).

Anything else missing on D&D Beyond reads as None.
"""

CS = "/character/v5"
CHARACTER_CONTAINER = 1581111423  # D&D Beyond's type for "carried by the character" (DDB Importer uses it too)
EXHAUSTION = 4
CONDITIONS = {1: "Blinded", 2: "Charmed", 3: "Deafened", 5: "Frightened", 6: "Grappled", 7: "Incapacitated",
              8: "Invisible", 9: "Paralyzed", 10: "Petrified", 11: "Poisoned", 12: "Prone", 13: "Restrained",
              14: "Stunned", 15: "Unconscious"}  # D&D Beyond's ids (4 is Exhaustion, a level)
COINS = {"cp": "copper", "sp": "silver", "ep": "electrum", "gp": "gold", "pp": "platinum"}
HP_PATH = f"{CS}/life/hp/damage-taken"
ITEM_PATH = f"{CS}/inventory/item/quantity"
# The only requests the extension makes (its own list in ddb-page.js matches)
WRITES = {("PUT", HP_PATH), ("PUT", f"{CS}/life/death-saves"), ("PUT", f"{CS}/character/inspiration"),
          ("PUT", f"{CS}/condition"), ("DELETE", f"{CS}/condition"), ("POST", f"{CS}/character/rest/short"),
          ("PUT", f"{CS}/spell/slots"), ("PUT", f"{CS}/spell/pact-magic"),
          ("PUT", f"{CS}/action/limited-use"), ("PUT", ITEM_PATH), ("PUT", f"{CS}/inventory/item/equipped"),
          ("PUT", f"{CS}/inventory/item/attuned"), ("PUT", f"{CS}/inventory/item/charge"),
          ("PUT", f"{CS}/inventory/item/move"), ("POST", f"{CS}/inventory/item"), ("DELETE", f"{CS}/inventory/item"),
          *{("PUT", f"{CS}/inventory/currency/{name}") for name in COINS.values()}}


def pick(data, steps: list):
    """Follow `steps` into a D&D Beyond character (or into what the open sheet holds); None where it stops."""
    v = data
    for s in steps:
        if isinstance(s, dict) and "or" in s:
            v = s["or"] if v is None else v
        elif isinstance(s, dict) and "present" in s:
            v = v is not None
        elif v is None:
            continue
        elif s == "*":
            v = [x for part in v.values() if isinstance(part, list) for x in part] if isinstance(v, dict) else None
        elif isinstance(s, str):
            v = v.get(s) if isinstance(v, dict) else None
        elif "read" in s:
            v = {k: pick(v, sub) for k, sub in s["read"].items()}
        elif "sum" in s:
            where, want, key = s["sum"]
            v = sum(x.get(key) or 0 for x in v if isinstance(x, dict) and str(pick(x, where)) == str(want)) if isinstance(v, list) else None
        else:
            (key, want), = s.items()
            v = next((x for x in v if isinstance(x, dict) and str(x.get(key)) == str(want)), None) if isinstance(v, list) else None
    return v


def _split(field: str) -> tuple[str, str]:
    kind, _, arg = field.partition(":")
    return kind, arg


def steps(field: str) -> list:
    kind, arg = _split(field)
    item = ["inventory", {"id": arg}]
    return {
        "hp": [{"read": {"removedHitPoints": ["removedHitPoints", {"or": 0}], "temporaryHitPoints": ["temporaryHitPoints", {"or": 0}]}}],
        "death": ["deathSaves", {"read": {"failCount": ["failCount", {"or": 0}], "successCount": ["successCount", {"or": 0}]}}],
        "inspiration": ["inspiration", {"or": False}],
        "exhaustion": ["conditions", {"id": EXHAUSTION}, "level", {"or": 0}],
        "condition": ["conditions", {"id": arg}, {"present": True}],
        "hitdice": ["classes", {"id": arg}, "hitDiceUsed", {"or": 0}],
        "slot": ["spellSlots", {"level": arg}, "used", {"or": 0}],
        "pact": ["pactMagic", {"level": arg}, "used", {"or": 0}],
        "uses": ["actions", "*", {"id": arg}, "limitedUse", "numberUsed"],
        "item": [*item, "quantity"],
        "equipped": [*item, "equipped"],
        "attuned": [*item, "isAttuned"],
        "charges": [*item, "limitedUse", "numberUsed"],
        "container": [*item, "containerEntityId"],
        "coin": ["currencies", arg, {"or": 0}],
        "add": ["inventory", {"sum": [["definition", "id"], arg, "quantity"]}],
    }[kind]


def value(data: dict, field: str):
    return pick(data, steps(field))


def tracked(data: dict | None) -> dict:
    """Every field the bridge follows on this character, with its value on D&D Beyond (what the log compares)."""
    if not data:
        return {}
    fs = ["hp", "death", "inspiration", "exhaustion", *(f"condition:{i}" for i in CONDITIONS), *(f"coin:{c}" for c in COINS)]
    fs += [f"hitdice:{c['id']}" for c in data.get("classes") or [] if isinstance(c, dict)]
    fs += [f"slot:{s['level']}" for s in data.get("spellSlots") or [] if isinstance(s, dict)]
    fs += [f"pact:{s['level']}" for s in data.get("pactMagic") or [] if isinstance(s, dict)]
    fs += [f"uses:{a['id']}" for a in pick(data, ["actions", "*"]) or [] if isinstance(a, dict) and a.get("limitedUse")]
    for i in data.get("inventory") or []:
        if isinstance(i, dict) and i.get("id") is not None:
            fs += [f"{k}:{i['id']}" for k in ("item", "equipped", "container")]
            fs += [f"attuned:{i['id']}"] if (i.get("definition") or {}).get("canAttune") or i.get("isAttuned") else []
            fs += [f"charges:{i['id']}"] if i.get("limitedUse") else []
    return {f: value(data, f) for f in fs}


# ------------------------------------------------------------------ saying it


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def item_name(data: dict | None, item_id) -> str:
    i = pick(data or {}, ["inventory", {"id": item_id}])
    return ((i or {}).get("definition") or {}).get("name") or "an item"


def name(data: dict | None, field: str) -> str:
    """What a person calls it: "hit points", "Potion of Healing", "1st-level slots"."""
    kind, arg = _split(field)
    data = data or {}
    if kind in ("item", "equipped", "attuned", "charges", "container"):
        return item_name(data, arg)
    if kind == "add":
        row = next((i for i in data.get("inventory") or [] if str((i.get("definition") or {}).get("id")) == arg), {})
        return (row.get("definition") or {}).get("name") or "an item"
    if kind == "hitdice":
        return f"{((pick(data, ['classes', {'id': arg}]) or {}).get('definition') or {}).get('name') or 'Class'} Hit Dice"
    if kind == "uses":
        return (pick(data, ["actions", "*", {"id": arg}]) or {}).get("name") or "a use"
    if kind == "condition":
        return CONDITIONS.get(int(arg), "a condition")
    if kind == "slot":
        return f"{ordinal(int(arg))}-level slots"
    return {"hp": "hit points", "death": "Death Saving Throws", "inspiration": "Heroic Inspiration", "exhaustion": "Exhaustion",
            "pact": "Pact Magic slots", "coin": COINS.get(arg, "coins")}.get(kind, field)


def text(data: dict | None, field: str, v, max_hit_points: int = 0) -> str:
    """A value as the log and the make-by-hand list say it, after the name: "31 + 5 temporary", "×9", "2 used"."""
    kind, _ = _split(field)
    if v is None:
        return "gone" if kind == "item" else "?"
    if kind == "hp":
        temp = v["temporaryHitPoints"]
        return f"{max_hit_points - v['removedHitPoints']}" + (f" + {temp} temporary" if temp else "")
    if kind == "death":
        return f"{v['successCount']} successes, {v['failCount']} failures"
    if kind in ("item", "add"):
        return f"×{v}"
    if kind == "container":
        return "carried" if str(v) == str((data or {}).get("id")) else f"in {item_name(data, v)}"
    if isinstance(v, bool):
        return {"equipped": ("equipped", "not equipped"), "attuned": ("attuned", "not attuned")}.get(kind, ("on", "off"))[0 if v else 1]
    if kind == "exhaustion":
        return f"level {v}" if v else "none"
    return f"{v} used" if kind in ("hitdice", "slot", "pact", "uses", "charges") else str(v)


def show(data: dict | None, field: str, v, max_hit_points: int = 0) -> str:
    """"hit points 31 + 5 temporary", "Candle ×9", "1st-level slots 2 used"."""
    return f"{name(data, field)} {text(data, field, v, max_hit_points)}"


def changed(data: dict | None, field: str, before, after, max_hit_points: int = 0) -> str:
    """One change seen on D&D Beyond, for the log: "hit points 37 → 31", "Potion of Healing ×2 → ×3"."""
    if field == "hp" and before and after and before["removedHitPoints"] == after["removedHitPoints"]:
        return f"temporary hit points {before['temporaryHitPoints']} → {after['temporaryHitPoints']}"
    return f"{name(data, field)} {text(data, field, before, max_hit_points)} → {text(data, field, after, max_hit_points)}"


def max_hp(summary: dict | None) -> int:
    return ((summary or {}).get("hit_points") or {}).get("max") or 0


# ------------------------------------------------------------------ writing it


def write(ddb_id: int, field: str, v, data: dict | None = None, extra: dict | None = None, max_hit_points: int = 0) -> dict:
    """The request the sheet itself sends to set this field to `v` ({"method", "path", "body"}). `data` is D&D Beyond's
    character (some requests name the row they change), `extra` what an added item needs (its definition's type, how
    many, where to)."""
    kind, arg = _split(field)
    data, extra = data or {}, extra or {}

    def req(method, path, **body):
        return {"method": method, "path": f"{CS}/{path}", "body": {"characterId": ddb_id, **body}}
    if kind == "hp":
        return req("PUT", "life/hp/damage-taken", **v)
    if kind == "death":
        return req("PUT", "life/death-saves", **v)
    if kind == "inspiration":
        return req("PUT", "character/inspiration", inspiration=v)
    if kind == "exhaustion":
        return req("PUT", "condition", id=EXHAUSTION, level=v, totalHp=max_hit_points) if v else req("DELETE", "condition", id=EXHAUSTION)
    if kind == "condition":
        return req("PUT", "condition", id=int(arg), level=None, totalHp=max_hit_points) if v else req("DELETE", "condition", id=int(arg))
    if kind == "hitdice":  # D&D Beyond spends Hit Dice only as part of a Short Rest (it restores what a Short Rest restores)
        return req("POST", "character/rest/short", classHitDiceUsed={arg: v}, resetMaxHpModifier=False)
    if kind in ("slot", "pact"):
        return req("PUT", "spell/slots" if kind == "slot" else "spell/pact-magic", **{f"level{arg}": v})
    if kind == "uses":
        a = pick(data, ["actions", "*", {"id": arg}]) or {}
        return req("PUT", "action/limited-use", id=str(arg), entityTypeId=str(a.get("entityTypeId")), uses=v)
    if kind == "item":
        if v is None:
            return req("DELETE", "inventory/item", id=int(arg), removeContainerContents=False)
        return req("PUT", "inventory/item/quantity", id=int(arg), quantity=v)
    if kind in ("equipped", "attuned"):
        return req("PUT", f"inventory/item/{kind}", id=int(arg), value=v)
    if kind == "charges":
        return req("PUT", "inventory/item/charge", id=int(arg), uses=v, charges=v)
    if kind == "container":
        own = str(v) == str(data.get("id"))
        box = pick(data, ["inventory", {"id": v}]) or {}
        return req("PUT", "inventory/item/move", id=int(arg), containerEntityId=int(v),
                   containerEntityTypeId=CHARACTER_CONTAINER if own else box.get("entityTypeId"))
    if kind == "coin":
        return req("PUT", f"inventory/currency/{COINS[arg]}", amount=v)
    if kind == "add":
        where = extra.get("container") or ddb_id
        box = pick(data, ["inventory", {"id": where}]) or {}
        return req("POST", "inventory/item", equipment=[{
            "containerEntityId": int(where), "containerEntityTypeId": CHARACTER_CONTAINER if str(where) == str(ddb_id) else box.get("entityTypeId"),
            "entityId": int(arg), "entityTypeId": extra.get("entityTypeId"), "quantity": extra.get("quantity", 1)}])
    raise ValueError(f"Not a field the bridge writes: {field}")
