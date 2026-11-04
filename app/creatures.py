"""Your creatures (Brett, 2026-11-03; docs/plans/2026-11-03-your-creatures.md, docs/mockups/your-creatures/ Option B): a
creature a player controls, from their D&D Beyond sheet's Extras (a familiar, an artificer's Homunculus Servant or Steel
Defender, a ranger's companion, a summon: every group but Wild Shape's). Battle's switch by the name (Vi · Homunculus)
draws Battle as the creature: its Hit Points as D&D Beyond keeps them, its Armor Class, speeds, abilities, saves and
skills, its actions to roll, and when its turn comes. A Labs feature, `creatures` (app/vtt.py).

D&D Beyond's stat block is the creature's at level 1. Where the creature's book says how a number grows with its master,
askdnd works it out and says how (Brett: "Work them out"), each number with its parts; the DM corrects anything else. Its
words decide the rest: Might of the Master in its own traits adds the master's Proficiency Bonus above 2.
"""

import re

from app import wild_shape as ws

FAMILIAR, COMPANION, MOUNT, PET, SUMMONED, MISC, DEFENDER, SIDEKICK, INFUSION = 2, 3, 4, 5, 6, 7, 10, 11, 12

# When its turn comes, by the rules that make it (its own words where the stat block says; askdnd says, the DM rules)
TURN = {
    FAMILIAR: "Its own turn: it rolls its own Initiative. It can't attack, but it can take other actions.",
    INFUSION: "Right after its master's turn, sharing their Initiative. It takes the Dodge action unless its master uses a Bonus "
              "Action to command another; it moves and uses its Reaction on its own.",
    DEFENDER: "Right after its master's turn, sharing their Initiative. It takes the Dodge action unless its master uses a Bonus "
              "Action to command another; it moves and uses its Reaction on its own.",
    SUMMONED: "Right after its master's turn, sharing their Initiative. It obeys its master's commands; with none, it defends "
              "itself.",
    COMPANION: "On its master's turn: it acts when they command it.",
}
OTHER_TURN = "When its turn comes is the DM's to say."
# Party's card for it (Brett, Nov 4, Creatures as Characters board 7, A): whose it is and its turn, in a few words
ROLE = {FAMILIAR: "familiar", INFUSION: "Homunculus", DEFENDER: "Steel Defender", SUMMONED: "summon", COMPANION: "companion",
        MOUNT: "mount", PET: "pet", SIDEKICK: "sidekick"}
TURN_SHORT = {FAMILIAR: "Its own Initiative · can't attack", INFUSION: "Right after its master's turn", DEFENDER: "Right after its master's turn",
              SUMMONED: "Right after its master's turn", COMPANION: "On its master's turn"}

# How a creature's Hit Points grow with its master, from its book (D&D Beyond keeps only the level-1 number): the class
# whose level counts, and the number from that level and the master's Intelligence modifier
GROWS = {
    "Homunculus Servant": ("Artificer", "1 + your Intelligence modifier + your artificer level", lambda lv, intm: 1 + intm + lv,
                           "Tasha's Cauldron of Everything"),
    "Steel Defender": ("Artificer", "2 + your Intelligence modifier + five times your artificer level", lambda lv, intm: 2 + intm + 5 * lv,
                       "Tasha's Cauldron of Everything"),
}
MIGHT = "Might of the Master"
# Older stat blocks (Tasha's, as D&D Beyond keeps a Homunculus Servant) say "Ranged Weapon Attack: +4 to hit … Hit: 1d4 + 2
# force damage"; Battle's stat block reading (app/wild_shape.py) reads the 2024 words, so these are put in them first
OLD_ATTACK = re.compile(r"(Melee or Ranged|Melee|Ranged) (?:Weapon |Spell )?Attack:\s*([+−-]\d+) to hit")
OLD_DAMAGE = re.compile(r"(?<![(\d])(\d+)d(\d+)(?:\s*([+−-])\s*(\d+))? (\w+) damage")


def modern(text: str) -> str:
    """An older stat block's attack in the 2024 words: "Ranged Attack Roll: +4 … 4 (1d4 + 2) Force damage"."""
    text = OLD_ATTACK.sub(lambda m: f"{m.group(1)} Attack Roll: {m.group(2)}", text)

    def dmg(m):
        n, size, sign, flat = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4) or 0)
        flat = -flat if sign in ("−", "-") else flat
        dice = f"{n}d{size}" + (f" {sign} {m.group(4)}" if m.group(4) else "")
        return f"{max(1, n * (size + 1) // 2 + flat)} ({dice}) {m.group(5).title()} damage"
    return OLD_DAMAGE.sub(dmg, text)


