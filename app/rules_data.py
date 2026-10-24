"""Rules content as data (VTT 0.6): monsters, spells, magic items and the Rules Glossary (conditions among it).

Two layers, read as one:

1. The System Reference Document 5.2.1 in app/data/srd/ (public, CC-BY-4.0; ATTRIBUTION below goes wherever
   it's shown). Built from the official PDF by scripts/srd_import.py, never edited by hand.
2. A campaign's own: the DM's creations, or entries copied from a book the DM owns, in the database
   (models.CampaignContent), never in the public repo. One with the same key as an SRD entry replaces it
   for that campaign.

`catalog(kind, db, campaign_id)` and `find(kind, name, db, campaign_id)` give the merged view; without a
campaign it's the SRD alone. Every entry is validated against its kind's schema when it's loaded (the SRD
files once, on first use) and when it's saved (`save`), so a bad file or row fails loudly, not on a page.
The shapes are in docs/rules/README.md ("Rules content as data"). Entries are plain dicts shared between
callers: read them, don't change them.
"""

import json
import logging
import re
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError, model_validator

log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data" / "srd"
PICTURES = Path(__file__).parent / "data" / "monster_pictures.json"
SOURCE = "SRD 5.2.1"
ATTRIBUTION = (
    "This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast "
    "LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons "
    "Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode."
)

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
CREATURE_TYPES = ("Aberration", "Beast", "Celestial", "Construct", "Dragon", "Elemental", "Fey", "Fiend", "Giant",
                  "Humanoid", "Monstrosity", "Ooze", "Plant", "Undead")
DAMAGE_TYPES = ("Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
                "Psychic", "Radiant", "Slashing", "Thunder")
SCHOOLS = ("Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy", "Transmutation")
CASTERS = ("Bard", "Cleric", "Druid", "Paladin", "Ranger", "Sorcerer", "Warlock", "Wizard")
ITEM_CATEGORIES = ("Armor", "Potion", "Ring", "Rod", "Scroll", "Staff", "Wand", "Weapon", "Wondrous Item")
GLOSSARY_TAGS = ("", "Action", "Area of Effect", "Attitude", "Condition", "Hazard")
CR_LABELS = {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}

Key = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=120)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Ability = Literal["str", "dex", "con", "int", "wis", "cha"]
Move = Literal["walk", "burrow", "climb", "fly", "swim"]
Sense = Literal["blindsight", "darkvision", "tremorsense", "truesight"]


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Entry(_Shape):
    """A named part of a stat block: a trait, an action ("Bite": "Melee Attack Roll: +4, reach 5 ft. Hit: …").
    A limit on its use is part of the name, as printed: "Fire Breath (Recharge 5–6)", "Dominate Mind (2/Day)"."""

    name: Name
    text: str


class Monster(_Shape):
    key: Key
    name: Name
    size: str  # "Medium", or "Medium or Small" (the creature's choice)
    type: Literal[CREATURE_TYPES]
    tags: list[str] = []  # "Dragon (Chromatic)" -> ["Chromatic"]
    swarm_of: Literal["", *SIZES] = ""  # "Large Swarm of Tiny Beasts": size Large, type Beast, swarm_of Tiny
    alignment: str
    ac: int = Field(ge=0)
    initiative: int
    hp: int = Field(ge=0)
    hit_dice: str  # "2d8 + 2", as printed
    speed: dict[Move, int]  # {"walk": 30, "fly": 60}
    hover: bool = False
    speed_note: str = ""  # what holds only sometimes: "40 ft. (bear form only)"
    abilities: dict[Ability, int]
    saves: dict[Ability, int]  # every saving throw bonus, as the stat block's SAVE column prints them
    skills: dict[str, int] = {}  # {"Perception": 5}
    resistances: list[str] = []  # damage types; a few say more ("Charmed (with Mind Blank)")
    vulnerabilities: list[str] = []
    immunities: list[str] = []
    condition_immunities: list[str] = []
    gear: list[str] = []
    senses: dict[Sense, int] = {}  # {"darkvision": 60}
    senses_note: str = ""  # "unimpeded by magical Darkness"
    passive_perception: int
    languages: str
    cr: float
    cr_label: str  # "1/4"
    xp: int
    xp_lair: int | None = None
    pb: int
    traits: list[Entry] = []
    actions: list[Entry] = []
    bonus_actions: list[Entry] = []
    reactions: list[Entry] = []
    legendary_actions: list[Entry] = []
    legendary_uses: str = ""  # "Legendary Action Uses: 3 (4 in Lair). Immediately after…"
    section: str = ""  # where the SRD prints it: "Monsters", "Animals", "Magic Items"
    group: str = ""  # its heading there, when not its own name: "Red Dragons", "Figurine of Wondrous Power"
    source: str

    @model_validator(mode="after")
    def _check(self):
        if set(self.abilities) != set(ABILITIES) or set(self.saves) != set(ABILITIES):
            raise ValueError("abilities and saves need all six")
        if not re.fullmatch(rf"({'|'.join(SIZES)})( or ({'|'.join(SIZES)}))*", self.size):
            raise ValueError(f"size {self.size!r}")
        if self.cr_label != cr_label(self.cr):
            raise ValueError(f"cr_label {self.cr_label!r} for CR {self.cr}")
        return self


