"""Summons and Find Steed (Your creatures, board 5; Brett chose A, Nov 4: docs/mockups/steeds-summons/, DECISIONS).

D&D Beyond's Extras has no 2024 summon spirit or Otherworldly Steed, so these are askdnd's own creatures, like a Wild
Shape form: cast in askdnd's Cast window, kept on the character (`Character.companions`, by `own_id`), their Hit Points
kept in askdnd. Their stat blocks are the Player's Handbook's, a private book (kind "summon", scripts/summon_load.py),
kept as printed ("11 + the spell's level"); `work` turns one into numbers for the level cast, the choice made
("Air", "Celestial") and its master's spell attack and save DC, and `creature` gives it the shape of a creature on a
sheet's Extras, so Battle, Party, the fight and Table rolls show it as they show Pip.
"""

import re
import zlib

from app.creatures import MOUNT, SUMMONED

OWN = 9_000_000_000_000  # askdnd's own creatures' ids, far above D&D Beyond's
STEED = "Find Steed"


def own_id(key: str) -> int:
    return OWN + zlib.crc32(key.encode())


def _pick(text: str, choice: str) -> str:
    """Keep what's for `choice`: "20 (Air only) or 30 (Land and Water only)" → "30" for Land; a part of a list marked
    "(Air only)" stays only for Air; "Radiant (Celestial), Psychic (Fey), or Necrotic (Fiend)" → "Psychic" for Fey."""
    def mine(who: str) -> bool:
        return not choice or choice in [x.strip() for x in re.split(r",\s*|\s+and\s+|\s+or\s+", who)]

    def only(m: re.Match) -> bool:
        return mine(m.group(1))
    # "A (X only) or B (Y only)": the one for the choice
    alts = re.compile(r"(\d+) \(([^()]+?) only\)((?: or \d+ \([^()]+? only\))+)", re.I)

    def alt(m: re.Match) -> str:
        opts = re.findall(r"(\d+) \(([^()]+?) only\)", m.group(0), re.I)
        return next((n for n, who in opts if mine(who)), opts[0][0])
    text = alts.sub(alt, text)
    # "+ 2 (Defender only)" inside a number: added for that choice only
    text = re.sub(r"\s*([+-] \d+) \(([^()]+?) only\)", lambda m: f" {m.group(1)}" if mine(m.group(2)) else "", text, flags=re.I)
    # a part of a list marked for some choices only: kept for those, its mark dropped
    parts = _parts(text)
    out = []
    for p in parts:
        m = re.search(r"\s*\((?:[^();]*;\s*)?([A-Z][\w ,]*?) [Oo]nly(?:; [^)]*)?\)", p)
        if m and not only(m):
            if out and re.fullmatch(r";\s*|,\s*", out[-1]):
                out.pop()
            continue
        out.append(re.sub(r"\s*\((?:hover; )?[A-Z][\w ,]*? [Oo]nly\)", "", p) if m else p)
    text = "".join(out).lstrip(";, ")
    # "Radiant (Celestial), Psychic (Fey), or Necrotic (Fiend)": the word for the choice
    if choice:
        run = re.compile(r"(\w+) \(([A-Z][\w ]*)\)(?:,? (?:or )?(\w+) \(([A-Z][\w ]*)\))+")

        def word(m: re.Match) -> str:
            pairs = re.findall(r"(\w+) \(([A-Z][\w ]*)\)", m.group(0))
            return next((w for w, who in pairs if who == choice), m.group(0))
        text = run.sub(word, text)
    return text


def _parts(text: str) -> list[str]:
    """A list split at its ";" and "," outside brackets, the separators kept: "30 ft.; Fly 40 ft. (hover; Ghostly only)"."""
    out, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and ch in ";,":
            j = i + 1
            while j < len(text) and text[j] == " ":
                j += 1
            out += [cur, text[i:j]]
            cur, i = "", j
            continue
        cur += ch
        i += 1
    return out + [cur]


def _sum(text: str) -> str:
    """Add up what's now plain numbers: "11 + 3" → "14", "1d8 + 4 + 3" → "1d8 + 7"."""
    text = re.sub(r"(?<![\dd])(\d+)((?: [+-] \d+)+)(?![\dd])",
                  lambda m: str(int(m.group(1)) + sum(int(x.replace(" ", "")) for x in re.findall(r"[+-] \d+", m.group(2)))), text)
    return re.sub(r"(\d+d\d+)((?: \+ \d+)+)", lambda m: f"{m.group(1)} + {sum(int(x) for x in re.findall(r'\d+', m.group(2)))}", text)