def short(name: str) -> str:
    """Its name on the switch by its master's: "Homunculus Servant" -> "Homunculus"."""
    return name if len(name) <= 12 else name.split()[0]


def _mod(score: int) -> int:
    return (score - 10) // 2


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{abs(n)}"


def yours(sheet: dict | None) -> list[dict]:
    """The creatures on this sheet that its player controls: every one that isn't a Wild Shape form."""
    return [c for c in (sheet or {}).get("creatures") or [] if c.get("id") and c.get("group") != "Wild Shape form" and c.get("group_id") not in (1, 13)]


# A familiar exists only once it's cast (Brett, 2026-11-04, docs/mockups/creatures-as-characters/ boards 2 and 3): askdnd
# keeps where each is (Character.companions, by its D&D Beyond id), and one on the sheet's Extras that was never cast
# through askdnd isn't in play. Other creatures (a Homunculus Servant, a Steel Defender, a companion) are always here;
# steeds and summons come with their spells next.
CAST = {FAMILIAR: "Find Familiar"}
WHERE = {"here": "Here", "away": "In the pocket dimension", "gone": "Gone"}
KINDS = ("Celestial", "Fey", "Fiend")


def where(ch, c: dict) -> str | None:
    """"here", "away" (the pocket dimension), "gone" (0 Hit Points, or dismissed), or None: a familiar not cast."""
    if c.get("group_id") not in CAST:
        return "here"
    return ((ch.companions or {}).get(str(c.get("id"))) or {}).get("state")


def in_play(ch, sheet: dict | None) -> list[dict]:
    """The character's creatures that exist now (here, away or gone): a familiar only once cast."""
    return [c for c in yours(sheet) if where(ch, c)]


def placed(ch, k: dict, c: dict) -> dict:
    """A creature's card with where it is, what it was made (a familiar's Celestial, Fey or Fiend) and the spell that
    brings it."""
    kept = (ch.companions or {}).get(str(k["id"])) or {}
    w = where(ch, c)
    return {**k, "where": w, "where_word": WHERE.get(w or "", "Not here"), "made": kept.get("kind", ""), "why": kept.get("why", ""),
            "spell": CAST.get(c.get("group_id"), ""), "cast": c.get("group_id") in CAST}


def find(sheet: dict | None, creature_id) -> dict | None:
    return next((c for c in yours(sheet) if str(c["id"]) == str(creature_id)), None)


def _level(sheet: dict, cls: str) -> int:
    return next((k["level"] for k in sheet.get("classes") or [] if k.get("name") == cls), 0)


def _master_mod(sheet: dict, key: str) -> int:
    return next((_mod(a["score"]) for a in sheet.get("abilities") or [] if a.get("key", "")[:3] == key), 0)