class SummonedCreature(_Shape):
    """A creature a spell or item makes, whose numbers come from its maker ("HP 10 (Medium or smaller), 20
    (Large)…", "PB equals your Proficiency Bonus"): its header fields stay as printed."""

    name: Name
    size: str
    type: str
    alignment: str
    fields: dict[str, str]  # {"AC": "15", "HP": "…", "Speed": "30 ft.", "Senses": "…", "CR": "None (XP 0; …)"}
    abilities: dict[Ability, int]
    saves: dict[Ability, int]
    traits: list[Entry] = []
    actions: list[Entry] = []
    bonus_actions: list[Entry] = []
    reactions: list[Entry] = []


class Spell(_Shape):
    key: Key
    name: Name
    level: int = Field(ge=0, le=9)  # 0 = cantrip
    school: Literal[SCHOOLS]
    classes: list[Literal[CASTERS]] = []
    casting_time: str  # "Action", "Bonus Action", "Reaction, which you take when…", "1 minute"
    ritual: bool = False
    range: str  # "60 feet", "Self (15-foot Cone)", "Touch"
    components: list[Literal["V", "S", "M"]]
    material: str = ""  # "a bell and silver wire"
    duration: str  # "Concentration, up to 1 minute"
    concentration: bool = False
    text: str
    higher_levels: str = ""  # "Using a Higher-Level Spell Slot."
    cantrip_upgrade: str = ""
    creatures: list[SummonedCreature] = []
    source: str

    @model_validator(mode="after")
    def _check(self):
        if ("M" in self.components) != bool(self.material):
            raise ValueError("a Material component needs its material, and only then")
        if self.concentration != self.duration.startswith("Concentration"):
            raise ValueError("concentration doesn't match the duration")
        return self


class MagicItem(_Shape):
    key: Key
    name: Name
    category: Literal[ITEM_CATEGORIES]
    base: str = ""  # "Armor (Plate Armor)" -> "Plate Armor"; "Weapon (Any Sword)" -> "Any Sword"
    rarity: str  # "Rare", or as printed: "Rare (+1), Very Rare (+2), or Legendary (+3)"
    attunement: bool = False
    attunement_by: str = ""  # "by a Wizard"
    text: str
    monsters: list[Key] = []  # monsters it makes that have their own stat block (keys)
    creatures: list[SummonedCreature] = []
    source: str


class GlossaryEntry(_Shape):
    key: Key
    name: Name
    tag: Literal[GLOSSARY_TAGS] = ""  # "Blinded [Condition]" -> "Condition"
    text: str
    source: str


# What a campaign can add (models.CampaignContent.kind), and every kind's schema and file
CAMPAIGN_KINDS = {"monster": Monster, "spell": Spell, "magic_item": MagicItem}
KINDS = {**CAMPAIGN_KINDS, "glossary": GlossaryEntry}
FILES = {"monster": "monsters", "spell": "spells", "magic_item": "magic_items", "glossary": "rules_glossary"}


def cr_label(cr: float) -> str:
    return CR_LABELS.get(cr, str(int(cr)))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "").replace("’", "")).strip("-")


# ------------------------------------------------------------------ the SRD


