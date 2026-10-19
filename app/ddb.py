"""D&D Beyond character data: fetch and sanitize (parsing is in app/ddb_sheet.py).

D&D Beyond has no official API. Its character sheet page loads public JSON from
the character service, which we read the same way. It can change or break
without notice, so callers keep the last good copy (app/characters.py) and the
parser is defensive: a missing or renamed field leaves a blank, not a crash.

Most numbers on a D&D Beyond sheet (ability scores, AC, spell slots…) are
computed in the browser from "modifiers", so `parse_character` recomputes the
common ones. It covers the rules our table's characters use; anything it
can't work out is left out rather than guessed.
"""

import json
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser

CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/{id}"
SHEET_URL = "https://www.dndbeyond.com/characters/{id}"
USER_AGENT = "askdnd/2 (private table companion; +https://beta.askdnd.ai)"
TIMEOUT_SECONDS = 15
PARSER_VERSION = 14  # bump when the summary shape changes; stored summaries are re-parsed


class DdbError(Exception):
    """A fetch or parse problem, worded for the person who clicked Refresh."""


# ---------------------------------------------------------------- fetching


def ddb_id_from(value: str | int | None) -> str | None:
    """Accept a character id or any D&D Beyond character link; return the id."""
    text = str(value or "").strip()
    if text.isdigit():
        return text
    m = re.search(r"dndbeyond\.com/(?:profile/[^/]+/)?characters/(\d+)", text)
    return m.group(1) if m else None


