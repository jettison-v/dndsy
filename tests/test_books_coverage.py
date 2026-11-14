"""The books' coverage (the outside review's R2, Nov 10; Brett, Nov 12: "continue with the roll card coverage"): every
class feature, option, feat and species trait in the 2024 Player's Handbook whose words hold dice, a save or a bonus to a
roll is played by askdnd's data, said in words on purpose, the sheet's own number, or a known gap with what fills it.
tests/fixtures/book-index.json holds names, classes and levels only (scripts/books_coverage.py writes it from the offline
books, which this test never needs), and made-up characters of every class and subclass at levels 1, 5, 11 and 17 are
given what the data says they have."""

import json
import re
from pathlib import Path

import pytest

from app import rules_book
from scripts import books_coverage as bc
from tests.table_setup import plain_id

BOOK = json.loads((Path(__file__).parent / "fixtures" / "book-index.json").read_text())
INDEX = BOOK["entries"]
ROWS = [r for r in INDEX if r["kind"] != "item"]  # (a magic item's rolls are added as the table's characters carry it)

# What the data doesn't play yet, each with what fills it. A new gap fails; a filled one must come off the list.
KNOWN_GAPS = {
    "Tandem Footwork": "a bonus to Initiative alone (an add's `to` of initiative), and the ally's share of it",
    "Mantle of Inspiration": "an amount that's twice a die (a multiplier in a roll's dice)",
    "Undying Sentinel": "a feature that acts at 0 Hit Points, offered by the hit points window; three times a level",
    "Boon of Recovery": "a feature that acts at 0 Hit Points; a pool of d10s to spend",
    "Disciple of Life": "healing that adds the slot's level (a {slot} token in an add's amount)",
    "Blessed Healer": "healing for yourself that adds the slot's level, after healing someone else",
    "Supreme Healing": "healing dice at their maximum (an add's op of max)",
    "Survivor": "healing at the start of your turn while Bloodied (a turn-start reminder with its roll, fight.follow)",
    "Elder Champion": "healing at the start of your turn (a turn-start reminder with its roll)",
    "Dark One's Blessing": "Temporary Hit Points when an enemy drops to 0 (a moment the hit points window could offer)",
    "Celestial Resilience": "Temporary Hit Points after a rest, for you and five others (the Rest window)",
    "Inspiring Leader": "Temporary Hit Points after a rest from your character level (a character-level token; the Rest window)",
    "Improved Duplicity": "healing when the illusion ends (a moment askdnd doesn't see)",
    "Foe Slayer": "Hunter's Mark's die as a d10 at Ranger 20 (a scale for the spell's die)",
    "Healer": "Battle Medic heals with the patient's Hit Point Die (whose die askdnd would need to ask)",
}


def status(row: dict) -> str:
    return bc.where(row, bc.played_names())[0]


def test_every_entry_that_rolls_is_played_said_or_a_known_gap():
    known = bc.played_names()
    missing = {r["name"].replace("’", "'") for r in ROWS if bc.where(r, known)[0] in ("missing", "partly")}
    assert not missing - set(KNOWN_GAPS), f"new gaps: give each data in app/data/rules/, or a reason: {sorted(missing - set(KNOWN_GAPS))}"
    assert not set(KNOWN_GAPS) - missing, f"filled: take these off KNOWN_GAPS: {sorted(set(KNOWN_GAPS) - missing)}"


def test_every_subclass_of_the_data_is_in_the_book():
    """A data entry's `sub` is the book's subclass name (or one from an older book, named there), so a character of
    that subclass is given it."""
    book = {(c, s) for c, ss in BOOK["subclasses"].items() for s in ss}
    older = {e.get("sub") for e in rules_book.entries() if e.get("book")}
    assert {(e["class"], e["sub"]) for e in rules_book.entries() if e.get("sub") and e.get("class") and e["sub"] not in older} <= book


def test_the_index_holds_names_never_words():
    """A standing rule (CLAUDE.md, the repo is public): never commit book text. The index keeps names, classes, levels
    and the kind of number; nothing longer."""
    for r in INDEX:
        assert set(r) <= {"kind", "name", "class", "level", "sub", "of", "group", "species", "has", "parts"}
        assert len(r["name"]) <= 60 and all(len(p["name"]) <= 60 and set(p) == {"name", "has"} for p in r.get("parts") or [])


def characters():
    """Every class and subclass at levels 1, 5, 11 and 17 (a subclass from level 3), as a made-up sheet with every
    feature and option it could have by then."""
    subs = BOOK["subclasses"]
    for cls in sorted(subs):
        for sub in [None, *sorted(subs.get(cls, ()))]:
            for lv in bc.LEVELS:
                if sub and lv < 3:
                    continue
                yield cls, sub, lv


def sheet_for(cls: str, sub: str | None, lv: int) -> tuple[dict, list[dict]]:
    rows = [r for r in INDEX if r["kind"] in ("feature", "option") and r["class"] == cls and r["level"] <= lv
            and (not r.get("sub") or r["sub"] == sub)]
    names = [r["name"] for r in rows] + [p["name"] for r in rows for p in r.get("parts") or []]
    sheet = {"classes": [{"name": cls, "level": lv, "subclass": sub}], "proficiency_bonus": 2 + (lv - 1) // 4,
             "features": [{"name": n} for n in names], "actions": [], "spells": [], "inventory": [],
             "abilities": [{"key": k, "short": k[:3], "modifier": 3} for k in rules_book.ABILITY.values()]}
    return sheet, rows


@pytest.mark.parametrize("cls, sub, lv", list(characters()), ids=plain_id)
def test_a_made_up_character_is_given_what_its_level_brings(cls, sub, lv):
    """What the data plays for a class feature reaches a character of that class, subclass and level (its class, `sub`
    and `level` match the book's), and every number in it fills from the sheet: no token is left unfilled."""
    sheet, rows = sheet_for(cls, sub, lv)
    active = rules_book.active(sheet)
    have = {rules_book._norm(e["name"]) for e in active}
    book = {rules_book._norm(e["name"]): e for e in rules_book.entries() if e.get("class") == cls}
    for r in rows:
        for name in [r["name"], *(p["name"] for p in r.get("parts") or [])]:
            e = book.get(rules_book._norm(name))
            if not e or (e.get("sub") and e["sub"] != sub) or e.get("level", 1) > lv or e.get("group"):
                continue
            assert rules_book._norm(e["name"]) in have, f"{cls} {lv} ({sub}) has {name}, but the data's entry doesn't apply"
    for a in rules_book.adds(sheet):
        for k in ("amount", "reduces", "dc"):
            assert "{" not in str(a.get(k, "")), f"{a['name']}'s {k} left a token unfilled: {a.get(k)}"
    for e in active:
        for roll in e.get("rolls") or []:
            for d in roll["dice"]:
                filled = rules_book.fill(d, sheet, e.get("class"))
                assert "{" not in filled and not re.search(r"(^|[^\d])0d\d", filled), f"{e['name']}: {d} fills to {filled}"
