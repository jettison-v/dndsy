"""D&D Beyond character data: fetch, sanitize and parse.

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


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _story(data: dict) -> dict:
    """The Background tab: who the character is, in the player's words."""
    traits = data.get("traits") if isinstance(data.get("traits"), dict) else {}
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
    text = lambda v: html_to_text(v) if isinstance(v, str) else ""  # noqa: E731
    looks = [("Alignment", ALIGNMENTS.get(data.get("alignmentId"), "")), ("Gender", data.get("gender")), ("Eyes", data.get("eyes")),
             ("Size", SIZES.get(_d(data, "race", "sizeId"), "")), ("Height", data.get("height")), ("Faith", data.get("faith")),
             ("Hair", data.get("hair")), ("Skin", data.get("skin")), ("Age", data.get("age")),
             ("Weight", f"{data['weight']} lb." if data.get("weight") else "")]
    bg = _d(data, "background", "definition") or {}
    return {
        "background": bg.get("name") or "",
        "background_text": _first_paragraph(html_to_text(bg.get("shortDescription") or bg.get("description")), 400),
        "characteristics": [(k, str(v).strip()) for k, v in looks if v not in (None, "") and str(v).strip()],
        "traits": [(label, text(traits.get(key))) for key, label in (("personalityTraits", "Personality traits"), ("ideals", "Ideals"),
                                                                     ("bonds", "Bonds"), ("flaws", "Flaws")) if text(traits.get(key))],
        "appearance": text(traits.get("appearance")),
        "backstory": text(notes.get("backstory")),
    }


def _portrait(data: dict) -> str:
    """The character's picture on D&D Beyond (their image server), or ""."""
    url = (data.get("decorations") or {}).get("avatarUrl") or ""
    return url if re.match(r"https://(www\.)?dndbeyond\.com/avatars/", url) else ""


def _first_paragraph(text: str, limit: int = 320) -> str:
    para = next((p for p in text.split("\n") if p.strip()), "")
    return para if len(para) <= limit else para[: limit - 1].rsplit(" ", 1)[0] + "…"


def _mod(score: int) -> int:
    return (score - 10) // 2


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{-n}"


ABILITIES = [
    (1, "strength", "Strength", "Str"),
    (2, "dexterity", "Dexterity", "Dex"),
    (3, "constitution", "Constitution", "Con"),
    (4, "intelligence", "Intelligence", "Int"),
    (5, "wisdom", "Wisdom", "Wis"),
    (6, "charisma", "Charisma", "Cha"),
]
ABILITY_KEY = {i: key for i, key, _, _ in ABILITIES}

SKILLS = [
    ("Acrobatics", "dexterity"), ("Animal Handling", "wisdom"), ("Arcana", "intelligence"),
    ("Athletics", "strength"), ("Deception", "charisma"), ("History", "intelligence"),
    ("Insight", "wisdom"), ("Intimidation", "charisma"), ("Investigation", "intelligence"),
    ("Medicine", "wisdom"), ("Nature", "intelligence"), ("Perception", "wisdom"),
    ("Performance", "charisma"), ("Persuasion", "charisma"), ("Religion", "intelligence"),
    ("Sleight of Hand", "dexterity"), ("Stealth", "dexterity"), ("Survival", "wisdom"),
]

ACTIVATION = {1: "Action", 2: "No action", 3: "Bonus action", 4: "Reaction", 6: "Minute", 7: "Hour", 8: "Special"}
RESET = {1: "Short or Long Rest", 2: "Long Rest", 3: "Dawn", 4: "Other"}
COMPONENTS = {1: "V", 2: "S", 3: "M"}
CR = {1: "0", 2: "1/8", 3: "1/4", 4: "1/2"}
CREATURE_GROUPS = {13: "Wild Shape form"}
SIMPLE_WEAPONS = {"Club", "Dagger", "Greatclub", "Handaxe", "Javelin", "Light Hammer", "Mace", "Quarterstaff",
                  "Sickle", "Spear", "Dart", "Crossbow, Light", "Shortbow", "Sling"}
MARTIAL_WEAPONS = {"Battleaxe", "Flail", "Glaive", "Greataxe", "Greatsword", "Halberd", "Lance", "Longsword", "Maul",
                   "Morningstar", "Pike", "Rapier", "Scimitar", "Shortsword", "Trident", "Warhammer", "War Pick", "Whip",
                   "Blowgun", "Crossbow, Hand", "Crossbow, Heavy", "Longbow", "Musket", "Pistol"}
DAMAGE_TYPES = {"acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison",
                "psychic", "radiant", "slashing", "thunder"}
PROFICIENCY_GROUPS = {174869515: "armor", 660121713: "weapons", 1782728300: "weapons", 2103445194: "tools"}

# The table plays with the 2024 core rulebooks only (CLAUDE.md). D&D Beyond adds
# some rules from other books to every character; those are left out.
NON_CORE_RULES = re.compile(r"^(Initiate a Circle Spell|Circle Spell:)", re.I)
CORE_SOURCES = {145, 146, 147}  # Player's Handbook (2024), Dungeon Master's Guide (2024), Monster Manual (2025)
SOURCE_NAMES = {1: "PHB 2014", 2: "MM 2014", 3: "DMG 2014", 4: "Xanathar's", 145: "PHB 2024", 146: "DMG 2024", 147: "MM 2025"}


def _source_ids(df: dict) -> list[int]:
    return [s.get("sourceId") for s in df.get("sources") or [] if isinstance(s, dict) and s.get("sourceId")]


USABLE_NAME = re.compile(r"(Spells|^Spellcasting|^Pact Magic|^Extra Attack|^Eldritch Invocations)$", re.I)
USABLE_TEXT = re.compile(r"\b(as a bonus action|take a bonus action|as a reaction|use your reaction|take a magic action|"
                         r"as a magic action|you can cast|you know the \w[\w' ]* cantrip)\b", re.I)

# Feature names that are only headings on D&D Beyond, not something you can do.
SKIP_FEATURES = re.compile(
    r"^(core .* traits|.* subclass|(\d+: )?ability score improvements?|ability score increases?|hit points|"
    r"proficiencies|equipment|age|size|speed|languages|creature type|alignment|epic boon)$",
    re.I,
)

# Standard spell slots by caster level (multiclass table, 2024 PHB).
FULL_CASTER_SLOTS = [
    [], [2], [3], [4, 2], [4, 3], [4, 3, 2], [4, 3, 3], [4, 3, 3, 1], [4, 3, 3, 2], [4, 3, 3, 3, 1],
    [4, 3, 3, 3, 2], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1, 1], [4, 3, 3, 3, 2, 1, 1],
    [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1, 1], [4, 3, 3, 3, 3, 1, 1, 1, 1],
    [4, 3, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 3, 2, 2, 1, 1],
]


def _adv_note(m: dict) -> str:
    """A short label for a save or skill: "Advantage", or "Adv. to maintain Concentration"."""
    restriction = re.sub(r"^(saving throws|checks)( that you make)?\s*", "", (m.get("restriction") or "").strip().rstrip("."), flags=re.I)
    return f"Adv. {restriction}" if restriction else "Advantage"


