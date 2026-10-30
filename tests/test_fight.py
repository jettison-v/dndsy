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
    order = [{"key": "t-cole", "name": "Cole", "kind": "character", "ddb_id": cole_ddb, "initiative": 18,
              "image": "https://www.dndbeyond.com/avatars/token-cole.png"},
             {"key": "t-e1", "name": "Enemy 1", "kind": "monster", "ddb_id": None, "initiative": 15,
              "image": "https://www.dndbeyond.com/avatars/thumbnails/enemy.jpeg"},
             {"key": "t-gob", "name": "Goblin", "kind": "monster", "ddb_id": None, "initiative": 9, "hidden": hidden_goblin,
              "monster_id": "5194879"}]  # (D&D Beyond's Allosaurus: Monster Manual art askdnd links to, rules_data.pictures)
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
    assert "Cole’s turn" in band and 'class="fb-who enemy hid"' in band and "Goblin" in band  # the DM sees the hidden one, marked
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


def test_each_in_the_order_has_its_picture(player, db, sheet):
    """A character's is its portrait, as on its own page; a creature's is its token's, only from D&D Beyond itself, else
    its Monster Manual art. The enemy (the VTT's monsters) is drawn in red, the party plain (Brett, 2026-10-29)."""
    from app import characters, rules_data

    campaign = _campaign(db)
    set_role(db, "player@example.com", "player")
    told = heard()
    told["order"][2]["image"] = "https://tracker.example.com/pixel.png"  # (not D&D Beyond's: dropped, so its Monster Manual art)
    fight.heard(db, campaign, told)
    order = fight.for_person(db, campaign, "player@example.com")["order"]
    cole = characters.character_summary(char(db, "Cole"))["portrait"]
    art = next(p["image"] for p in rules_data.pictures().values() if str(p["ddb_id"]) == "5194879")
    assert [x["picture"] for x in order] == [cole, "https://www.dndbeyond.com/avatars/thumbnails/enemy.jpeg", art]
    band = player.get(f"/characters/{char(db, 'Cole').id}/battle").text.split('class="fight-band"')[1].split("</div>")[0]
    assert f'src="{cole.replace("&", "&amp;")}"' in band and "tracker.example.com" not in band and '<span class="fb-name">Goblin</span>' in band
    assert band.count('class="fb-who party now"') == 1 and band.count('class="fb-who enemy') == 2  # Cole's turn; two enemies



def test_the_extension_tells_askdnd_only_about_the_games_it_follows(player, db, sheet):
    """A standing rule (Brett, 2026-10-29, the listing's privacy answers): nothing about a D&D Beyond game askdnd
    doesn't follow leaves the browser. askdnd says which games those are: this person's campaigns with the bridge."""
    _campaign(db)
    assert player.get("/bridge/games").json()["games"] == []  # no role in the campaign
    set_role(db, "player@example.com", "player")
    assert player.get("/bridge/games").json()["games"] == [GAME]


def test_the_last_vtt_closing_leaves_no_fight_heard_and_a_closed_sheet_isnt_in_step(player, db, sheet):
    from datetime import UTC, datetime

    campaign = _campaign(db)
    set_role(db, "player@example.com", "player")
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert campaign.fight is not None
    player.post(f"/bridge/fight/{GAME}", json={"closed": True})  # the browser's last VTT tab for that game closed
    assert campaign.fight is None
    from sqlalchemy import text

    db.flush()
    assert db.scalar(text("select fight is null from campaigns where id = :i"), {"i": campaign.id})  # an empty field, not JSON null
    cole = char(db, "Cole")
    cole.sheet_heard_at = datetime.now(UTC)
    assert player.post(f"/bridge/closed/{cole.ddb_id}").status_code == 200
    assert cole.sheet_heard_at is None  # the Live pill says so at once
