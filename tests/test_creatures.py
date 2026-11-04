"""Your creatures (app/creatures.py; docs/plans/2026-11-03-your-creatures.md): a creature on a character's D&D Beyond sheet
that isn't a Wild Shape form gets a switch by the name on Battle, and Battle is drawn as the creature's, with the numbers
that grow with its master worked out. Made-up stat blocks in D&D Beyond's shape (never a book's words)."""

import pytest
from sqlalchemy import select

from app import characters, creatures
from app.models import Campaign, TableRoll
from tests.table_setup import char

ZAP = 990001


def made_up(name="Homunculus Servant", group=12, cid=ZAP, removed=0):
    """A creature as D&D Beyond's sheet lists it, with older words (a "Weapon Attack … to hit", damage without its average)."""
    return {"id": cid, "entityTypeId": 1, "name": None, "groupId": group, "isActive": False, "removedHitPoints": removed, "temporaryHitPoints": 0,
            "definition": {"name": name, "armorClass": 13, "averageHitPoints": 1, "hitPointDice": {"diceString": "1d4"}, "challengeRatingId": 1,
                           "sizeId": 2, "passivePerception": 12, "movements": [{"movementId": 1, "speed": 20}, {"movementId": 4, "speed": 30}],
                           "stats": [{"statId": i, "value": v} for i, v in zip(range(1, 7), (4, 15, 12, 10, 10, 7), strict=True)],
                           "savingThrows": [{"statId": 2}], "skills": [{"skillId": 14, "value": 2, "additionalBonus": 2}],
                           "conditionImmunities": [11], "senses": [{"senseId": 2, "notes": "60 ft."}],
                           "specialTraitsDescription": "<p><strong>Might of the Master.</strong> Made-up words: it grows with its master.</p>",
                           "actionsDescription": "<p><strong>Zap.</strong> Ranged Weapon Attack: +4 to hit, range 30 ft., one target. Hit: 1d4 + 2 force damage.</p>",
                           "reactionsDescription": "<p><strong>Carry.</strong> It carries a touch spell for its master.</p>",
                           "characteristicsDescription": "<p>A made-up helper.</p>"}}


@pytest.fixture(autouse=True)
def labs(db, sheet):
    """Your creatures is a Labs feature (app/vtt.py): on for Cole's campaign, with a made-up creature on his sheet."""
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["sync", "labs", "creatures"]
    sheet["creatures"] = [*sheet.get("creatures", []), made_up()]
    characters.refresh(db, cole)
    db.flush()
    return cole


def master(level=10, intelligence=16, pb=4):
    return {"classes": [{"name": "Artificer", "level": level}], "proficiency_bonus": pb,
            "abilities": [{"key": "intelligence", "score": intelligence}], "creatures": []}


def test_an_older_stat_block_is_read_in_the_2024_words():
    assert creatures.modern("Zap. Ranged Weapon Attack: +4 to hit, range 30 ft. Hit: 1d4 + 2 force damage.") == \
        "Zap. Ranged Attack Roll: +4, range 30 ft. Hit: 4 (1d4 + 2) Force damage."
    assert "6 (2d6 - 1) Piercing damage plus 3 (1d6) fire damage" in creatures.modern("Hit: 2d6 - 1 piercing damage plus 3 (1d6) fire damage.")


def test_its_numbers_grow_with_its_master(db, labs):
    """Brett, Nov 3 ("work them out"): a Homunculus Servant's Hit Points from its book's rule, and Might of the Master (its own
    trait) adds the master's Proficiency Bonus above 2 to its attack, damage, saves and skills."""
    c = creatures.yours(characters.character_summary(labs))[0]
    k = creatures.card(master(), c)
    assert k["hp"]["max"] == 1 + 3 + 10 and k["hp"]["current"] == 14 and "Tasha's Cauldron of Everything" in k["notes"][0]
    zap = k["columns"]["Action"]["all"][0]
    assert (zap["name"], zap["hit"], zap["recipe"]["events"][0]["parts"]) == ("Zap", "+6", ["1d4+4 force"]) and "worn item" not in zap["meta"]
    assert next(s["label"] for s in k["saves"] if s["key"] == "dex") == "+6"  # (Dex +2, proficient +2, Might +2)
    assert k["skills"] == [{"name": "Perception", "label": "+6"}] and k["immune"] == ["Poisoned"] and k["walk"] == 20
    assert "Right after its master's turn" in k["turn"] and [o["name"] for o in k["columns"]["Action"]["all"]] == ["Zap", "Dodge"]
    low = creatures.card(master(level=2, intelligence=10, pb=2), c)
    assert low["hp"]["max"] == 3 and low["columns"]["Action"]["all"][0]["hit"] == "+4"  # (level 2: +4 as the stat block says)


def test_a_familiar_keeps_its_stat_block_and_rolls_its_own_initiative():
    owl = creatures.card(master(), _parsed(made_up("Owl", group=2, cid=7)))
    assert owl["hp"]["max"] == 1 and owl["own_initiative"] and "rolls its own Initiative" in owl["turn"]


def _parsed(raw):
    from app.ddb_sheet import parse_character
    from tests.table_setup import COLE

    return next(x for x in parse_character({**COLE, "creatures": [raw]})["creatures"] if x["id"] == raw["id"])


def test_wild_shape_forms_are_not_creatures(db, labs, sheet):
    sheet["creatures"].append(made_up("Ape", group=13, cid=5))
    characters.refresh(db, labs)
    assert [c["kind"] for c in creatures.yours(characters.character_summary(labs))] == ["Homunculus Servant"]


def test_battle_has_the_switch_and_draws_the_creature(player, db, labs):
    page = player.get(f"/characters/{labs.id}/battle").text
    assert 'class="who-switch' in page and f'href="/characters/{labs.id}/battle?creature={ZAP}"' in page and ">Homunculus</a>" in page
    k = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "Cole's Homunculus Servant" in k and 'data-who="Homunculus Servant"' in k and ">Zap</b>" in k and "Back to Cole" in k
    assert "1d4+3 force" in k and "<b>1</b>" in k  # (Might of the Master: Cole's Proficiency Bonus +3; no Artificer, so D&D Beyond's 1 HP)
    assert "Cole's Homunculus" not in player.get(f"/characters/{labs.id}/battle?creature=12345").text  # (not his: his own Battle)


def test_without_labs_there_is_no_switch(player, db, labs):
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    assert "who-switch" not in player.get(f"/characters/{labs.id}/battle").text
    assert "Cole's Homunculus" not in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text


def test_a_creatures_roll_says_whose_it_is(player, db, labs):
    """Table rolls says "Cole (Homunculus Servant)"; a name that isn't one of his creatures is ignored."""
    for who in ("Homunculus Servant", "Tarrasque"):
        r = player.post("/rolls", data={"character": labs.id, "kind": "attack", "label": "Zap", "mod": "6", "who": who})
        assert r.status_code == 200
    rows = list(db.scalars(select(TableRoll).where(TableRoll.character_id == labs.id).order_by(TableRoll.id)))
    assert [r.who for r in rows[-2:]] == ["Homunculus Servant", ""]


def test_party_shows_it_under_its_master(player, db, labs):
    """Brett, Nov 3: on Party, under its master's card, its Hit Points and AC, opening its master's Battle as it."""
    page = player.get("/party").text
    assert 'class="pt-line pt-creature"' in page and f'href="/characters/{labs.id}/battle?creature={ZAP}" data-no-peek' in page
    assert "<b>1</b><span class=\"note\"> / 1 HP" in page  # (Cole has no Artificer levels: D&D Beyond's 1)
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    assert "pt-creature" not in player.get("/party").text
