"""The numbers the D&D Beyond bridge follows on a character (app/ddb_bridge.py): how to read each, how to say it, and
the request the sheet itself sends to change it (each seen on Brett's test character's own sheet, 2026-10-27).

A field is a key: "hp", "death", "inspiration", "exhaustion", "condition:<id>", "hitdice:<class id>", "slot:<level>",
"pact:<level>", "uses:<action id>", "item:<inventory id>" (its count; None once removed),
"equipped:<id>", "attuned:<id>", "charges:<id>", "container:<id>", "coin:<cp|sp|ep|gp|pp>" (carried), "bagcoin:<bag's
inventory id>:<cp|sp|ep|gp|pp>" (kept in that container; the same request as a carried coin, naming the container: tried
on a test sheet, Nov 7, feedback 52), "add:<definition id>" (how
many of that item the character has, in all), "prep:<class row id>:<spell's id on the class list>" (whether it's prepared;
D&D Beyond drops an unprepared spell from the sheet, which reads as not prepared), "creature:<creature id>" (one of the
character's creatures' damage taken and temporary hit points, app/creatures.py) and "creature_max:<creature id>" (the
maximum D&D Beyond shows for it, its character value 43 when someone set one; None for its stat block's). `steps(field)` says where D&D Beyond keeps it in a character's JSON, as
steps the extension follows too (extension/askdnd-bridge/ddb-page.js `pick`), so askdnd's read-back, the extension's
check before writing and its check of the open sheet always read a value the same way:

- a string reads a dict's entry ("removedHitPoints"),
- {key: value} picks the element of a list whose `key` is `value` ({"id": 7}, {"level": 1}; compared as text); with
  several keys, the one matching them all (a character value: {"typeId": 43, "valueId": "25957677"}),
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
          ("PUT", f"{CS}/spell/prepared"),
          *{("PUT", f"{CS}/inventory/currency/{name}") for name in COINS.values()},
          # (extension 0.10.0: a creature's Hit Points and its maximum, D&D Beyond's character value 43 only)
          ("PUT", f"{CS}/creature/hp"), ("PUT", f"{CS}/custom/value"), ("DELETE", f"{CS}/custom/value"),
          # (extension 0.11.0: a familiar kept in step, Brett 2026-11-04 option A: here or not, what it is, its name;
          # character values 43 and 44 only)
          ("PUT", f"{CS}/creature/status"), ("PUT", f"{CS}/creature"),
          # (also 0.11.0, ahead of the roadmap so one Google review covers them, Brett 2026-11-04: adding a creature,
          # a familiar's form, a steed or summon, a Wild Shape form learned; removing one, only a Wild Shape form swapped
          # out after a Long Rest; a spell learned or unlearned at a new level (Warlock, Sorcerer, Bard). Unused until
          # their slices, each request tried on a test sheet first)
          ("POST", f"{CS}/creature"), ("DELETE", f"{CS}/creature"), ("POST", f"{CS}/spell"), ("DELETE", f"{CS}/spell")}
CREATURE_MAX = 43  # D&D Beyond's AdjustmentTypeEnum.CREATURE_HIT_POINTS: a creature's maximum, set on its sheet
CREATURE_TYPE = 44  # D&D Beyond's AdjustmentTypeEnum.CREATURE_TYPE_OVERRIDE: what a creature is (a familiar's Celestial…)
FAMILIAR_GROUP = 2  # D&D Beyond's group for familiars on Extras (Manage Extras › Familiar)
CREATURE_AC = 42  # D&D Beyond's AdjustmentTypeEnum.CREATURE_AC: a steed's or summon's Armor Class from its spell's level (0.11.0, unused yet)
MONSTER_TYPES = {"Celestial": 3, "Fey": 8, "Fiend": 9}  # D&D Beyond's monsterTypes (its config), for CREATURE_TYPE
VALUES = {"creature_max": CREATURE_MAX, "creature_type": CREATURE_TYPE}  # the character values askdnd may set, by field


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
        elif "count" in s:  # [where, want, where, want…]: how many match them all
            pairs = list(zip(s["count"][::2], s["count"][1::2]))
            v = sum(1 for x in v if isinstance(x, dict) and all(str(pick(x, w)) == str(want) for w, want in pairs)) if isinstance(v, list) else None
        else:
            v = next((x for x in v if _matches(x, s)), None) if isinstance(v, list) else None
    return v


def _matches(x, want: dict) -> bool:
    return isinstance(x, dict) and all(str(x.get(k)) == str(w) for k, w in want.items())


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
        "bagcoin": [*["inventory", {"id": arg.partition(":")[0]}], "currency", arg.partition(":")[2], {"or": 0}],
        "add": ["inventory", {"sum": [["definition", "id"], arg, "quantity"]}],
        "prep": ["classSpells", {"characterClassId": arg.partition(":")[0]}, "spells", {"id": arg.partition(":")[2]}, "prepared", {"or": False}],
        "creature": ["creatures", {"id": arg}, {"read": {"removedHitPoints": ["removedHitPoints", {"or": 0}],
                                                         "temporaryHitPoints": ["temporaryHitPoints", {"or": 0}]}}],
        "creature_max": ["characterValues", {"typeId": CREATURE_MAX, "valueId": arg}, "value"],
        "creature_type": ["characterValues", {"typeId": CREATURE_TYPE, "valueId": arg}, "value"],
        "creature_active": ["creatures", {"id": arg}, "isActive", {"or": False}],
        "creature_name": ["creatures", {"id": arg}, "name"],
        # A familiar form added to Extras (Your creatures; `arg` D&D Beyond's monster id): how many of it there are
        # (only the Familiar group's: the same monster as a Pet or Mount isn't this one, review Nov 4)
        "familiar_add": ["creatures", {"or": []}, {"count": [["definition", "id"], arg, ["groupId"], FAMILIAR_GROUP]}],
    }[kind]


# The steps the extension's own `pick` reads (extension/askdnd-bridge/ddb-page.js: keep the two the same). A field whose
# steps use one it lacks is sent to the extension as `wire` says (tests/test_ddb_fields.py checks every kind)
EXTENSION_READS = ("or", "present", "read", "sum")


def wire(field: str, data: dict, before, after) -> tuple[list, object, object]:
    """How the extension checks a field just before writing it: (its steps, the value before, the value after), in steps
    its `pick` reads. Most fields are as they are. A new familiar form (`count`, which extensions up to 0.12.1 don't read,
    Nov 5: every Find Familiar with a new form was refused as changed) is checked as the sum of the matching creatures'
    group ids: adding one to the Familiar group adds 2, whatever else of that monster is on Extras."""
    kind, arg = _split(field)
    if kind == "familiar_add":
        read = ["creatures", {"or": []}, {"sum": [["definition", "id"], arg, "groupId"]}]
        now = pick(data, read) or 0
        return read, now, now + FAMILIAR_GROUP * ((after or 0) - (before or 0))
    return steps(field), before, after


def value(data: dict, field: str):
    return pick(data, steps(field))


def put(data: dict, field: str, v) -> None:
    """Write `v` where `field` lives in D&D Beyond's character data (a copy: what askdnd shows while a change is on its
    way, ddb_bridge.as_shown), the other way round from `value`. A field it can't find is left as it is."""
    kind, arg = _split(field)
    if kind == "prep":  # D&D Beyond adds a spell to the sheet when it's prepared: a copy shows it there while on its way
        cls, _, entry = arg.partition(":")
        group = next((g for g in data.get("classSpells") or [] if str(g.get("characterClassId")) == cls), None)
        row = next((s for s in (group or {}).get("spells") or [] if str(s.get("id")) == entry), None)
        if row is not None:
            row["prepared"] = bool(v)
        elif v and group is not None:
            pool = [s for ss in ((data.get("askdnd") or {}).get("availableSpells") or {}).values() for s in ss or []]
            known = next((s for s in pool if str(s.get("id")) == entry), None)
            if known:
                group.setdefault("spells", []).append({**known, "prepared": True})
        return
    if kind in VALUES:  # a character value: added, changed, or gone (back to the stat block's)
        rest = [x for x in data.get("characterValues") or [] if not _matches(x, {"typeId": VALUES[kind], "valueId": arg})]
        data["characterValues"] = rest + ([{"typeId": VALUES[kind], "valueId": str(arg), "value": int(v)}] if v else [])
        return
    if kind == "bagcoin":  # (a container that has never held coins has none at all on D&D Beyond)
        row = pick(data, ["inventory", {"id": arg.partition(":")[0]}])
        if isinstance(row, dict):
            row["currency"] = {**{c: 0 for c in COINS}, **(row.get("currency") or {}), arg.partition(":")[2]: v}
        return
    if kind in ("condition", "exhaustion"):  # a condition is there or not; Exhaustion is one with a level
        cid = EXHAUSTION if kind == "exhaustion" else int(arg)
        rest = [c for c in data.get("conditions") or [] if not (isinstance(c, dict) and c.get("id") == cid)]
        data["conditions"] = rest + ([{"id": cid, "level": int(v) if kind == "exhaustion" else None}] if v else [])
        return
    _put(data, [s for s in steps(field) if not (isinstance(s, dict) and ("or" in s or "present" in s))], v)


