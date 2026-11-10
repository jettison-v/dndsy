"""Search, like Spotlight (app/search.py; Brett chose A and A, Nov 9): `/search/index` is everything a person can find,
matched in the browser as they type. Your own character's rows come with what Enter does, the story only what the
Campaign page shows that person, and every place a result goes opens without a redirect."""

from sqlalchemy import select

from app import characters
from app.importer import import_bundle
from app.models import Campaign, Entity, EntityKind, Status
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by


def _entries(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    campaign = db.get(Campaign, cole.campaign_id)
    db.add_all([Entity(campaign_id=campaign.id, kind=EntityKind.PLACE, name="Stern Wood", summary="A forest.", status=Status.PUBLISHED),
                Entity(campaign_id=campaign.id, kind=EntityKind.NPC, name="The Veiled Duke", summary="Secretly runs the cult.", status=Status.DRAFT)])
    db.flush()
    return cole, campaign


def _rows(client, group=None):
    r = client.get("/search/index")
    assert r.status_code == 200, r.text[:300]
    rows = r.json()["rows"]
    return [x for x in rows if group is None or x["g"] == group]


def test_a_player_finds_their_character_the_rules_the_story_and_pages(no_network, player, db):
    cole, _ = _entries(db)
    owned_by(db, cole, "player@example.com")
    data = player.get("/search/index").json()
    assert data["character"] == cole.id and data["ctx"]  # (what a roll needs, as Battle's rows carry it)
    mine = [r for r in data["rows"] if r["g"] == "Your character"]
    assert mine and all(r.get("a") and r.get("panel") for r in mine)
    for r in mine:  # each does one thing on Enter: roll it, Cast or Use it, else open its side panel
        assert sum(k in r for k in ("roll", "use", "go")) == 1, r
    assert any(r["a"] == "Roll" and r["roll"]["roll"] == "attack" for r in mine)
    checks = {r["n"] for r in _rows(player, "Checks, saves, skills")}
    assert {"Stealth check", "Dex save", "Initiative"} <= checks
    assert any(r["n"] == "Prone" and r["text"] for r in _rows(player, "Rules"))
    assert {"Story", "Campaign", "Party", "Help"} <= {r["n"] for r in _rows(player, "Pages")}


def test_hidden_entries_are_as_if_they_did_not_exist(no_network, player, dm, db):
    """A standing rule (Brett, Nov 6; CLAUDE.md › Privacy): a hidden World entry never reaches the table, its name
    included. The DM finds it, marked hidden."""
    cole, campaign = _entries(db)
    owned_by(db, cole, "player@example.com")
    set_role(db, "dm@example.com", "dm", campaign=campaign)
    seen = _rows(player, "The story")
    assert "Stern Wood" in {r["n"] for r in seen}
    assert "Veiled" not in player.get("/search/index").text
    dm_sees = {r["n"]: r["s"] for r in _rows(dm, "The story")}
    assert dm_sees["The Veiled Duke"].endswith("hidden") and not dm_sees["Stern Wood"].endswith("hidden")


def test_every_place_a_result_goes_opens(no_network, player, admin, db):
    cole, _ = _entries(db)
    owned_by(db, cole, "player@example.com")
    for client in (player, admin):
        for r in _rows(client):
            for url in filter(None, (r.get("go"), r.get("panel"))):
                got = client.get(url, follow_redirects=False)
                assert got.status_code == 200, (r["n"], url, got.status_code)


def test_signed_out_finds_nothing(db):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/search/index").status_code == 401