def _d(obj, *path, default=None):
    """Safe nested lookup: _d(x, "a", "b") is x["a"]["b"] or default."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return default if obj is None else obj


# ---------------------------------------------------------------- parsing


class _Sheet:
    """One parse of one character. Methods build the sections of the summary."""

    def __init__(self, data: dict):
        self.d = data
        self.classes = [c for c in data.get("classes") or [] if _d(c, "definition", "name")]
        self.level = sum(c.get("level") or 0 for c in self.classes) or 1
        self.pb = 2 + (self.level - 1) // 4
        self.items = data.get("inventory") or []
        self.active_item_defs = {
            _d(i, "definition", "id")
            for i in self.items
            if i.get("equipped") and (i.get("isAttuned") or not _d(i, "definition", "canAttune"))
        }
        self.equipped_item_defs = {_d(i, "definition", "id") for i in self.items if i.get("equipped")}
        # Features of a class you multiclassed into (e.g. its saving throws) don't all carry over.
        self.multiclass_features = {
            _d(f, "definition", "id")
            for c in self.classes
            if not c.get("isStartingClass")
            for f in c.get("classFeatures") or []
        } if len(self.classes) > 1 else set()
        self.modifiers = [m for source, m in self._all_modifiers() if self._applies(source, m)]
        self.names = self._component_names()
        self.background_asi = any(
            (_d(f, "definition", "name") or "").endswith("Ability Score Improvements") for f in data.get("feats") or []
        )
        self.scores = self._scores()
        self.mods = {k: _mod(v) for k, v in self.scores.items()}

    # modifiers ---------------------------------------------------------

    def source_name(self, m: dict) -> str:
        """Where a modifier comes from ("Unarmored Defense", "Stone of Good Luck")."""
        return self.names.get(m.get("componentId")) or "a feature"

    def bonus_parts(self, sub: str) -> list[tuple[str, int]]:
        """[(where it comes from, amount)] for the bonuses to one number."""
        return [(self.source_name(m), self.bonus_value(m)) for m in self.mods_of(("bonus", "stacking-bonus"), sub) if self.bonus_value(m)]

    def _all_modifiers(self):
        for source, group in (self.d.get("modifiers") or {}).items():
            for m in group or []:
                yield source, m

    def _applies(self, source: str, m: dict) -> bool:
        """Item modifiers count only while the item is equipped (and attuned if it needs it);
        some class modifiers count only for your first class."""
        if source == "class":
            return m.get("availableToMulticlass") is not False or m.get("componentId") not in self.multiclass_features
        if source != "item":
            return True
        active = self.active_item_defs if m.get("requiresAttunement") else self.equipped_item_defs
        return m.get("componentId") in active

    def template_values(self, class_level: int | None = None, scale=None) -> dict:
        v = {"classlevel": class_level or self.level, "characterlevel": self.level, "proficiency": self.pb}
        if getattr(self, "mods", None):
            for short, key in ABBR.items():
                v[f"modifier:{short}"] = self.mods[key]
                v[f"savedc:{short}"] = 8 + self.pb + self.mods[key]
                v[f"spellattack:{short}"] = self.pb + self.mods[key]
        if scale:
            v["scalevalue"] = _d(scale, "dice", "diceString") or scale.get("fixedValue")
        return v

    def what_it_does(self, df: dict, class_level: int | None = None, scale=None) -> str:
        """D&D Beyond's short mechanics text (snippet) with its formulas filled in;
        falls back to the first paragraph of the full description."""
        snippet = df.get("snippet") or ""
        if snippet.strip():
            return html_to_text(render_template(snippet, self.template_values(class_level, scale)))
        return _first_paragraph(html_to_text(df.get("description")), 400)

    def mods_of(self, type_: str | tuple, sub: str | None = None) -> list[dict]:
        types = (type_,) if isinstance(type_, str) else type_
        return [m for m in self.modifiers if m.get("type") in types and (sub is None or m.get("subType") == sub)]

    def bonus_value(self, m: dict) -> int:
        """A bonus is a fixed number, or an ability modifier (e.g. "add your Wisdom modifier")."""
        if m.get("value") is not None:
            return int(m["value"])
        if m.get("fixedValue") is not None:
            return int(m["fixedValue"])
        if m.get("statId") and getattr(self, "mods", None):
            return max(1, self.mods.get(ABILITY_KEY.get(m["statId"]), 0))
        return 0

    def total_bonus(self, sub: str) -> int:
        return sum(self.bonus_value(m) for m in self.mods_of(("bonus", "stacking-bonus"), sub))

    # numbers -----------------------------------------------------------

    def _scores(self) -> dict:
        stats = {s.get("id"): s.get("value") for s in self.d.get("stats") or []}
        bonus = {s.get("id"): s.get("value") for s in self.d.get("bonusStats") or []}
        override = {s.get("id"): s.get("value") for s in self.d.get("overrideStats") or []}
        out = {}
        for sid, key, _, _ in ABILITIES:
            if override.get(sid):
                out[key] = override[sid]
                continue
            base = (stats.get(sid) or 10) + (bonus.get(sid) or 0)
            base += sum(int(m.get("value") or 0) for m in self.mods_of("bonus", f"{key}-score") if not self._ignored_species_bonus(m))
            cap_raise = sum(
                int(m.get("value") or 0) for m in self.mods_of("bonus", "ability-score-maximum") if m.get("statId") == sid
            )
            score = min(base, min(30, 20 + cap_raise))
            for m in self.mods_of("set", f"{key}-score"):  # e.g. Belt of Giant Strength
                score = max(score, int(m.get("value") or 0))
            # stacking bonuses go on top of a set score (Hammer of Thunderbolts: Belt + 4)
            score += sum(int(m.get("value") or 0) for m in self.mods_of("stacking-bonus", f"{key}-score"))
            out[key] = min(score, 30)
        return out

    def _ignored_species_bonus(self, m: dict) -> bool:
        """2024 rules: ability increases come from the background. D&D Beyond ignores a
        legacy (2014) species' increases when the background provides them."""
        if not self.background_asi or not _d(self.d, "race", "isLegacy"):
            return False
        return any(m is x for x in (self.d.get("modifiers") or {}).get("race") or [])

    def proficient(self, sub: str) -> bool:
        return bool(self.mods_of("proficiency", sub))

    def armor(self) -> tuple[dict | None, dict | None]:
        body = shield = None
        for i in self.items:
            df = i.get("definition") or {}
            if not i.get("equipped") or df.get("armorClass") is None:
                continue
            if df.get("armorTypeId") == 4:
                shield = df
            elif df.get("armorTypeId") in (1, 2, 3):
                body = df
        return body, shield

    def armor_class(self) -> int:
        return self.armor_class_parts()["total"]

    def armor_class_parts(self) -> dict:
        """AC and how it adds up: [(what, amount)], plus notes."""
        body, shield = self.armor()
        dex = self.mods["dexterity"]
        parts, notes = [], []
        if body:
            kind = body.get("armorTypeId")
            parts.append((f"{body['name']} ({ {1: 'light', 2: 'medium', 3: 'heavy'}.get(kind, '') } armor)", body["armorClass"]))
            if kind == 1:
                parts.append(("Dexterity modifier", dex))
            elif kind == 2:
                parts.append(("Dexterity modifier (medium armor: at most +2)", min(dex, 2)))
            else:
                notes.append("Heavy armor: no Dexterity modifier.")
            parts += self.bonus_parts("armored-armor-class")
        else:
            parts += [("No armor", 10), ("Dexterity modifier", dex)]
            extra = [(self.source_name(m), ABILITY_KEY.get(m.get("statId"))) for m in self.mods_of("set", "unarmored-armor-class") if m.get("statId")]
            if extra:  # Unarmored Defense (Monk: Wis, Barbarian: Con) — the best one applies
                name, key = max(extra, key=lambda e: self.mods.get(e[1], 0))
                parts.append((f"{name} ({key.title()} modifier)", self.mods.get(key, 0)))
            parts += self.bonus_parts("unarmored-armor-class")
        if shield:
            parts.append((shield["name"], shield["armorClass"]))
        parts += self.bonus_parts("armor-class")
        total = sum(v for _, v in parts)
        for m in self.mods_of("set", "armor-class"):
            if int(m.get("value") or 0) > total:
                total = int(m["value"])
                notes.append(f"{self.source_name(m)} sets your AC to {total}.")
        return {"total": total, "parts": parts, "notes": notes}

    def hit_points(self) -> dict:
        d = self.d
        parts, notes = [], []
        if d.get("overrideHitPoints"):
            maximum = d["overrideHitPoints"]
            notes.append("The maximum is set by hand on D&D Beyond.")
        else:
            con = self.mods["constitution"]
            parts.append(("Hit dice: the full first die, then the fixed or rolled amount each level", d.get("baseHitPoints") or 0))
            parts.append((f"Constitution modifier ({_signed(con)}) × {self.level} levels", con * self.level))
            parts += [(f"{name} ({_signed(v)} per level × {self.level})", v * self.level) for name, v in self.bonus_parts("hit-points-per-level")]
            if d.get("bonusHitPoints"):
                parts.append(("Bonus set on D&D Beyond", d["bonusHitPoints"]))
            maximum = sum(v for _, v in parts)
        return {
            "parts": parts,
            "notes": notes,
            "damage": d.get("removedHitPoints") or 0,
            "max": maximum,
            "current": max(0, maximum - (d.get("removedHitPoints") or 0)),
            "temp": d.get("temporaryHitPoints") or 0,
            "hit_dice": [
                {"class": _d(c, "definition", "name"), "die": f"d{_d(c, 'definition', 'hitDice', default=8)}",
                 "total": c.get("level") or 0, "used": c.get("hitDiceUsed") or 0}
                for c in self.classes
            ],
        }

    def speeds(self) -> dict:
        normal = _d(self.d, "race", "weightSpeeds", "normal", default={}) or {}
        base = (f"{_d(self.d, 'race', 'fullName', default='Species')} base speed", normal.get("walk") or 30)
        for m in self.mods_of("set", "innate-speed-walking"):
            if int(m.get("value") or 0) > base[1]:
                base = (f"{self.source_name(m)} (sets your base speed)", int(m["value"]))
        parts = [base] + self.bonus_parts("speed") + self.bonus_parts("speed-walking")
        body, shield = self.armor()
        notes = []
        if not body and not shield:
            parts += self.bonus_parts("unarmored-movement")
        elif self.bonus_parts("unarmored-movement"):
            notes.append("Unarmored Movement doesn't count while you wear armor or carry a shield.")
        walk = sum(v for _, v in parts)
        out = {"walk": walk, "parts": parts, "notes": notes}
        for kind in ("fly", "swim", "climb", "burrow"):
            v = normal.get(kind) or 0
            for m in self.mods_of("set", f"innate-speed-{kind}"):
                v = max(v, int(m.get("value") or 0) or walk)
            if v:
                out[kind] = v
        return out

    def saves(self) -> list[dict]:
        out = []
        general = self.total_bonus("saving-throws")
        for _, key, name, short in ABILITIES:
            prof = self.proficient(f"{key}-saving-throws")
            total = self.mods[key] + (self.pb if prof else 0) + general + self.total_bonus(f"{key}-saving-throws")
            adv = bool(self.mods_of("advantage", f"{key}-saving-throws"))
            notes = [_adv_note(m) for m in self.mods_of("advantage", f"{key}-saving-throws")]
            out.append({"ability": name, "short": short, "bonus": total, "label": _signed(total), "proficient": prof, "advantage": adv,
                        "notes": notes})
        return out

    def skills(self) -> list[dict]:
        out = []
        checks = self.total_bonus("ability-checks")
        half = bool(self.mods_of("half-proficiency", "ability-checks"))
        for name, ability in SKILLS:
            sub = name.lower().replace(" ", "-")
            level = "expertise" if self.mods_of("expertise", sub) else "proficient" if self.proficient(sub) else ""
            prof = self.pb * 2 if level == "expertise" else self.pb if level else (self.pb // 2 if half else 0)
            parts = [(f"{ability.title()} modifier", self.mods[ability])]
            if prof:
                parts.append(("Expertise (twice your Proficiency Bonus)" if level == "expertise" else "Proficiency Bonus" if level
                              else "Half your Proficiency Bonus (Jack of All Trades)", prof))
            parts += self.bonus_parts("ability-checks") + self.bonus_parts(sub)
            total = sum(v for _, v in parts)
            notes = [_adv_note(m) for m in self.mods_of("advantage", sub)]
            out.append({"name": name, "ability": ability[:3].title(), "bonus": total, "label": _signed(total), "proficiency": level or ("half" if half else ""),
                        "notes": notes, "parts": parts})
        return out

    def initiative(self) -> int:
        return sum(v for _, v in self.initiative_parts())

    def initiative_parts(self) -> list[tuple[str, int]]:
        # an "initiative" bonus already covers items that also boost ability checks (Luckstone)
        parts = [("Dexterity modifier", self.mods["dexterity"])] + self.bonus_parts("initiative")
        prof = self.mods_of("proficiency", "initiative")
        if prof:
            parts.append((f"Proficiency Bonus ({self.source_name(prof[0])})", self.pb))
        return parts

    # lists -------------------------------------------------------------

    def proficiencies(self) -> dict:
        groups = {"armor": [], "weapons": [], "tools": [], "languages": []}
        for m in self.mods_of(("proficiency", "language", "monk-weapon")):
            name = (m.get("friendlySubtypeName") or m.get("subType") or "").strip()
            sub = m.get("subType") or ""
            if not name or sub.startswith("choose-") or sub.endswith("saving-throws"):
                continue
            if m["type"] == "language":
                group = "languages"
            else:
                group = PROFICIENCY_GROUPS.get(m.get("entityTypeId"))
            if group and name not in groups[group]:
                groups[group].append(name)
        # like D&D Beyond, don't list a weapon that a category already covers
        covered = (SIMPLE_WEAPONS if "Simple Weapons" in groups["weapons"] else set()) | (
            MARTIAL_WEAPONS if "Martial Weapons" in groups["weapons"] else set())
        groups["weapons"] = sorted(w for w in groups["weapons"] if w not in covered)
        senses = [
            f"{m.get('friendlySubtypeName') or m.get('subType')} {m.get('value')} ft"
            for m in self.mods_of(("set-base", "sense"))
            if m.get("value")
        ]
        defenses = {}
        for kind, label in (("resistance", "Resistances"), ("immunity", "Immunities"), ("vulnerability", "Vulnerabilities")):
            names = sorted({m.get("friendlySubtypeName") or m.get("subType") for m in self.mods_of(kind)})
            if names:
                defenses[label] = names
        adv = sorted({
            (m.get("friendlySubtypeName") or m.get("subType")) + (f" ({m['restriction']})" if m.get("restriction") else "")
            for m in self.mods_of("advantage")
        })
        if adv:
            defenses["Advantage on"] = adv
        return {**groups, "senses": sorted(set(senses)), "defenses": defenses}

    def limited_use(self, lu: dict | None) -> dict | None:
        """Uses per rest. D&D Beyond stores a base number, optionally plus an ability
        modifier or the proficiency bonus."""
        if not lu:
            return None
        maximum = lu.get("maxUses") or 0
        if lu.get("useProficiencyBonus"):
            maximum = maximum * self.pb if lu.get("proficiencyBonusOperator") == 2 and maximum else maximum + self.pb
        if lu.get("statModifierUsesId"):
            maximum += max(1, self.mods.get(ABILITY_KEY.get(lu["statModifierUsesId"]), 0))
        if maximum <= 0:
            return None
        reset = lu.get("resetType")
        reset_label = RESET.get(reset, reset) if isinstance(reset, int) else (reset or "")
        if reset_label == "Consumable":
            reset_label = "Used up"
        used = lu.get("numberUsed") or 0
        note = lu.get("resetTypeDescription") or ""
        phrase = {"Dawn": "back at dawn", "Used up": "gone once used", "Other": note or "see the description"}.get(
            reset_label, f"back after a {reset_label}" if reset_label else note)
        return {"max": maximum, "used": used, "left": max(0, maximum - used), "reset": reset_label,
                "reset_note": note, "reset_phrase": phrase}

    def _feature_owners(self) -> dict:
        """Feature id -> (class level, level scale), for filling in formulas."""
        owners = {}
        for c in self.classes:
            for f in c.get("classFeatures") or []:
                owners[_d(f, "definition", "id")] = (c.get("level"), f.get("levelScale"))
        return owners

    def actions(self) -> list[dict]:
        out, seen = [], set()
        owners = self._feature_owners()
        for source, group in (self.d.get("actions") or {}).items():
            for a in group or []:
                name = (a.get("name") or "").strip()
                kind = _d(a, "activation", "activationType")
                if not name or (name, kind) in seen or NON_CORE_RULES.match(name):
                    continue  # e.g. Circle Magic (Forgotten Realms): our table uses the 2024 core books only
                seen.add((name, kind))
                class_level, scale = owners.get(a.get("componentId"), (None, None))
                values = self.template_values(class_level, scale)
                out.append({
                    "key": f"action:{name}",
                    "name": name,
                    "source": source,
                    "activation": ACTIVATION.get(kind, ""),
                    "uses": self.limited_use(a.get("limitedUse")),
                    "summary": self.what_it_does(a, class_level, scale),
                    "text": html_to_text(render_template(a.get("description") or a.get("snippet") or "", values)),
                    "rule": False,
                })
        return out

    def features(self) -> list[dict]:
        out, seen = [], set()
        acted = {a.get("componentId") for group in (self.d.get("actions") or {}).values() for a in group or []}
        casts = {s.get("componentId") for group in (self.d.get("spells") or {}).values() for s in group or []}

        def usable(df: dict, name: str, text: str) -> bool:
            """Something you do (an action, a resource, spells), as opposed to a rule
            that's simply part of your numbers (Fleet of Foot, Keen Senses)."""
            return bool(df.get("id") in acted or df.get("id") in casts or df.get("limitedUse")
                        or USABLE_NAME.search(name) or USABLE_TEXT.search(text))

        def add(name, source, desc, required_level=None, df=None, class_level=None, scale=None):
            name = (name or "").strip()
            if not name or SKIP_FEATURES.match(name) or (name, source) in seen:
                return
            seen.add((name, source))
            text = html_to_text(render_template(desc, self.template_values(class_level, scale)))
            out.append({"key": f"feature:{source}:{name}", "name": name, "source": source, "level": required_level,
                        "summary": self.what_it_does(df or {"description": desc}, class_level, scale), "text": text,
                        "use": usable(df or {}, name, text)})

        for c in self.classes:
            cname = _d(c, "definition", "name")
            sub = _d(c, "subclassDefinition", "name")
            sub_id = _d(c, "subclassDefinition", "id")
            feats = sorted(c.get("classFeatures") or [], key=lambda f: _d(f, "definition", "requiredLevel", default=0))
            for f in feats:
                df = f.get("definition") or {}
                if df.get("hideInSheet") or (df.get("requiredLevel") or 0) > (c.get("level") or 0):
                    continue
                label = sub if sub and (df.get("isSubClassFeature") or (sub_id and df.get("classId") == sub_id)) else cname
                add(df.get("name"), label, df.get("description"), df.get("requiredLevel"), df,
                    class_level=c.get("level"), scale=f.get("levelScale"))
        species = _d(self.d, "race", "fullName", default="Species")
        for t in _d(self.d, "race", "racialTraits", default=[]):
            df = t.get("definition") or {}
            if not df.get("hideInSheet"):
                add(df.get("name"), species, df.get("description"), df=df)
        for f in self.d.get("feats") or []:
            df = f.get("definition") or {}
            add(df.get("name"), "Feat", df.get("description"), df=df)
        for group in (self.d.get("options") or {}).values():
            for o in group or []:
                df = o.get("definition") or {}
                if not re.match(r"^(increase .*|strength|dexterity|constitution|intelligence|wisdom|charisma)$", df.get("name") or "", re.I):
                    add(df.get("name"), "Choice", df.get("description"), df={**df, "id": o.get("componentId")})
        return out

    def spell_slots(self) -> dict:
        casters = [c for c in self.classes if _d(c, "definition", "canCastSpells") or _d(c, "subclassDefinition", "canCastSpells")]
        pact = [c for c in casters if _d(c, "definition", "name") == "Warlock"]
        regular = [c for c in casters if c not in pact]

        def table_row(c):
            rules = _d(c, "definition", "spellRules") or _d(c, "subclassDefinition", "spellRules") or {}
            rows = rules.get("levelSpellSlots") or []
            lvl = c.get("level") or 0
            return [n for n in (rows[lvl] if lvl < len(rows) else [])]

        slots: list[int] = []
        if len(regular) == 1:
            slots = table_row(regular[0])
        elif regular:
            caster_level = 0
            for c in regular:
                rules = _d(c, "definition", "spellRules") or _d(c, "subclassDefinition", "spellRules") or {}
                div = rules.get("multiClassSpellSlotDivisor") or 1
                lvl = c.get("level") or 0
                caster_level += -(-lvl // div) if rules.get("multiClassSpellSlotRounding") == 2 else lvl // div
            slots = FULL_CASTER_SLOTS[min(caster_level, 20)]
        used = {s.get("level"): s.get("used") or 0 for s in self.d.get("spellSlots") or []}
        out = {"slots": [{"level": i + 1, "max": n, "used": used.get(i + 1, 0)} for i, n in enumerate(slots) if n]}
        if pact:
            row = table_row(pact[0])
            level = max((i + 1 for i, n in enumerate(row) if n), default=0)
            if level:
                pused = {s.get("level"): s.get("used") or 0 for s in self.d.get("pactMagic") or []}
                out["pact"] = {"level": level, "max": row[level - 1], "used": pused.get(level, 0)}
        return out

    def spellcasting(self) -> list[dict]:
        out = []
        for c in self.classes:
            df = c.get("definition") or {}
            ability_id = df.get("spellCastingAbilityId") or _d(c, "subclassDefinition", "spellCastingAbilityId")
            if not ability_id or not (df.get("canCastSpells") or _d(c, "subclassDefinition", "canCastSpells")):
                continue
            key = ABILITY_KEY.get(ability_id, "wisdom")
            mod = self.mods[key]
            common = [("Proficiency Bonus", self.pb), (f"{key.title()} modifier", mod)]
            dc_parts = [("Base", 8)] + common + self.bonus_parts("spell-save-dc")
            attack_parts = common + self.bonus_parts("spell-attacks")
            out.append({
                "class": df.get("name"),
                "ability": key.title(),
                "save_dc": sum(v for _, v in dc_parts),
                "attack": _signed(sum(v for _, v in attack_parts)),
                "dc_parts": dc_parts,
                "attack_parts": attack_parts,
            })
        return out

    def _caster(self, s: dict, source: str) -> dict | None:
        """The spellcasting numbers a spell uses: its class's, or (for species, feat
        and item spells) the ability D&D Beyond names, or the first caster's."""
        casters = {c["class"]: c for c in self.spellcasting()}
        if source in casters:
            return casters[source]
        ability_id = s.get("spellCastingAbilityId")
        if ability_id:
            mod = self.mods[ABILITY_KEY.get(ability_id, "wisdom")]
            return {"save_dc": 8 + self.pb + mod, "attack": _signed(self.pb + mod)}
        return next(iter(casters.values()), None)

    def _cantrip_dice(self, dice: str, name: str) -> str:
        """Cantrip damage grows at character levels 5, 11 and 17 (not Eldritch Blast: it adds beams)."""
        m = re.fullmatch(r"(\d+)d(\d+)(.*)", dice or "")
        if not m or name == "Eldritch Blast":
            return dice
        tier = 1 + (self.level >= 5) + (self.level >= 11) + (self.level >= 17)
        return f"{int(m.group(1)) * tier}d{m.group(2)}{m.group(3)}"

    def spell(self, s: dict, source: str) -> dict | None:
        df = s.get("definition") or {}
        if not df.get("name"):
            return None
        caster = self._caster(s, source)
        dmg = next((m for m in df.get("modifiers") or [] if m.get("type") == "damage" and _d(m, "die", "diceString")), None)
        heal = next((m for m in df.get("modifiers") or [] if m.get("type") == "bonus" and m.get("subType") == "hit-points"
                     and _d(m, "die", "diceString")), None)
        damage = ""
        if dmg:
            dice = _d(dmg, "die", "diceString")
            if not df.get("level") and df.get("scaleType") == "characterlevel":
                dice = self._cantrip_dice(dice, df["name"])
            damage = f"{dice} {(dmg.get('friendlySubtypeName') or dmg.get('subType') or '').lower()}".strip()
        save = ABILITY_KEY.get(df.get("saveDcAbilityId"))
        rng = df.get("range") or {}
        origin, value = rng.get("origin") or "", rng.get("rangeValue")
        range_label = f"{value} ft" if origin == "Ranged" and value else origin
        if rng.get("aoeType") and rng.get("aoeValue"):
            range_label = f"{range_label} ({rng['aoeValue']}-ft {rng['aoeType'].lower()})".strip()
        act = df.get("activation") or {}
        kind, amount = act.get("activationType"), act.get("activationTime") or 1
        if kind in (6, 7):
            unit = "minute" if kind == 6 else "hour"
            casting = f"{amount} {unit}{'s' if amount != 1 else ''}"
        else:
            casting = ACTIVATION.get(kind, "")
        dur = df.get("duration") or {}
        dtype, n, unit = dur.get("durationType") or "", dur.get("durationInterval") or 0, (dur.get("durationUnit") or "").lower()
        span = f"{n} {unit}{'s' if n != 1 else ''}" if n and unit else ""
        duration = (f"Concentration, up to {span}" if span else "Concentration") if dtype == "Concentration" else (span or dtype)
        comps = [COMPONENTS[c] for c in df.get("components") or [] if c in COMPONENTS]
        ids = _source_ids(df)
        return {
            "key": f"spell:{df['name']}",
            "core": not ids or bool(set(ids) & CORE_SOURCES),
            "book": ", ".join(SOURCE_NAMES.get(i, "another book") for i in ids),
            "name": df["name"],
            "level": df.get("level") or 0,
            "school": df.get("school") or "",
            "attack": caster["attack"] if caster and df.get("requiresAttackRoll") else "",
            "save": f"{save[:3].title()} {caster['save_dc']}" if caster and save and df.get("requiresSavingThrow") else "",
            "damage": damage,
            "healing": (_d(heal, "die", "diceString") or "") if heal else "",
            "tags": list(df.get("tags") or []),
            "trigger": (df.get("castingTimeDescription") or "").strip(),
            "sources": [source],
            "prepared": bool(s.get("prepared")),
            "always_prepared": bool(s.get("alwaysPrepared")),
            "uses_slot": s.get("usesSpellSlot") is not False,
            "uses": self.limited_use(s.get("limitedUse")),
            "concentration": bool(df.get("concentration")),
            "ritual": bool(df.get("ritual")),
            "components": comps,
            "material": (df.get("componentsDescription") or "").strip(),
            "range": range_label,
            "casting_time": casting,
            "duration": duration,
            "summary": _first_paragraph(html_to_text(df.get("description")), 400),
            "text": html_to_text(df.get("description")),
        }

    def spells(self) -> list[dict]:
        out: dict[str, dict] = {}
        classes = {c.get("id"): c for c in self.classes}
        lists = []
        for cs in self.d.get("classSpells") or []:
            c = classes.get(cs.get("characterClassId")) or {}
            spells = cs.get("spells") or []
            if _d(c, "definition", "spellPrepareType") == 1:  # e.g. a wizard's spellbook: only what's prepared
                spells = [s for s in spells if s.get("prepared") or s.get("alwaysPrepared") or not _d(s, "definition", "level")]
            lists.append((_d(c, "definition", "name", default="Class"), spells))
        by_class_id = {}
        for c in self.classes:
            for key in ("definition", "subclassDefinition"):
                if _d(c, key, "id"):
                    by_class_id[str(_d(c, key, "id"))] = _d(c, "definition", "name")
        for class_id, spells in (_d(self.d, "askdnd", "alwaysPreparedSpells", default={}) or {}).items():
            lists.append((by_class_id.get(class_id, "Class"), [{**s, "alwaysPrepared": True} for s in spells or []]))
        labels = {"race": _d(self.d, "race", "fullName", default="Species"), "class": "Class feature", "item": "Item", "feat": "Feat", "background": "Background"}
        for k, v in (self.d.get("spells") or {}).items():
            if k == "item":  # an item's spells only while it's equipped (and attuned if it needs it)
                v = [s for s in v or [] if s.get("componentId") in self.active_item_defs]
            lists.append((labels.get(k, k.title()), v or []))
        for source, spells in lists:
            for s in spells:
                sp = self.spell(s, source)
                if not sp:
                    continue
                key = sp["name"]
                if key in out:  # the same spell from two places, or once free (1/day) and once with a slot
                    prev = out[key]
                    if source not in prev["sources"]:
                        prev["sources"].append(source)
                    prev["uses"] = prev["uses"] or sp["uses"]
                    prev["uses_slot"] = prev["uses_slot"] or sp["uses_slot"]
                    prev["prepared"] |= sp["prepared"]
                    prev["always_prepared"] |= sp["always_prepared"]
                else:
                    out[key] = sp
        return sorted(out.values(), key=lambda s: (s["level"], s["name"]))

    def spellbook(self) -> list[dict]:
        """For the spell planner: per spellcasting class, every spell it could have,
        each with a state — "always" (always prepared), "prepared", "known"
        (a cantrip you have), "spellbook" (a wizard's, not prepared today) or
        "available" (on the class list, not on your sheet) — plus the counts."""
        casters = {c["class"]: c for c in self.spellcasting()}
        extra_always = _d(self.d, "askdnd", "alwaysPreparedSpells", default={}) or {}
        extra_available = _d(self.d, "askdnd", "availableSpells", default={}) or {}
        sheet_lists = {cs.get("characterClassId"): cs.get("spells") or [] for cs in self.d.get("classSpells") or []}
        out = []
        for c in self.classes:
            df = c.get("definition") or {}
            name, lvl = df.get("name"), c.get("level") or 0
            if name not in casters:
                continue
            rules = df.get("spellRules") or {}

            def at_level(key):
                row = rules.get(key) or []
                return row[lvl] if lvl < len(row) and row[lvl] else None

            book = df.get("spellPrepareType") == 1 and df.get("spellCastingLearningStyle") == 2
            # Classes that don't prepare from a list (D&D Beyond: spellPrepareType unset) simply
            # know the spells on their sheet, so those count as prepared.
            knows = df.get("spellPrepareType") != 1
            entries: dict[str, dict] = {}

            def put(raw, state):
                sp = self.spell(raw, name)
                if not sp:
                    return
                old = entries.get(sp["name"])
                rank = {"always": 4, "prepared": 3, "known": 3, "spellbook": 2, "available": 1}
                if old is None or rank[state] > rank[old["state"]]:
                    entries[sp["name"]] = {**sp, "state": state}

            for s in sheet_lists.get(c.get("id"), []):
                level = _d(s, "definition", "level") or 0
                state = ("always" if s.get("alwaysPrepared") else "known" if not level
                         else "prepared" if s.get("prepared") or knows else "spellbook" if book else "available")
                put(s, state)
            for key in ("definition", "subclassDefinition"):
                for s in extra_always.get(str(_d(c, key, "id")), []):
                    put(s, "always")
            own_features = {_d(f, "definition", "id") for f in c.get("classFeatures") or []}
            for s in _d(self.d, "spells", "class", default=[]) or []:  # e.g. Oath Spells, granted by a feature
                if s.get("alwaysPrepared") and s.get("componentId") in own_features:
                    put(s, "always")
            for s in extra_available.get(str(df.get("id")), []):
                ids = _source_ids(s.get("definition") or {})
                if not ids or set(ids) & CORE_SOURCES:  # only offer 2024 core-rulebook spells to prepare
                    put(s, "available")
            spells = sorted(entries.values(), key=lambda x: (x["level"], x["name"]))
            out.append({
                "class": name,
                **casters[name],
                "spellbook": book,
                "prepared_count": sum(1 for x in spells if x["state"] == "prepared"),
                "prepared_max": at_level("levelPreparedSpellMaxes") or at_level("levelSpellKnownMaxes"),
                "cantrips_count": sum(1 for x in spells if x["state"] == "known" and not x["level"]),
                "cantrips_max": at_level("levelCantripsKnownMaxes"),
                "spells": spells,
            })
        return out

    def inventory(self) -> list[dict]:
        names = {str(v.get("valueId")): v.get("value") for v in self.d.get("characterValues") or [] if v.get("typeId") == 8}
        other_changes = {str(v.get("valueId")) for v in self.d.get("characterValues") or [] if v.get("typeId") not in (8, ITEM_NOTE_VALUE_TYPE)}
        noted = {x if ":" in x else f"item:{x}" for x in self.d.get("noteItemIds") or []}  # older copies kept bare ids
        containers = {i.get("id"): i for i in self.items}
        out = []
        for i in self.items:
            df = i.get("definition") or {}
            if not df.get("name"):
                continue
            container = containers.get(i.get("containerEntityId"))
            dmg = _d(df, "damage", "diceString")
            charges = self.limited_use(i.get("limitedUse"))
            kind = df.get("subType") or df.get("filterType") or df.get("type") or ""
            active = i.get("equipped") and (i.get("isAttuned") or not df.get("canAttune"))
            usable = kind in ("Potion", "Scroll") or bool(charges and (active or charges["reset"] == "Used up") and charges["reset"] != "Other")
            item_id = str(i.get("id"))
            renamed = names.get(item_id) if names.get(item_id) and names.get(item_id) != df["name"] else ""
            changes = ([f"Renamed (the D&D Beyond item is {df['name']})"] if renamed else []) + (
                ["Has a note from the player (below)"] if f"item:{item_id}" in noted else []) + (
                ["Other details changed on D&D Beyond (such as cost or weight)"] if item_id in other_changes else [])
            out.append({
                "key": f"item:{i.get('id')}",
                "name": renamed or df["name"],
                "base_name": df["name"],
                "custom": False,
                "changes": changes,
                "battle": bool(usable and df.get("filterType") != "Weapon"),
                "category": df.get("filterType") or "Other Gear",
                "type": df.get("subType") or df.get("filterType") or df.get("type") or "",
                "quantity": i.get("quantity") or 1,
                "equipped": bool(i.get("equipped")),
                "magic": bool(df.get("magic")),
                "rarity": df.get("rarity") or "",
                "attunement": "attuned" if i.get("isAttuned") else ("required" if df.get("canAttune") else ""),
                "attunement_note": df.get("attunementDescription") or "",
                "charges": charges,
                "in": _d(container, "definition", "name") if container else "",
                "damage": f"{dmg} {df.get('damageType') or ''}".strip() if dmg else "",
                "properties": [p.get("name") for p in df.get("properties") or [] if p.get("name")],
                "armor_class": df.get("armorClass"),
                "summary": _first_paragraph(html_to_text(df.get("description")), 280) if df.get("magic") else "",
                "text": html_to_text(df.get("description")) if df.get("magic") or usable else "",
            })
        for c in self.d.get("customItems") or []:  # made up on D&D Beyond (by a player or the DM), not from a book
            if not c.get("name"):
                continue
            text = html_to_text(c.get("description"))
            out.append({
                "key": f"custom:{c.get('id')}", "name": c["name"].strip(), "base_name": c["name"].strip(), "custom": True,
                "changes": ["Has a note from the player (below)"] if f"custom:{c.get('id')}" in noted else [], "battle": False, "category": "Other Gear", "type": "Custom item", "quantity": c.get("quantity") or 1,
                "equipped": False, "magic": False, "rarity": "", "attunement": "", "attunement_note": "", "charges": None,
                "in": "", "damage": "", "properties": [], "armor_class": None,
                "summary": _first_paragraph(text, 280), "text": text,
            })
        out.sort(key=lambda x: (not x["equipped"], not x["magic"], bool(x["in"]), x["name"]))
        return out

    # attacks ----------------------------------------------------------

    def monk_level(self) -> int:
        return sum(c.get("level") or 0 for c in self.classes if _d(c, "definition", "name") == "Monk")

    def martial_arts_die(self) -> int:
        lvl = self.monk_level()
        return 0 if not lvl else 6 if lvl < 5 else 8 if lvl < 11 else 10 if lvl < 17 else 12

    def weapon_proficient(self, df: dict) -> bool:
        weapons = set(self.proficiencies()["weapons"])
        category = {1: "Simple Weapons", 2: "Martial Weapons"}.get(df.get("categoryId"))
        names = {m.get("friendlySubtypeName") for m in self.mods_of(("proficiency", "monk-weapon"))}
        return bool(category in names or df.get("type") in names or df.get("name") in names or df.get("type") in weapons)

    def attacks(self) -> list[dict]:
        """Equipped weapons and the Unarmed Strike, with to-hit and damage as D&D Beyond shows them."""
        out = []
        str_mod, dex_mod = self.mods["strength"], self.mods["dexterity"]
        die = self.martial_arts_die()
        for i in self.items:
            df = i.get("definition") or {}
            if df.get("filterType") != "Weapon" or not i.get("equipped"):
                continue
            props = {p.get("name") for p in df.get("properties") or []}
            ranged = df.get("attackType") == 2
            monk_weapon = bool(die) and not ranged and (df.get("categoryId") == 1 or "Light" in props)
            mod = dex_mod if ranged else max(str_mod, dex_mod) if ("Finesse" in props or monk_weapon) else str_mod
            magic = sum(int(m.get("value") or 0) for m in self.mods_of("bonus", "magic") if m.get("componentId") == df.get("id"))
            magic += sum(int(g.get("value") or 0) for g in df.get("grantedModifiers") or [] if g.get("subType") == "magic"
                         and not any(m.get("componentId") == df.get("id") for m in self.mods_of("bonus", "magic")))
            dice = _d(df, "damage", "diceString") or ""
            m = re.fullmatch(r"(\d+)d(\d+)", dice)
            if monk_weapon and m and int(m.group(1)) == 1 and int(m.group(2)) < die:
                dice = f"1d{die}"
            dmg_bonus = mod + magic
            rng = f"{df.get('range')} ({df.get('longRange')}) ft" if df.get("longRange") and df.get("longRange") != df.get("range") else (
                "5 ft" if not ranged else f"{df.get('range')} ft")
            out.append({
                "key": f"attack:{i.get('id')}",
                "name": df.get("name"),
                "to_hit": _signed(mod + magic + (self.pb if self.weapon_proficient(df) else 0)),
                "damage": f"{dice}{'+' if dmg_bonus >= 0 else '−'}{abs(dmg_bonus)} {(df.get('damageType') or '').lower()}".strip() if dice else "",
                "range": rng,
                "properties": sorted(props),
                "martial_arts": monk_weapon,
            })
        natural = sum(int(m.get("value") or 0) for m in self.mods_of("bonus", "natural-attacks"))
        mod = max(str_mod, dex_mod) if die else str_mod
        base = f"1d{die}{'+' if mod + natural >= 0 else '−'}{abs(mod + natural)}" if die else str(max(0, 1 + mod + natural))
        out.append({"key": "attack:unarmed", "name": "Unarmed Strike", "to_hit": _signed(mod + self.pb + natural),
                    "damage": f"{base} bludgeoning", "range": "5 ft", "properties": [], "martial_arts": bool(die)})
        return out

    # situational ------------------------------------------------------

    def _component_names(self) -> dict:
        names = {}
        for c in self.classes:
            for f in c.get("classFeatures") or []:
                names[_d(f, "definition", "id")] = _d(f, "definition", "name")
        for t in _d(self.d, "race", "racialTraits", default=[]):
            names[_d(t, "definition", "id")] = _d(t, "definition", "name")
        for f in self.d.get("feats") or []:
            names[_d(f, "definition", "id")] = _d(f, "definition", "name")
        for i in self.items:
            names[_d(i, "definition", "id")] = _d(i, "definition", "name")
        for group in (self.d.get("options") or {}).values():
            for o in group or []:
                names[o.get("componentId")] = names.get(o.get("componentId")) or _d(o, "definition", "name")
        return names

    def situational(self, spells: list[dict], actions: list[dict]) -> list[dict]:
        """Rules that only matter in some situations: conditional advantages,
        resistances and immunities, item bonuses already in the numbers, and the
        reactions that protect you. The things the Defenses box doesn't show."""
        names = self._component_names()
        out, seen = [], set()

        def add(kind, text, source, key=None):
            key = key or f"situ:{kind}:{text}"
            if key not in seen:
                seen.add(key)
                out.append({"key": key, "kind": kind, "text": text, "source": source or ""})

        def what(m):
            text = (m.get("friendlySubtypeName") or m.get("subType") or "").replace("-", " ").lower()
            return re.sub(r"\b(strength|dexterity|constitution|intelligence|wisdom|charisma)\b", lambda x: x.group(1).title(), text)

        def condition(word, m):
            target, restriction = what(m), (m.get("restriction") or "").strip().rstrip(".")
            head, _, rest = target.partition(" ")
            if rest and restriction.lower().startswith(rest):  # "Constitution saving throws" + "saving throws that you make…"
                return f"{word} on {head} {restriction}"
            return f"{word} on {target}" + (f" {restriction}" if restriction else "")

        for m in self.mods_of("advantage"):
            add("advantage", condition("Advantage", m), names.get(m.get("componentId")))
        for m in self.mods_of("disadvantage"):
            add("disadvantage", condition("Disadvantage", m), names.get(m.get("componentId")))
        for kind, word in (("immunity", "Immune to"), ("resistance", "Resistant to"), ("vulnerability", "Vulnerable to")):
            for m in self.mods_of(kind):
                target = what(m).lower()
                damage = m.get("entityTypeId") == 349597128 or target in DAMAGE_TYPES
                add(kind, f"{word} {target}{' damage' if damage else ''}", names.get(m.get("componentId")))
        for sub, label in (("saving-throws", "saving throws"), ("ability-checks", "ability checks"), ("armor-class", "AC"),
                           ("initiative", "initiative")):
            for m in self.mods_of("bonus", sub):
                n = self.bonus_value(m)
                if n and not m.get("restriction"):
                    add("bonus", f"{_signed(n)} to {label} (already in the numbers)", names.get(m.get("componentId")))
        for a in actions:
            if a["activation"] == "Reaction":
                add("reaction", f"Reaction: {a['name']}", "", key=a["key"])
        for sp in spells:
            if sp["casting_time"] == "Reaction":
                when = sp["trigger"] or ""
                add("reaction", f"Reaction spell: {sp['name']}" + (f", {when}" if when else ""), ", ".join(sp["sources"]), key=sp["key"])
        return out

    # What a druid might keep in Wild Shape, if the DM allows it (app/wild_shape.py):
    # worn magic items that change numbers a form uses, and class features that do.
    FORM_ITEM_EFFECTS = {
        ("bonus", "saving-throws"): "saves", ("bonus", "ability-checks"): "checks", ("bonus", "initiative"): "initiative",
        ("bonus", "armor-class"): "ac", ("bonus", "natural-attacks"): "attack", ("damage", "natural-attacks"): "damage",
        ("bonus", "speed"): "speed", ("bonus", "speed-walking"): "speed",
        # A form's Str/Dex/Con replace yours, so a learned book or a belt only counts if kept
        ("bonus", "strength-score"): "str_score", ("bonus", "dexterity-score"): "dex_score",
        ("bonus", "constitution-score"): "con_score",
    }

    def form_options(self) -> dict:
        by_def = {}
        for i in self.items:
            df = i.get("definition") or {}
            if df.get("id") and i.get("equipped") and (i.get("isAttuned") or not df.get("canAttune")):
                by_def[df["id"]] = i
        items: dict[str, dict] = {}
        for m in (self.d.get("modifiers") or {}).get("item") or []:
            what = self.FORM_ITEM_EFFECTS.get((m.get("type"), m.get("subType")))
            i = by_def.get(m.get("componentId"))
            value = m.get("fixedValue") if m.get("fixedValue") is not None else m.get("value")
            if not what or i is None or not isinstance(value, int) or (m.get("restriction") or "").strip():
                continue
            entry = items.setdefault(f"item:{i.get('id')}", {"key": f"item:{i.get('id')}", "name": i["definition"]["name"], "effects": {}})
            entry["effects"][what] = entry["effects"].get(what, 0) + value
        features = []
        class_mods = (self.d.get("modifiers") or {}).get("class") or []
        ud = next((m for m in class_mods if m.get("type") == "set" and m.get("subType") == "unarmored-armor-class"), None)
        if ud:
            ability = ABILITY_KEY.get(ud.get("statId"), "wisdom")[:3]
            features.append({"key": "unarmored-defense", "name": "Unarmored Defense", "ability": ability,
                             "text": f"AC = 10 + the form's Dexterity + {'your' if ability in ('int', 'wis', 'cha') else 'the form' + chr(39) + 's'} "
                                     f"{ {'wis': 'Wisdom', 'con': 'Constitution', 'cha': 'Charisma'}.get(ability, ability.title())} modifier"})
        moves = [m.get("value") or 0 for m in class_mods if m.get("subType") == "unarmored-movement"]
        if moves and max(moves):
            features.append({"key": "unarmored-movement", "name": "Unarmored Movement", "bonus": max(moves),
                             "text": f"+{max(moves)} ft to the form's speeds"})
        return {"items": list(items.values()), "features": features}

    def creatures(self) -> list[dict]:
        out = []
        for c in self.d.get("creatures") or []:
            df = c.get("definition") or {}
            if not df.get("name"):
                continue
            cr = df.get("challengeRatingId")
            moves = ", ".join(
                f"{'walk' if m.get('movementId') == 1 else {2: 'burrow', 3: 'climb', 4: 'fly', 5: 'swim'}.get(m.get('movementId'), '')} {m.get('speed')} ft".strip()
                for m in df.get("movements") or [] if m.get("speed")
            )
            out.append({
                "key": f"form:{df['name']}",
                "name": c.get("name") or df["name"],
                "kind": df["name"],
                "group": CREATURE_GROUPS.get(c.get("groupId"), "Creature"),
                "cr": CR.get(cr, str(cr - 4) if isinstance(cr, int) and cr > 4 else ""),
                "armor_class": df.get("armorClass"),
                "hit_points": df.get("averageHitPoints"),
                "speed": moves,
                "block": _creature_block(df),
            })
        return out


MOVES = {1: "walk", 2: "burrow", 3: "climb", 4: "fly", 5: "swim"}
SENSE_NAMES = {1: "Blindsight", 2: "Darkvision", 3: "Tremorsense", 4: "Truesight"}


def _stat_entries(html: str | None) -> list[dict]:
    """"Rend. Melee Attack Roll: +7…" paragraphs as [{"name": "Rend", "text": "Melee Attack Roll…"}]."""
    out = []
    for para in (p.strip() for p in html_to_text(html).split("\n") if p.strip()):
        m = re.match(r"([^.]{1,60}?(?:\([^)]*\))?)\.\s+(.*)", para, re.S)
        if m:
            out.append({"name": m.group(1).strip(), "text": m.group(2).strip()})
        elif out:
            out[-1]["text"] += "\n" + para
    return out


def _creature_block(df: dict) -> dict:
    """A Wild Shape form's stat block from D&D Beyond, in the same shape as
    app/data/beasts_2024.json (used when the form isn't in that list)."""
    cr = df.get("challengeRatingId")
    label = CR.get(cr, str(cr - 4) if isinstance(cr, int) and cr > 4 else "")
    value = {"0": 0.0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5}.get(label)
    abilities = {ABILITY_KEY[x["statId"]][:3]: x.get("value") or 10 for x in df.get("stats") or [] if x.get("statId") in ABILITY_KEY}
    return {
        "name": df.get("name", ""),
        "cr": value if value is not None else float(label or 0),
        "cr_label": label,
        "size": {2: "Tiny", 3: "Small", 4: "Medium", 5: "Large", 6: "Huge", 7: "Gargantuan"}.get(df.get("sizeId"), ""),
        "ac": df.get("armorClass"),
        "ac_note": df.get("armorClassDescription") or "",
        "hp": df.get("averageHitPoints"),
        "hit_dice": (df.get("hitPointDice") or {}).get("diceString", ""),
        "speed": {MOVES[m["movementId"]]: m["speed"] for m in df.get("movements") or [] if m.get("movementId") in MOVES and m.get("speed")},
        "abilities": abilities,
        "saves": {},
        "skills": {},
        "senses": ", ".join(f"{SENSE_NAMES[x['senseId']]} {x.get('notes') or ''}".strip() for x in df.get("senses") or [] if x.get("senseId") in SENSE_NAMES),
        "passive_perception": df.get("passivePerception"),
        "traits": _stat_entries(df.get("specialTraitsDescription")),
        "actions": _stat_entries(df.get("actionsDescription")),
        "bonus_actions": _stat_entries(df.get("bonusActionsDescription")),
        "reactions": _stat_entries(df.get("reactionsDescription")),
        "source": "D&D Beyond",
    }


def parse_character(data: dict) -> dict:
    """A readable summary of a D&D Beyond character (the `data` object).

    This is the shape stored in character_snapshots.summary and passed to the
    templates (and, later, to Claude for briefings). Raises DdbError if the
    data is unusable.
    """
    if not isinstance(data, dict) or not data.get("name"):
        raise DdbError("D&D Beyond's character data didn't have a name; the format may have changed.")
    try:
        sh = _Sheet(data)
        perception = next(s for s in sh.skills() if s["name"] == "Perception")
        actions = sh.actions()
        spells = sh.spells()
        items = sh.inventory()
        slots = sh.spell_slots()
        general_save_notes = [
            "Advantage on saving throws " + (m.get("restriction") or "").strip().rstrip(".")
            for m in sh.mods_of("advantage", "saving-throws")
        ]
        summary = {
            "parser_version": PARSER_VERSION,
            "ddb_id": str(data.get("id") or ""),
            "sheet_url": SHEET_URL.format(id=data.get("id")) if data.get("id") else "",
            "name": data["name"].strip(),
            "portrait": _portrait(data),
            "story": _story(data),
            "species": _d(data, "race", "fullName", default=""),
            "background": _d(data, "background", "definition", "name", default=""),
            "classes": [
                {"name": _d(c, "definition", "name"), "level": c.get("level") or 0, "subclass": _d(c, "subclassDefinition", "name", default="")}
                for c in sorted(sh.classes, key=lambda c: (not c.get("isStartingClass"), -(c.get("level") or 0)))
            ],
            "level": sh.level,
            "proficiency_bonus": sh.pb,
            "abilities": [
                {"key": key, "name": name, "short": short, "score": sh.scores[key], "modifier": sh.mods[key], "label": _signed(sh.mods[key])}
                for _, key, name, short in ABILITIES
            ],
            "hit_points": sh.hit_points(),
            "armor_class": sh.armor_class(),
            "armor_parts": sh.armor_class_parts(),
            "initiative_parts": sh.initiative_parts(),
            "initiative": _signed(sh.initiative()),
            "speed": sh.speeds(),
            "passive_perception": 10 + perception["bonus"],
            "inspiration": bool(data.get("inspiration")),
            "saves": sh.saves(),
            "save_notes": general_save_notes,
            "attacks": sh.attacks(),
            "situational": sh.situational(spells, actions),
            "skills": sh.skills(),
            "proficiencies": sh.proficiencies(),
            "spellcasting": sh.spellcasting(),
            "spell_slots": slots,
            "spells": spells,
            "spellbook": sh.spellbook(),
            "actions": actions,
            "features": sh.features(),
            "inventory": items,
            "attuned": [i["name"] for i in items if i["attunement"] == "attuned"],
            "currency": {k: v for k, v in (data.get("currencies") or {}).items() if v},
            "creatures": sh.creatures(),
            "form_options": sh.form_options(),
        }
    except DdbError:
        raise
    except Exception as e:  # an unexpected shape: keep the last good copy
        raise DdbError(f"Couldn't read D&D Beyond's character data (the format may have changed): {type(e).__name__}.") from e
    summary["resources"] = key_resources(summary)
    return summary


def key_resources(summary: dict) -> list[dict]:
    """Limited-use things worth showing on a character card: class and feat
    resources first, then spell slots."""
    out = []
    for a in summary["actions"]:
        if a["uses"] and a["source"] in ("class", "feat", "race") and not any(r["name"] == a["name"] for r in out):
            out.append({"name": a["name"], "max": a["uses"]["max"], "left": a["uses"]["left"], "reset": a["uses"]["reset"]})
    slots = summary["spell_slots"].get("slots") or []
    if slots:
        out.append({"name": "Spell slots", "text": " · ".join(f"{s['level']}: {s['max']}" for s in slots)})
    pact = summary["spell_slots"].get("pact")
    if pact:
        out.append({"name": "Pact slots", "text": f"{pact['max']} × level {pact['level']}"})
    return out