def _put(here, path: list, v) -> None:
    for i, s in enumerate(path):
        last = i == len(path) - 1
        if isinstance(s, dict) and "read" in s:  # several values at once (hit points: damage taken and temporary)
            for k, sub in s["read"].items():
                if isinstance(v, dict) and k in v:
                    _put(here, [x for x in sub if not (isinstance(x, dict) and "or" in x)], v[k])
            return
        if s == "*":  # one of the groups (actions by where they come from): the first that has the rest of the path
            for part in (here.values() if isinstance(here, dict) else []):
                if isinstance(part, list) and any(isinstance(x, dict) and str(x.get(next(iter(path[i + 1])))) == str(next(iter(path[i + 1].values())))
                                                  for x in part):
                    return _put(part, path[i + 1:], v)
            return
        if isinstance(s, str):
            if not isinstance(here, dict):
                return
            if last:
                here[s] = v
                return
            here = here.get(s)
        elif isinstance(s, dict):  # the one in a list with this id (or level), or matching several keys
            here = next((x for x in here if _matches(x, s)), None) if isinstance(here, list) else None
        if here is None:
            return


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
            fs += [f"bagcoin:{i['id']}:{c}" for c in COINS] if (i.get("definition") or {}).get("isContainer") else []
    for c in data.get("creatures") or []:  # (a Wild Shape form's Hit Points are the druid's: not followed)
        if isinstance(c, dict) and c.get("id") is not None and c.get("groupId") not in (1, 13):
            fs += [f"creature:{c['id']}", f"creature_max:{c['id']}"]
    return {f: value(data, f) for f in fs}