@cache
def srd(kind: str) -> tuple[dict, ...]:
    """Every SRD entry of a kind, validated, in the book's order."""
    name = FILES[kind]
    data = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    rows = data[name]
    TypeAdapter(list[KINDS[kind]]).validate_python(rows)
    keys = [r["key"] for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{name}.json has a key twice")
    if kind == "magic_item":
        known = {m["key"] for m in srd("monster")}
        missing = {k for r in rows for k in r["monsters"] if k not in known}
        if missing:
            raise ValueError(f"magic items name monsters that aren't there: {sorted(missing)}")
    return tuple(rows)


@cache
def _srd_by(kind: str) -> dict[str, dict]:
    """By key and by lowercased name."""
    out = {}
    for r in srd(kind):
        out[r["key"]] = r
        out.setdefault(r["name"].lower(), r)
    return out


def conditions() -> list[dict]:
    """The 15 conditions (Blinded … Unconscious): the Rules Glossary's [Condition] entries."""
    return [g for g in srd("glossary") if g["tag"] == "Condition"]


def condition_names() -> tuple[str, ...]:
    return tuple(c["name"] for c in conditions())


@cache
def pictures() -> dict[str, dict]:
    """Links to D&D Beyond's 2024 Monster Manual art for SRD monsters, by key (scripts/monster_pictures.py):
    {"image": …, "ddb_url": …, "ddb_id": …}. Links, never the pictures themselves."""
    return json.loads(PICTURES.read_text(encoding="utf-8"))["pictures"]


# ------------------------------------------------------------------ with a campaign's own


def _campaign_rows(db, kind: str, campaign_id: int | None) -> list[dict]:
    if db is None or campaign_id is None:
        return []
    from sqlalchemy import select

    from app.models import CampaignContent

    out = []
    for row in db.scalars(select(CampaignContent).where(CampaignContent.campaign_id == campaign_id, CampaignContent.kind == kind)):
        entry = row.entry()
        try:
            CAMPAIGN_KINDS[kind].model_validate(entry)
        except ValidationError as e:  # saved before a schema change: leave it out, don't break the page
            log.warning("campaign content %s (%s %s) doesn't fit its schema: %s", row.id, kind, row.key, e)
            continue
        out.append(entry)
    return out


def catalog(kind: str, db=None, campaign_id: int | None = None) -> list[dict]:
    """The SRD's entries of a kind plus the campaign's own (its own replacing an SRD entry with the same key),
    by name. Each says where it's from in "source" ("SRD 5.2.1", "Homebrew", a book's title)."""
    own = {r["key"]: r for r in _campaign_rows(db, kind, campaign_id)}
    rows = [own.pop(r["key"], r) for r in srd(kind)] + list(own.values())
    return sorted(rows, key=lambda r: r["name"].lower())


def find(kind: str, name_or_key: str, db=None, campaign_id: int | None = None) -> dict | None:
    """One entry by key or name (any case): the campaign's own first, then the SRD's."""
    want = name_or_key.strip().lower().replace("’", "'")
    for r in _campaign_rows(db, kind, campaign_id):
        if want in (r["key"], r["name"].lower()):
            return r
    return _srd_by(kind).get(want) or _srd_by(kind).get(slug(want))


def save(db, campaign_id: int, kind: str, entry: dict, source: str = "Homebrew", user_id: int | None = None):
    """Add or replace one of a campaign's own entries (validated first; raises ValueError if it doesn't fit).
    Its key is its name's slug unless it has one; an SRD key replaces that SRD entry for the campaign."""
    from sqlalchemy import select

    from app.models import CampaignContent

    if kind not in CAMPAIGN_KINDS:
        raise ValueError(f"a campaign can't add a {kind}")
    entry = {**entry, "key": entry.get("key") or slug(entry.get("name", "")), "source": source}
    try:
        CAMPAIGN_KINDS[kind].model_validate(entry)
    except ValidationError as e:
        raise ValueError(str(e)) from e
    row = db.scalar(select(CampaignContent).where(CampaignContent.campaign_id == campaign_id, CampaignContent.kind == kind,
                                                  CampaignContent.key == entry["key"]))
    if row is None:
        row = CampaignContent(campaign_id=campaign_id, kind=kind, key=entry["key"], created_by_id=user_id)
        db.add(row)
    row.name, row.source = entry["name"], source
    row.data = {k: v for k, v in entry.items() if k not in ("key", "name", "source")}
    db.flush()
    return row