def fetch_character_json(ddb_id: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """The character's public JSON (the "data" object). Raises DdbError."""
    req = urllib.request.Request(
        CHARACTER_URL.format(id=ddb_id), headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise DdbError(
                "D&D Beyond says this character is private. Its player can change Character Privacy "
                "to Public in the character's settings on D&D Beyond."
            ) from e
        if e.code == 404:
            raise DdbError("D&D Beyond has no character with that id.") from e
        raise DdbError(f"D&D Beyond answered with an error ({e.code}). Try again later.") from e
    except (TimeoutError, socket.timeout) as e:
        raise DdbError("D&D Beyond took too long to answer. Try again later.") from e
    except urllib.error.URLError as e:
        raise DdbError("Couldn't reach D&D Beyond. Try again later.") from e
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise DdbError("D&D Beyond sent something that isn't character data.") from e
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not payload.get("success", True) or not data.get("name"):
        raise DdbError("D&D Beyond sent something that isn't character data.")
    return data


ALWAYS_PREPARED_URL = (
    "https://character-service.dndbeyond.com/character/v5/game-data/always-prepared-spells"
    "?classId={class_id}&classLevel={level}&sharingSetting=2"
)


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


CLASS_SPELLS_URLS = (  # what a class can prepare: leveled spells, then cantrips
    "https://character-service.dndbeyond.com/character/v5/game-data/always-known-spells"
    "?classId={class_id}&classLevel={level}&sharingSetting=2",
    "https://character-service.dndbeyond.com/character/v5/game-data/spells"
    "?classId={class_id}&classLevel={level}&sharingSetting=2",
)
SPELL_FIELDS = ("id", "name", "level", "school", "duration", "activation", "range", "concentration", "ritual",
                "components", "componentsDescription", "saveDcAbilityId", "requiresAttackRoll", "requiresSavingThrow",
                "modifiers", "tags", "scaleType", "castingTimeDescription", "description")


def _slim_spell(s: dict) -> dict:
    """Only what the parser reads, so a class's whole spell list stays small."""
    df = s.get("definition") or {}
    slim = {k: df.get(k) for k in SPELL_FIELDS if k in df}
    slim["description"] = (df.get("description") or "")[:1500]
    slim["sources"] = [{"sourceId": i} for i in _source_ids(df)]
    slim["modifiers"] = [{k: m.get(k) for k in ("type", "subType", "friendlySubtypeName", "die")} for m in df.get("modifiers") or []]
    return {"definition": slim, "prepared": False, "alwaysPrepared": bool(s.get("alwaysPrepared"))}


def _spell_list(url: str, timeout: float) -> list:
    try:
        payload = _get_json(url, timeout)
    except (OSError, ValueError):
        return []
    spells = payload.get("data") if isinstance(payload, dict) else None
    return spells if isinstance(spells, list) else []


def fetch_character(ddb_id: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """The character, plus two things D&D Beyond's sheet loads separately:
    - the spells each class and subclass always has prepared (e.g. Circle of the
      Moon spells), under data["askdnd"]["alwaysPreparedSpells"];
    - every spell each class could prepare at its level (for the spell planner),
      under data["askdnd"]["availableSpells"].
    If those extra calls fail, the character still loads, just without them."""
    data = fetch_character_json(ddb_id, timeout)
    always, available = {}, {}
    for c in data.get("classes") or []:
        level = c.get("level") or 0
        for key in ("definition", "subclassDefinition"):
            class_id = _d(c, key, "id")
            if not class_id:
                continue
            spells = _spell_list(ALWAYS_PREPARED_URL.format(class_id=class_id, level=level), timeout)
            if spells:
                always[str(class_id)] = spells
        class_id = _d(c, "definition", "id")
        if class_id and _d(c, "definition", "canCastSpells"):
            seen, pool = set(), []
            for url in CLASS_SPELLS_URLS:
                for sp in _spell_list(url.format(class_id=class_id, level=level), timeout):
                    name = _d(sp, "definition", "name")
                    if name and name not in seen:
                        seen.add(name)
                        pool.append(_slim_spell(sp))
            if pool:
                available[str(class_id)] = pool
    data["askdnd"] = {"alwaysPreparedSpells": always, "availableSpells": available}
    return data


# The player's own writing on D&D Beyond:
# - Background tab (personality traits, ideals, bonds, flaws, appearance) and the
#   backstory: kept and shown to everyone, the DM included (Brett, 2026-10-17).
# - Item notes: kept apart (item_notes -> CharacterItemNote), shown to everyone.
# - The rest of the Notes tab (allies, enemies, organizations, other notes):
#   dropped, never stored.
# None of it goes into test fixtures (scripts/ddb_fixture.py strips it), so none is in git.
ITEM_NOTE_VALUE_TYPE = 9
KEPT_NOTES = ("backstory",)
ALIGNMENTS = {1: "Lawful Good", 2: "Neutral Good", 3: "Chaotic Good", 4: "Lawful Neutral", 5: "Neutral",
              6: "Chaotic Neutral", 7: "Lawful Evil", 8: "Neutral Evil", 9: "Chaotic Evil"}
SIZES = {1: "Tiny", 2: "Tiny", 3: "Small", 4: "Medium", 5: "Large", 6: "Huge", 7: "Gargantuan"}


def item_notes(data: dict) -> list[dict]:
    """Players' notes on items, from the raw D&D Beyond data (before sanitize drops them):
    [{"ref": "item:<id>" | "custom:<id>", "name", "note"}]. Stored apart (CharacterItemNote)."""
    rows = lambda key: [x for x in data.get(key) or [] if isinstance(x, dict)]  # noqa: E731 (odd data: skip, don't fail)
    inventory = {str(i.get("id")): _d(i, "definition", "name", default="") for i in rows("inventory")}
    custom = {str(c.get("id")): c for c in rows("customItems")}
    out: dict[str, dict] = {}
    for v in rows("characterValues"):
        note, vid = (v.get("value") or "").strip() if isinstance(v.get("value"), str) else "", str(v.get("valueId"))
        if v.get("typeId") != ITEM_NOTE_VALUE_TYPE or not note:
            continue
        if vid in inventory:
            out[f"item:{vid}"] = {"ref": f"item:{vid}", "name": inventory[vid], "note": note}
        elif vid in custom:
            out[f"custom:{vid}"] = {"ref": f"custom:{vid}", "name": custom[vid].get("name") or "", "note": note}
    for cid, c in custom.items():
        note = (c.get("notes") or "").strip()
        if note and f"custom:{cid}" not in out:
            out[f"custom:{cid}"] = {"ref": f"custom:{cid}", "name": c.get("name") or "", "note": note}
    return list(out.values())


def sanitize(data: dict) -> dict:
    clean = {k: v for k, v in data.items() if k != "notes"}
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
    clean["notes"] = {k: notes[k] for k in KEPT_NOTES if notes.get(k)}
    values = data.get("characterValues") or []
    clean["characterValues"] = [v for v in values if v.get("typeId") != ITEM_NOTE_VALUE_TYPE]
    # Only *which* items have a note stays in this copy, never the note (notes go to CharacterItemNote).
    clean["noteItemIds"] = sorted({n["ref"] for n in item_notes(data)})
    clean["customItems"] = [{k: v for k, v in c.items() if k != "notes"} for c in data.get("customItems") or []]
    return clean


# ---------------------------------------------------------------- helpers


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str | None) -> str:
    """D&D Beyond descriptions are HTML; keep paragraphs, drop markup."""
    if not html:
        return ""
    p = _Text()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"\[([a-z]+)\][^\[;]*;([^\[]*)\[/\1\]", r"\2", text)  # [rules]short rest;Short[/rules]: the text after ";" is shown
    text = re.sub(r"\[/?[a-z]+(?:[ =][^\]]*)?\]", "", text)  # D&D Beyond link tags: [rules]Unarmed Strike[/rules]
    text = re.sub(r"\{\{[^}]*\}\}", "(see D&D Beyond)", text)  # sheet formulas we don't evaluate
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


TEMPLATE = re.compile(r"\{\{([^}]*)\}\}")
ABBR = {"str": "strength", "dex": "dexterity", "con": "constitution", "int": "intelligence", "wis": "wisdom", "cha": "charisma"}


def render_template(text: str, values: dict) -> str:
    """Fill in D&D Beyond's sheet formulas, e.g. "{{(classlevel/2)@rounddown}}" -> "3".

    `values` holds numbers for classlevel, characterlevel, proficiency, maxhp,
    modifier:<abbr>, savedc:<abbr>, spellattack:<abbr>, and scalevalue (a number
    or dice like "1d6"). Anything we can't work out reads "(see D&D Beyond)"."""

    def one(m):
        expr = m.group(1).strip()
        fmt, _, rest = expr.partition("#")
        body, _, rounding = fmt.partition("@")
        flags = [f.strip() for f in (rest or "").split(",") if f.strip()]
        rules = [r.strip() for r in rounding.split(",") if r.strip()] + [f for f in flags if f.startswith(("min:", "max:"))]
        scale = values.get("scalevalue")
        if body.strip() == "scalevalue" and isinstance(scale, str):
            return scale
        def var(v):
            v = v.group(0)
            if v in values and not isinstance(values[v], str):
                return str(values[v])
            raise KeyError(v)
        try:
            arithmetic = re.sub(r"[a-z]+(?::[a-z]+)?", var, body.replace(" ", ""))
            if not re.fullmatch(r"[\d+\-*/().]+", arithmetic):
                raise ValueError(body)
            n = eval(arithmetic, {"__builtins__": {}})  # digits and + - * / ( ) only (checked above)
        except (KeyError, ValueError, SyntaxError, ZeroDivisionError):
            return "(see D&D Beyond)"
        n = int(-(-n // 1)) if "roundup" in rules else int(n // 1)
        for r in rules:
            if r.startswith("min:") and r[4:].lstrip("-").isdigit():
                n = max(n, int(r[4:]))
            if r.startswith("max:") and r[4:].lstrip("-").isdigit():
                n = min(n, int(r[4:]))
        return _signed(n).replace("−", "-") if "signed" in flags else str(abs(n) if "unsigned" in flags else n)

    return TEMPLATE.sub(one, text or "")


def _source_ids(df: dict) -> list[int]:
    return [s.get("sourceId") for s in df.get("sources") or [] if isinstance(s, dict) and s.get("sourceId")]
def _d(obj, *path, default=None):
    """Safe nested lookup: _d(x, "a", "b") is x["a"]["b"] or default."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return default if obj is None else obj
def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{-n}"


# The parser lives in app/ddb_sheet.py; these names stay available here (ddb.parse_character…)
from app.ddb_sheet import _Sheet, parse_character  # noqa: E402,F401
