"""Pieces of the usability round (Brett, 2026-10-31, docs/mockups/usability/)."""

from sqlalchemy import select

from app.templating import res_groups, table_url


def test_resources_sharing_a_name_group_under_it():
    rows = [{"name": "Infuse Item"}, {"name": "Cannon: Flame"}, {"name": "Cannon: Force"}, {"name": "Alone: One"}]
    got = res_groups(rows)
    assert [g["name"] for g in got] == ["", "Cannon", ""]
    assert [r["name"] for r in got[1]["rows"]] == ["Cannon: Flame", "Cannon: Force"]
    assert got[2]["rows"][0]["name"] == "Alone: One"  # (only one: its full name stays)


def test_the_table_button_needs_a_game_on_d_and_d_beyond():
    assert table_url({"ddb_campaign_id": "123"}) == "https://www.dndbeyond.com/games/123"
    assert table_url({"ddb_campaign_id": None}) == "" and table_url(None) == ""


def test_help_starts_on_what_askdnd_adds(player):
    html = player.get("/help").text
    assert 'aria-selected="true" data-tab="t-adds"' in html
    assert 'aria-selected="true" data-tab="t-faq"' in player.get("/help?tab=faq").text




def test_the_bridges_window_lists_your_own_sheet_and_the_table(monkeypatch, db, player):
    """Its links come from who the key belongs to, so nobody else's sheet is listed."""
    from app import config
    from app.models import Character, User

    monkeypatch.setattr(config, "DDB_BRIDGE", True)
    me = db.scalar(select(User).where(User.email == "player@example.com")) or User(email="player@example.com", name="P")
    db.add(me)
    db.flush()
    db.add(Character(name="Cole", ddb_id="55", ddb_campaign_id="77", owner_id=me.id))
    db.add(Character(name="Trah", ddb_id="56"))
    db.commit()
    got = player.get("/bridge/links").json()
    assert [c["name"] for c in got["characters"]] == ["Cole"]
    assert got["table"] == "https://www.dndbeyond.com/games/77"