def creature(data: dict | None, creature_id) -> dict:
    return pick(data or {}, ["creatures", {"id": creature_id}]) or {}


def creature_max(data: dict | None, creature_id) -> int:
    """The maximum D&D Beyond shows for one of the character's creatures: its set one, else its stat block's."""
    return value(data or {}, f"creature_max:{creature_id}") or (creature(data, creature_id).get("definition") or {}).get("averageHitPoints") or 0


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
    if kind == "familiar_add":
        return "familiar forms on Extras"  # ("D&D Beyond's familiar forms on Extras changed…")
    if kind == "prep":
        entry = arg.partition(":")[2]
        lists = [s for g in data.get("classSpells") or [] for s in g.get("spells") or []]
        lists += [s for ss in ((data.get("askdnd") or {}).get("availableSpells") or {}).values() for s in ss or []]
        return next(((s.get("definition") or {}).get("name") for s in lists if str(s.get("id")) == entry), None) or "a spell"
    if kind == "hitdice":
        return f"{((pick(data, ['classes', {'id': arg}]) or {}).get('definition') or {}).get('name') or 'Class'} Hit Dice"
    if kind == "uses":
        return (pick(data, ["actions", "*", {"id": arg}]) or {}).get("name") or "a use"
    if kind.startswith("creature"):
        c = creature(data, arg)
        who = c.get("name") or (c.get("definition") or {}).get("name") or "a creature"
        return f"{who}'s " + {"creature": "hit points", "creature_max": "maximum hit points", "creature_type": "creature type",
                              "creature_active": "Active", "creature_name": "name"}[kind]
    if kind == "condition":
        return CONDITIONS.get(int(arg), "a condition")
    if kind == "bagcoin":  # "copper in Backpack"
        bag, _, coin = arg.partition(":")
        return f"{COINS.get(coin, 'coins')} in {item_name(data, bag)}"
    if kind == "slot":
        return f"{ordinal(int(arg))}-level slots"
    return {"hp": "hit points", "death": "Death Saving Throws", "inspiration": "Heroic Inspiration", "exhaustion": "Exhaustion",
            "pact": "Pact Magic slots", "coin": COINS.get(arg, "coins")}.get(kind, field)