def work(text: str, level: int, choice: str = "", attack: int = 0, dc: int = 0) -> str:
    """A line of the stat block for this casting: its choice kept, the spell's level and its master's numbers put in."""
    t = _pick(text.replace("’", "'"), choice)
    t = re.sub(r"half (?:this|the) spell's level \(round down\)", str(level // 2), t)
    t = re.sub(r"\+ (\d+) for each spell level above (\d+)", lambda m: f"+ {int(m.group(1)) * max(0, level - int(m.group(2)))}", t)
    t = re.sub(r"(\d+) per spell level", lambda m: str(int(m.group(1)) * level), t)
    t = re.sub(r"(?:the|this) spell's level", str(level), t)
    t = re.sub(r"(\d+(?:d\d+)?) plus (\d+)", r"\1 + \2", t)
    t = re.sub(r"(\d) of (\w+) damage", r"\1 \2 damage", t)
    t = re.sub(r"Bonus equals your spell attack modifier", f"{attack:+d}", t)
    t = re.sub(r"DC equals your spell save DC", f"DC {dc}", t)
    t = re.sub(r"\(requires level (\d)\+ spell\)", lambda m: "" if level >= int(m.group(1)) else "(not at this level)", t)
    t = re.sub(r",? \w+ \d+ ft\. \(not at this level\)", "", t)
    return " ".join(_sum(t).split())


def _first(text: str) -> int:
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else 0


def _speed(text: str) -> dict:
    out = {}
    for m in re.finditer(r"(?:(Burrow|Climb|Fly|Swim) )?(\d+) ft", text):
        out[(m.group(1) or "walk").lower()] = int(m.group(2))
    return out


def creature(entry: dict, level: int, choice: str = "", attack: int = 0, dc: int = 0, **kept) -> dict:
    """The creature for this casting, in the shape of one on a sheet's Extras (app/ddb_sheet.py creatures), its block
    worked out. `kept`: what askdnd keeps of it (its name, look, Hit Points taken)."""
    w = lambda s: work(s or "", level, choice, attack, dc)  # noqa: E731
    entries = lambda key: [{"name": _plain(w(e["name"])), "text": w(e["text"])} for e in entry.get(key) or []  # noqa: E731
                           if not re.search(r"\(([^()]*?) Only", e["name"], re.I) or _keeps(e["name"], choice)]
    senses = w(entry.get("senses"))
    hp = _first(w(entry["hp"]))
    steed = entry["spell"] == STEED
    block = {"name": entry["name"], "size": w(entry.get("what")).split(" ")[0], "ac": _first(w(entry["ac"])), "hp": hp,
             "hit_dice": f"{level}d10" if steed else "", "speed": _speed(w(entry["speed"])), "abilities": dict(entry.get("abilities") or {}),
             "block_saves": [], "block_skills": {}, "condition_immunities": [], "saves": {}, "skills": {},
             "senses": {k.lower(): int(n) for k, n in re.findall(r"(Darkvision|Blindsight|Tremorsense|Truesight) (\d+)", senses)},
             "passive_perception": _first(senses.split("Passive Perception")[-1]) if "Passive Perception" in senses else 10,
             "traits": entries("traits"), "actions": entries("actions"), "bonus_actions": entries("bonus_actions"),
             "reactions": entries("reactions"), "source": entry.get("source") or "PHB 2024", "cr": 0.0, "cr_label": ""}
    name = kept.get("name") or entry["name"]
    return {"key": f"form:{entry['name']}", "name": name, "kind": entry["name"], "own": True, "spell": entry["spell"],
            "id": own_id(entry.get("key") or entry["name"]), "group_id": MOUNT if steed else SUMMONED,
            "group": "Mount" if steed else "Summoned", "group_name": "Mount" if steed else "Summoned",
            "level": level, "choice": choice, "look": kept.get("look") or "", "concentration": bool(entry.get("concentration")),
            "turn_text": entry.get("turn") or "", "goes": entry.get("goes") or "",
            "cr": "", "armor_class": block["ac"], "hit_points": hp, "speed": block["speed"], "block": block,
            "removed": kept.get("removed") or 0, "temp": kept.get("temp") or 0, "active": True, "max_set": None, "picture": "",
            "about": " · ".join(x for x in (w(entry.get("what")), f"{entry['spell']} at level {level}") if x)}


def _plain(name: str) -> str:
    """An entry's name without the choice it's for: "Fey Step (Fey Only; Recharges after a Long Rest)" → "Fey Step
    (Recharges after a Long Rest)"."""
    name = re.sub(r"\(([^()]*?) Only; ", "(", name, flags=re.I)
    return re.sub(r"\s*\([^()]*? Only\)", "", name, flags=re.I)


def _keeps(name: str, choice: str) -> bool:
    m = re.search(r"\(([^()]*?) Only", name, re.I)
    if not m or not choice:
        return True
    return choice in re.split(r",\s*|\s+and\s+|\s+or\s+|;\s*", m.group(1))