def card(sheet: dict, c: dict) -> dict:
    """The creature as Battle draws it: each number with where it comes from."""
    b = c["block"]
    pb = sheet.get("proficiency_bonus") or 2
    might = pb - 2 if any(t["name"] == MIGHT for t in b.get("traits") or []) else 0
    notes = []
    grows = GROWS.get(c["kind"])
    block_hp = b.get("hp") or c.get("hit_points") or 1
    ddb_max = c.get("max_set") or block_hp  # (what D&D Beyond shows: its set maximum, else the stat block's)
    rule = None
    if grows and _level(sheet, grows[0]):
        lv, intm = _level(sheet, grows[0]), _master_mod(sheet, "int")
        rule = grows[2](lv, intm)
        notes.append(f"Hit Points: {grows[1]}, so {rule} at {grows[0]} {lv} ({grows[3]}).")
    if c.get("max_set") and c["max_set"] == rule:  # (askdnd keeps it there: app/creature_hp.py keep_max)
        hp_max, hp_parts = rule, [(f"{grows[1]} ({grows[3]}), set on D&D Beyond", rule)]
    elif c.get("max_set"):  # set on D&D Beyond to another number (by its player or DM, or before a level-up): that's the one
        hp_max, hp_parts = c["max_set"], [("Set on D&D Beyond", c["max_set"])]
        if rule and rule != c["max_set"]:
            notes.append(f"D&D Beyond's maximum is set to {c['max_set']}; the rule works out {rule}. The DM rules.")
    elif rule:
        hp_max, hp_parts = rule, [(f"{grows[1]} ({grows[3]})", rule)]
    else:
        hp_max, hp_parts = block_hp, [("D&D Beyond's stat block", block_hp)]
    if might:
        notes.append(f"{MIGHT}: its skills, saving throws and attack's to-hit and damage are {_signed(might)} "
                     f"(the stat block's numbers are for a Proficiency Bonus of +2; yours is {_signed(pb)}).")
    removed, temp = c.get("removed") or 0, c.get("temp") or 0
    scores = b.get("abilities") or {}
    abilities = [{"key": k, "short": short, "score": scores.get(k, 10), "label": _signed(_mod(scores.get(k, 10)))} for k, _, short in ws.ABILITIES]
    saves = [{"key": k, "short": short, "label": _signed(_mod(scores.get(k, 10)) + (2 + might if k in (b.get("block_saves") or []) else 0)),
              "proficient": k in (b.get("block_saves") or [])} for k, _, short in ws.ABILITIES]
    skills = [{"name": n, "label": _signed(v + might)} for n, v in (b.get("block_skills") or {}).items()]
    d = {"attack_bonus": might, "damage_bonus": might}
    cols = {"Action": [], "Bonus action": [], "Reaction": []}
    for cost, key in (("Action", "actions"), ("Bonus action", "bonus_actions"), ("Reaction", "reactions")):
        cols[cost] = [_option(c, e, cost, d) for e in b.get(key) or []]
    group = c.get("group_id")
    if group in (INFUSION, DEFENDER):
        cols["Action"].append({"key": f"creature:{c['id']}:dodge", "name": "Dodge", "cost": "Action", "hit": "", "tags": [], "uses": None,
                               "spends": [], "starred": False, "source": "rule", "text": "",
                               "meta": "What it does on its turn unless you command it (Bonus Action)"})
    speed = ws.speed_text(b.get("speed") or {}) or c.get("speed") or ""
    passive = b.get("passive_perception") or 10 + _mod(scores.get("wis", 10))
    if might and b.get("block_skills", {}).get("Perception") is not None:
        passive += might
    return {
        "id": c["id"], "name": c["name"], "kind": c["kind"], "group": c.get("group_name") or "Creature", "picture": c.get("picture") or "",
        "active": c.get("active"),
        "hp": {"max": hp_max, "current": max(0, hp_max - removed), "temp": temp, "removed": removed, "parts": hp_parts,
               "ddb_max": ddb_max, "rule": rule, "fix": rule if rule and rule != ddb_max else None,  # (fix: D&D Beyond shows another maximum)
               # (waits: D&D Beyond still counts against its stat block's, until askdnd's maximum is on its way there)
               "waits": bool(rule and not c.get("max_set") and rule != block_hp)},
        "ac": b.get("ac") or c.get("armor_class"), "speed": speed, "walk": (b.get("speed") or {}).get("walk", 0),
        "other_speeds": ", ".join(f"{k} {v} ft" for k, v in (b.get("speed") or {}).items() if k != "walk"), "initiative": _signed(_mod(scores.get("dex", 10))),
        "abilities": abilities, "saves": saves, "skills": skills, "senses": ws.senses_text(b), "passive": passive,
        "immune": b.get("condition_immunities") or [], "size": b.get("size") or "", "cr": b.get("cr_label") or "",
        "traits": [t for t in b.get("traits") or [] if t["name"] != MIGHT], "might": might,
        "columns": {k: {"shown": v, "all": v, "count": len(v), "items": [], "item_count": 0} for k, v in cols.items()},
        "turn": TURN.get(group, OTHER_TURN), "turn_short": TURN_SHORT.get(group, ""), "role": ROLE.get(group, "creature"),
        "own_initiative": group == FAMILIAR, "notes": notes,
        "about": _first(c.get("about") or ""),
    }


def _option(c: dict, e: dict, cost: str, d: dict) -> dict:
    """One of its stat block's entries as a row on Battle: the roll (Might of the Master included) and what it does."""
    o = ws._entry({**e, "text": modern(e["text"])}, cost, d)
    rec = o.get("recipe")
    if rec:  # (its own damage as it rolls, not Wild Shape's "worn item" line)
        reach = re.search(r"(reach \d+ ft\.|range [\d/]+ ft\.)", e["text"])
        first, *more = rec["events"]
        o["meta"] = " · ".join([x for x in (reach.group(1).rstrip(".") if reach else "", " + ".join(first["parts"])) if x]
                               + [f"{ev['name']}: {' + '.join(ev['parts'])}" for ev in more])
    return {**o, "key": f"creature:{c['id']}:{e['name']}", "tags": [], "source": "creature"}


def _first(text: str, n: int = 320) -> str:
    """The creature's description, its first paragraph or so."""
    para = next((p.strip() for p in text.split("\n") if p.strip()), "")
    return para if len(para) <= n else re.sub(r"\s+\S*$", "", para[:n]) + "…"