def text(data: dict | None, field: str, v, max_hit_points: int = 0) -> str:
    """A value as the log and the make-by-hand list say it, after the name: "31 + 5 temporary", "×9", "2 used"."""
    kind, _ = _split(field)
    if kind == "creature_max":
        return str(v) if v else "its stat block's"
    if kind == "creature_type":
        return next((t for t, i in MONSTER_TYPES.items() if i == v), str(v)) if v else "its stat block's"
    if kind == "creature_name":
        return v or "its stat block's"
    if v is None:
        return "gone" if kind == "item" else "?"
    if kind == "hp":
        temp = v["temporaryHitPoints"]
        return f"{max_hit_points - v['removedHitPoints']}" + (f" + {temp} temporary" if temp else "")
    if kind == "creature":
        temp, most = v["temporaryHitPoints"], creature_max(data, _split(field)[1])
        return f"{most - v['removedHitPoints']} of {most}" + (f" + {temp} temporary" if temp else "")
    if kind == "death":
        return f"{v['successCount']} successes, {v['failCount']} failures"
    if kind in ("item", "add"):
        return f"×{v}"
    if kind == "familiar_add":
        return "added" if v else "not there"
    if kind == "container":
        return "carried" if str(v) == str((data or {}).get("id")) else f"in {item_name(data, v)}"
    if isinstance(v, bool):
        return {"equipped": ("equipped", "not equipped"), "attuned": ("attuned", "not attuned"), "prep": ("prepared", "not prepared")}.get(kind, ("on", "off"))[0 if v else 1]
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
    if kind == "creature":
        return req("PUT", "creature/hp", id=int(arg), **v)
    if kind in VALUES:  # its maximum or what it is, as D&D Beyond shows it, or back to its stat block's
        c = creature(data, arg)
        key = {"typeId": VALUES[kind], "valueId": str(arg), "valueTypeId": str(c.get("entityTypeId")), "contextId": None, "contextTypeId": None}
        return req("PUT", "custom/value", **key, value=int(v), notes=None) if v else req("DELETE", "custom/value", **key)
    if kind == "creature_active":  # Active on its Extras (here), as D&D Beyond's own switch sends it
        return req("PUT", "creature/status", id=int(arg), isActive=bool(v))
    if kind == "creature_name":  # its name on its Extras (its notes and group as they are)
        c = creature(data, arg)
        return req("PUT", "creature", id=int(arg), name=v or None, description=c.get("description"), groupId=c.get("groupId"))
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
    if kind == "bagcoin":  # the container's own total of that coin, as D&D Beyond's coin manager sets it
        bag, _, coin = arg.partition(":")
        box = pick(data, ["inventory", {"id": bag}]) or {}
        return req("PUT", f"inventory/currency/{COINS[coin]}", amount=v, destinationEntityId=int(bag), destinationEntityTypeId=box.get("entityTypeId"))
    if kind == "prep":
        cls, _, entry = arg.partition(":")
        return req("PUT", "spell/prepared", spellId=extra.get("spellId"), characterClassId=int(cls), entityTypeId=extra.get("entityTypeId"),
                   id=int(entry), prepared=bool(v))
    if kind == "familiar_add":  # a familiar form onto Extras, as Manage Extras › Familiar › Add sends it (Nov 4, Levi's seat)
        return req("POST", "creature", groupId=FAMILIAR_GROUP, monsterId=int(arg), names=[None])
    if kind == "add":
        where = extra.get("container") or ddb_id
        box = pick(data, ["inventory", {"id": where}]) or {}
        return req("POST", "inventory/item", equipment=[{
            "containerEntityId": int(where), "containerEntityTypeId": CHARACTER_CONTAINER if str(where) == str(ddb_id) else box.get("entityTypeId"),
            "entityId": int(arg), "entityTypeId": extra.get("entityTypeId"), "quantity": extra.get("quantity", 1)}])
    raise ValueError(f"Not a field the bridge writes: {field}")
