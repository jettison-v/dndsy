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


def test_party_gives_it_its_own_card_after_its_masters(player, db, labs):
    """Brett, Nov 4 (Creatures as Characters board 7, A): on Party a creature is as easy to see as a character, its own card
    right after its master's (whose it is, its Hit Points, AC, Speed and turn), opening its Battle; its master's says "with"."""
    page = player.get("/party").text
    master, mine = page.index('data-modal-url="/characters/%d/brief"' % labs.id), page.index('class="section pt-card pt-creature-card"')
    assert master < mine and page.count("</article>", master, mine) == 1  # (the very next card)
    card = page[mine:page.index("</article>", mine)]
    assert "Cole's Homunculus" in card and f'href="/characters/{labs.id}/battle?creature={ZAP}" data-no-peek' in card
    assert "<b>1</b><span class=\"note\"> / 1" in card and "Right after its master" in card  # (Cole has no Artificer levels: D&D Beyond's 1)
    assert "with Homunculus" in page[master:mine]
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    assert "pt-creature-card" not in player.get("/party").text


# ------------------------------------------------------------------ its Hit Points on D&D Beyond (slice 2)


def ops(db, ch):
    from app import ddb_bridge

    return ddb_bridge.outbox(db, ch)["ops"]


def test_its_damage_and_healing_go_to_d_and_d_beyond_as_its_sheet_sends_them(player, db, labs):
    """Brett, Nov 3 ("keep D&D Beyond up to date"): PUT creature/hp, as D&D Beyond's own sheet sends it (tried on Vi's test
    sheet); temporary hit points take damage first, and it never takes more than its maximum."""
    r = player.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "3", "to": "damage"})  # (Cole: its stat block's 1 HP)
    assert r.status_code == 204 and "took 3" in r.headers["HX-Trigger"]
    op, = ops(db, labs)
    assert (op["method"], op["path"]) == ("PUT", "/character/v5/creature/hp")
    assert op["body"] == {"characterId": 75423618, "id": ZAP, "removedHitPoints": 1, "temporaryHitPoints": 0}  # (1 HP: at 0)
    assert "Cole's Homunculus Servant" in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text


def maxima(db, ch):
    from app.models import BridgeIntent

    return [(i.data["value"], i.state) for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == ch.id).order_by(BridgeIntent.id))
            if str(i.data.get("field", "")).startswith("creature_max:")]


def test_askdnd_sets_the_rules_maximum_on_d_and_d_beyond_by_itself(player, db, labs, sheet):
    """Brett, Nov 4 (Creatures as Characters, A: askdnd keeps D&D Beyond's Extras in step): D&D Beyond counts damage against
    the maximum it shows (its stat block's 1 for a Homunculus Servant), so a read sets the rule's there (its character value
    43), with no button; − and + work at once, as it's on its way."""
    sheet["classes"][0]["definition"]["name"] = "Artificer"  # (Cole as an artificer, for the rule)
    characters.refresh(db, labs)
    (value, _), = maxima(db, labs)
    assert value > 1
    op, = ops(db, labs)
    assert (op["method"], op["path"]) == ("PUT", "/character/v5/custom/value")
    assert {k: op["body"][k] for k in ("typeId", "valueId", "contextId", "value")} == {"typeId": 43, "valueId": str(ZAP), "contextId": None, "value": value}
    k = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "Set D&amp;D Beyond to" not in k and "askdnd sets" not in k and "−/+" in k
    assert player.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "3", "to": "damage"}).status_code == 204
    characters.refresh(db, labs)
    assert len(maxima(db, labs)) == 1  # (on its way: not asked again)


def test_the_maximum_is_set_once_per_number_and_never_over_a_typed_one(db, labs, sheet):
    """One given up (or undone) isn't made again; one its player or DM typed on D&D Beyond stays theirs; after a level-up
    askdnd's own number moves on."""
    sheet["classes"][0]["definition"]["name"] = "Artificer"
    characters.refresh(db, labs)
    from app.models import BridgeIntent

    it = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == labs.id)).one()
    first = it.data["value"]
    it.state = "dismissed"
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "dismissed")]
    it.state = "live"  # (made: D&D Beyond holds askdnd's number)
    sheet["characterValues"] = [{"typeId": 43, "valueId": str(ZAP), "value": first}]
    sheet["classes"][0]["level"] += 1  # (a level-up: the rule's number grows)
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "live"), (first + 1, "waiting")]
    db.delete(db.scalars(select(BridgeIntent).where(BridgeIntent.state == "waiting")).one())
    sheet["characterValues"] = [{"typeId": 43, "valueId": str(ZAP), "value": 9}]  # (typed on D&D Beyond)
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "live")]


def test_without_your_creatures_on_nothing_is_set(db, labs, sheet):
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    sheet["classes"][0]["definition"]["name"] = "Artificer"
    characters.refresh(db, labs)
    assert maxima(db, labs) == []


def test_a_creature_change_is_only_for_its_player_or_the_dm(dm, db, labs):
    from tests.roles import set_role

    assert dm.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "1", "to": "heal"}).status_code == 404  # (not the DM yet)
    set_role(db, "dm@example.com", "dm")
    assert dm.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "1", "to": "heal"}).status_code == 204


def test_the_extension_sends_a_character_value_only_for_a_creatures_maximum():
    """extension 0.10.0: custom/value is on its list, but only for type 43 (ddb-page.js)."""
    import os

    js = open(os.path.join(os.path.dirname(__file__), "..", "extension", "askdnd-bridge", "ddb-page.js")).read()
    assert "const CREATURE_MAX = 43" in js and "op.body.typeId) !== CREATURE_MAX" in js
