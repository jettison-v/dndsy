"""The fight heard from D&D Beyond's VTT (app/fight.py; Brett, 2026-10-29: askdnd only listens). The extension on an
open VTT page says what the fight is; askdnd keeps it on the campaign, every page there hears it, and the fight band
above the name shows it to each person as D&D Beyond's VTT would."""

from app import fight, realtime
from app.models import Campaign, Character
from tests.roles import set_role
from tests.table_setup import char

GAME = "9001"


def heard(round_=2, turn=1, hidden_goblin=False, cole_ddb="75423618"):
    """What the extension says (vtt-page.js `told()`): Cole first, then Enemy 1, then a goblin the DM may have hidden."""
    order = [{"key": "t-cole", "name": "Cole", "kind": "character", "ddb_id": cole_ddb, "initiative": 18},
             {"key": "t-e1", "name": "Enemy 1", "kind": "monster", "ddb_id": None, "initiative": 15},
             {"key": "t-gob", "name": "Goblin", "kind": "monster", "ddb_id": None, "initiative": 9, "hidden": hidden_goblin}]
    for i, x in enumerate(order):
        x["active"] = i == turn - 1
    return {"round": round_, "turn": turn, "order": order}


def _campaign(db) -> Campaign:
    c = db.get(Campaign, char(db, "Cole").campaign_id)
    c.ddb_campaign_id = GAME
    return c


def test_the_vtt_tells_askdnd_the_fight_and_every_page_hears_it(player, db, sheet, monkeypatch):
    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind)))
    campaign = _campaign(db)
    set_role(db, "player@example.com", "player")
    r = player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert campaign.fight["round"] == 2 and [x["name"] for x in campaign.fight["order"]] == ["Cole", "Enemy 1", "Goblin"]
    assert campaign.fight["order"][0]["character"] == char(db, "Cole").id  # by its D&D Beyond id, in this campaign
    games = lambda: [x for x in sent if x[1] == "game"]  # noqa: E731 (the setup's own changes announce too)
    assert games() == [(campaign.id, "game")]  # every open page shows its new copy
    assert player.post(f"/bridge/fight/{GAME}", json={"fight": heard()}).json()["changed"] is False  # the same again: nothing
    player.post(f"/bridge/fight/{GAME}", json={"fight": None})  # the fight ended in the VTT
    assert campaign.fight is None and len(games()) == 2


def test_only_someone_at_that_table_and_only_where_the_bridge_is_on(player, db, sheet):
    """A standing rule (Brett, 2026-10-28: the bridge per campaign, switched on in Manage › Settings): someone
    without a role in the campaign changes nothing, nor does anyone where the bridge is off."""
    campaign = _campaign(db)
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert campaign.fight is None  # signed in, but no role in this campaign
    set_role(db, "player@example.com", "player")
    campaign.vtt_pieces = []
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert campaign.fight is None


def test_a_game_without_a_named_campaign_is_the_one_its_characters_are_in(db, sheet):
    cole = char(db, "Cole")
    cole.ddb_campaign_id = "4242"
    assert fight.campaigns_for(db, "4242") == [db.get(Campaign, cole.campaign_id)]
    copy = Character(name="Cole (test copy)", ddb_id=cole.ddb_id, ddb_campaign_id="5555", copy_of_id=cole.id)
    db.add(copy)
    db.flush()
    assert fight.campaigns_for(db, "5555") == []  # a test copy shares its original's game: never by it


def test_the_band_says_whose_turn_to_each_person_and_hides_what_the_dm_hid(player, dm, db, sheet):
    """A standing rule (Brett, 2026-10-29): a token the DM hid in D&D Beyond's VTT stays the DM's in askdnd too."""
    campaign = _campaign(db)
    set_role(db, "player@example.com", "player")
    set_role(db, "dm@example.com", "dm")
    cole = char(db, "Cole")
    fight.heard(db, campaign, heard(turn=1, hidden_goblin=True))
    band = player.get(f"/characters/{cole.id}/battle").text.split('class="fight-band"')[1].split("</div>")[0]
    assert "Round 2" in band and "Your turn" in band and "Goblin" not in band  # Cole is the player's
    band = dm.get(f"/characters/{cole.id}").text.split('class="fight-band"')[1].split("</div>")[0]
    assert "Cole’s turn" in band and 'class=" hid"' in band and "Goblin" in band  # the DM sees the hidden one, marked
    fight.heard(db, campaign, heard(turn=3, hidden_goblin=True))  # the hidden goblin's turn
    band = player.get("/c/main/party").text.split('class="fight-band"')[1].split("</div>")[0]
    assert "Goblin" not in band and "’s turn" not in band and "You’re next" in band  # on Party too; Cole is next
    fight.heard(db, campaign, None)
    assert 'class="fight-band"' not in player.get(f"/characters/{cole.id}/battle").text  # no fight, no band


def test_a_fight_not_heard_for_hours_isnt_shown(db, sheet):
    from datetime import UTC, datetime

    campaign = _campaign(db)
    fight.heard(db, campaign, heard())
    assert fight.shown(campaign, dm=False) is not None
    campaign.fight_at = datetime.now(UTC) - fight.STALE * 2  # a VTT closed mid-fight
    assert fight.shown(campaign, dm=False) is None
