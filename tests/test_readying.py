"""Ready kept on Battle (app/readying.py; feedback 14, docs/mockups/hide-ready.html): what and when, at the top of the
Reaction column, until it's used, let go or its character's turn starts."""

from app import fight
from app.models import Campaign
from tests.table_setup import char, owned_by

import pytest

pytestmark = pytest.mark.usefixtures("no_network")


def test_ready_an_attack_and_it_waits_at_the_top_of_reactions(player, db, sheet):
    cole = char(db, "Cole")
    assert 'data-use-url="/characters/%d/ready"' % cole.id in player.get(f"/characters/{cole.id}/detail?ref=rule%3Abasic%3AReady").text
    w = player.get(f"/characters/{cole.id}/ready").text
    assert 'value="attack:unarmed"' in w and "Move up to your Speed" in w and "Spell · cantrip" in w
    assert player.post(f"/characters/{cole.id}/ready", data={"what": "attack:unarmed", "trigger": ""}).status_code == 409  # (say when)
    r = player.post(f"/characters/{cole.id}/ready", data={"what": "attack:unarmed", "trigger": "Enemy 1 steps through the doorway"})
    assert r.json()["text"] == "Readied: Unarmed Strike, when Enemy 1 steps through the doorway"
    page = player.get(f"/characters/{cole.id}/battle").text
    reaction = page.split('data-econ-col="reaction"')[1]
    assert "Readied" in reaction.split('class="moves"')[0] and "When Enemy 1 steps through the doorway" in reaction and "Unarmed Strike" in reaction
    r = player.post(f"/characters/{cole.id}/ready/clear", data={"to": "used"})
    assert r.status_code == 204 and "Unarmed Strike: used" in r.headers["HX-Trigger"]
    db.refresh(cole)
    assert cole.readied is None


def test_a_readied_spell_with_a_slot_says_to_cast_it_now_and_moving_can_be_readied(player, db, sheet):
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/ready", data={"what": "spell:Faerie Fire", "trigger": "the door opens"})
    assert "Cast it now: its slot is spent and it's held with Concentration" in r.json()["text"]
    r = player.post(f"/characters/{cole.id}/ready", data={"what": "move", "trigger": "the zombie steps next to me"})
    assert r.json()["text"].startswith("Readied: Move up to") and player.post(f"/characters/{cole.id}/ready", data={"what": "spell:Wish", "trigger": "x"}).status_code == 409


def test_it_is_gone_when_its_characters_turn_starts(db):
    from app.importer import import_bundle
    from tests.table_setup import BUNDLE

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    cole.readied = {"key": "attack:unarmed", "name": "Unarmed Strike", "kind": "attack", "level": 0, "trigger": "the door opens"}
    db.flush()
    now = {"order": [{"character": cole.id, "key": "t-cole"}]}
    fight.follow(db, db.get(Campaign, cole.campaign_id), None, "t-other", now)
    assert cole.readied  # (someone else's turn)
    fight.follow(db, db.get(Campaign, cole.campaign_id), None, "t-cole", now)
    assert cole.readied is None and now["reminders"][-1]["kind"] == "readied" and "wasn't used" in now["reminders"][-1]["text"]


def test_only_its_own_player_readies(dm, db, sheet):
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    assert dm.post(f"/characters/{cole.id}/ready", data={"what": "move", "trigger": "x"}).status_code == 404
