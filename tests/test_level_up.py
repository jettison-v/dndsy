"""After leveling on D&D Beyond (app/level_up.py): what's new, shown once to the character's player."""

import pytest

from app import characters, level_up
from app.models import Campaign
from tests.table_setup import char


def sheet_at(level, **kw):
    return {"level": level, "hit_points": {"max": 40 + level}, "proficiency_bonus": 3, "features": [{"key": "feature:a", "name": "Old"}], "spells": [],
            "spell_slots": {"slots": [{"level": 1, "max": 4}]}, **kw}


def test_a_level_up_lists_what_changed():
    new = sheet_at(9, proficiency_bonus=4, features=[{"key": "feature:a", "name": "Old"}, {"key": "feature:b", "name": "New"}],
                   spells=[{"key": "spell:Bless", "name": "Bless"}], spell_slots={"slots": [{"level": 1, "max": 4}, {"level": 2, "max": 2}]})
    got = level_up.changes(sheet_at(8), new)
    assert (got["from"], got["to"], got["hp"], got["pb"]) == (8, 9, 1, 4)
    assert got["features"] == [{"key": "feature:b", "name": "New"}] and got["spells"][0]["name"] == "Bless"
    assert got["slots"] == [{"level": 2, "more": 2}]


def test_nothing_is_new_without_a_higher_level_or_a_copy_to_compare():
    assert level_up.changes(sheet_at(8), sheet_at(8)) is None
    assert level_up.changes(sheet_at(9), sheet_at(8)) is None  # (a level taken back)
    assert level_up.changes(None, sheet_at(8)) is None  # (first read of a new character)


def test_two_levels_before_reading_the_first_are_one_list():
    first = level_up.changes(sheet_at(8), sheet_at(9, features=[{"key": "feature:b", "name": "B"}]))
    second = level_up.changes(sheet_at(9), sheet_at(10, features=[{"key": "feature:c", "name": "C"}]))
    both = level_up.merged(first, second)
    assert (both["from"], both["to"], both["hp"]) == (8, 10, 2) and [f["name"] for f in both["features"]] == ["B", "C"]


@pytest.fixture
def leveled(db, sheet):
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    cole = char(db, "Cole")
    next(c for c in sheet["classes"])["level"] += 1
    characters.refresh(db, cole)
    assert cole.level_up
    return cole


def test_battle_shows_it_to_the_player_until_they_say_got_it(player, db, leveled):
    page = player.get(f"/characters/{leveled.id}/battle").text
    assert "what's new" in page.replace("&#39;", "'")
    assert player.post(f"/characters/{leveled.id}/level-up/read").status_code == 204
    db.refresh(leveled)
    assert leveled.level_up is None and "level-up" not in player.get(f"/characters/{leveled.id}/battle").text.split('id="battle-body"')[1].split("battlebar")[0]


def test_only_the_player_clears_it(dm, leveled):
    assert dm.post(f"/characters/{leveled.id}/level-up/read").status_code == 404
