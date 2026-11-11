"""The roll engine's hand-written data (app/data/rules/<book>.json; the Roll Data Review, Nov 10,
docs/artifacts/roll-data-review.html): one file per book, each entry a spell, feature, feat, item or the like with what
it rolls when used (`rolls`), what it does to another roll (`adds`) and what using an item rolls (`use`). Every entry is
checked here, so a book's worth of entries can't slip in a shape the engine can't play."""

import json
from pathlib import Path

import pytest

from app import roll_recipes as rr

BOOKS = sorted((Path(__file__).resolve().parents[1] / "app" / "data" / "rules").glob("*.json"))
KINDS = {"spell", "feature", "feat", "item", "species", "mastery"}
RESOLVE = {"attack", "save", "none"}
EFFECT = {"damage", "heal", "temp", "dice"}
WHEN = {"before", "after_roll", "after_fail", "on_hit", "on_miss", "on_damage", "damage_taken"}
TO = {"attack", "save", "check", "damage", "spell damage", "damage_taken"}
WITH = {"weapon", "melee_weapon", "ranged_weapon", "monk_weapon", "finesse", "heavy_weapon", "unarmed", "spell", "this_item"}  # (roll_plan.traits)


def entries():
    for f in BOOKS:
        data = json.loads(f.read_text())
        assert data["book"] == f.stem and data["about"]
        for e in data["entries"]:
            yield f.stem, e


def test_there_is_a_file_per_book():
    assert {f.stem for f in BOOKS} >= {"srd-5.2.1", "phb-2024", "dmg-2024", "other-books"}


@pytest.mark.parametrize("book, e", list(entries()), ids=lambda x: x if isinstance(x, str) else x.get("name"))
def test_every_entry_has_a_shape_the_engine_plays(book, e):
    assert e["kind"] in KINDS and e["name"].strip() == e["name"] and e["name"]
    assert book != "other-books" or e.get("book"), "an entry from another book names its book"
    assert {"rolls", "adds", "use", "after_hit", "why"} & set(e), "an entry says what it does"
    for r in e.get("rolls") or []:
        assert r["resolve"] in RESOLVE and r["effect"] in EFFECT and r["name"]
        assert r["dice"] and all(rr.parse_part(p.replace("{", "").replace("}", "").replace("level:", "").replace("mod:", "")) or "{" in p for p in r["dice"])
        assert r.get("when") in (None, "on_hit")
        if r["resolve"] == "save":
            assert r.get("save") and r.get("success") in ("half", "none")
    for a in e.get("adds") or []:
        assert a["name"] and a["when"] in WHEN and set(a.get("to") or []) <= TO
        assert a.get("amount") or a.get("reduces") or a.get("op") in ("words", "save", "type", "twice"), "an add says what it does"
        assert a.get("op", "add") in ("add", "words", "save", "type", "twice")
        assert set(a.get("with") or []) <= WITH, a.get("with")


def test_names_are_unique_within_a_kind():
    seen = {}
    for book, e in entries():
        key = (e["kind"], e["name"].replace("’", "'"), e.get("class"), e.get("sub"))  # (Guided Strike: a War Domain's and a Conquest Paladin's)
        assert key not in seen, f"{key} is in {seen[key]} and {book}"
        seen[key] = book
