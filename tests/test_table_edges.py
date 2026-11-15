"""askdnd's table, the paths its other tests don't take (the outside review's C12, Nov 10: the table's files were the
least tested before its cutover from D&D Beyond's VTT). What a player's page must never receive comes first: another
place's map, a creature's numbers when the DM hides them, a scene or place of another campaign; then the DM's tools'
own edges (a creature's Hit Points, a grid, a pin), each as the DM sees it said."""

import json

from sqlalchemy import select

from app import measure, rules_data, tokens
from app.models import Campaign, Place, ScenePin, Token
from tests.table_setup import char
from tests.test_table_places import _goblin, _png, table  # (the table: a place with a map)


def _toast(r) -> dict:
    said = json.loads(r.headers["HX-Trigger"]).get("toast") or {}
    return said if isinstance(said, dict) else {"text": said}


def toast(r) -> str:
    return _toast(r).get("text", "")


def warned(r) -> bool:
    return _toast(r).get("kind") == "warn"


def other_campaigns_place(db) -> Place:
    elsewhere = Campaign(slug="elsewhere", name="Elsewhere")
    db.add(elsewhere)
    db.flush()
    p = Place(campaign_id=elsewhere.id, name="Their keep")
    db.add(p)
    db.flush()
    return p


# ------------------------------------------------------------------ what a player never receives


def test_a_player_gets_only_the_shown_places_map(dm, player, db, table):
    """A standing rule (the table build plan: players see the place the DM shows, no other): another place's map picture
    is the DM's until she shows it, and Hide takes the shown one away again."""
    campaign, p = table
    assert player.get(f"/c/main/table/places/{p.id}/map").status_code == 404
    assert dm.get(f"/c/main/table/places/{p.id}/map").status_code == 200
    dm.post(f"/c/main/table/places/{p.id}/show")
    assert player.get(f"/c/main/table/places/{p.id}/map").status_code == 200
    r = dm.post(f"/c/main/table/places/{p.id}/hide")
    assert db.get(Campaign, campaign.id).shown_place_id is None and r.status_code in (204, 303)
    assert player.get(f"/c/main/table/places/{p.id}/map").status_code == 404
    assert "The ruined chapel" not in player.get("/c/main/table").text


def test_with_enemy_hit_points_off_a_player_sees_no_status(dm, player, db, table):
    """The battle setting "Enemy Hit Points: none": players see a creature, not how hurt it is; the DM still does."""
    campaign, p = table
    campaign.shown_place_id = p.id
    db.flush()
    gob = _goblin(dm, db, p)
    dm.post(f"/c/main/table/tokens/{gob.id}/hp", data={"change": "1"})
    dm.post("/c/main/table/settings", data={"enemy_hp": "none"})
    seen = next(t for t in tokens.shown(db, p, {"email": "player@example.com"}, campaign, False, []) if t["id"] == gob.id)
    assert seen["status"] == "" and seen["hp"] is None
    theirs = next(t for t in tokens.shown(db, p, {"email": "dm@example.com"}, campaign, True, []) if t["id"] == gob.id)
    assert theirs["status"] == "Bloodied" and theirs["hp"] is not None


def test_another_campaigns_place_token_or_scene_is_not_found(dm, db, table):
    """A role is per campaign: a place of another campaign is never shown, pinned to, given a scene or creatures."""
    other = other_campaigns_place(db)
    elsewhere_token = Token(campaign_id=other.campaign_id, place_id=other.id, kind="monster", name="Their guard")
    db.add(elsewhere_token)
    db.flush()
    assert dm.post(f"/c/main/table/places/{other.id}/show").status_code == 404
    assert dm.post(f"/c/main/table/places/{other.id}/creatures", data={"key": "ogre"}).status_code == 404
    assert dm.post(f"/c/main/table/tokens/{elsewhere_token.id}/hp", data={"change": "-1"}).status_code == 404
    assert dm.post("/c/main/table/scenes", data={"place": str(other.id)}).status_code == 404
    _, p = table
    dm.post("/c/main/table/scenes", data={"place": str(p.id)})
    s = db.scalar(select(ScenePin))
    assert dm.post(f"/c/main/table/scenes/{s.id}/pin", data={"place": str(other.id), "x": "1", "y": "1"}).status_code == 404
    assert db.get(ScenePin, s.id).place_id == p.id


# ------------------------------------------------------------------ the DM's tools


def test_a_creatures_hit_points_take_damage_heal_and_set(dm, db, table):
    """−7 takes 7 (Temporary Hit Points first), +5 heals to at most its maximum, 20 sets it; anything else is explained."""
    _, p = table
    gob = _goblin(dm, db, p)
    top = gob.hp["max"]
    gob.hp = {"current": top, "max": top, "temp": 2}
    db.flush()
    dm.post(f"/c/main/table/tokens/{gob.id}/hp", data={"change": "−5"})  # (the typographic minus too)
    db.refresh(gob)
    assert gob.hp == {"current": top - 3, "max": top, "temp": 0}
    dm.post(f"/c/main/table/tokens/{gob.id}/hp", data={"change": "+50"})
    db.refresh(gob)
    assert gob.hp["current"] == top
    r = dm.post(f"/c/main/table/tokens/{gob.id}/hp", data={"change": "0"})
    db.refresh(gob)
    assert gob.hp["current"] == 0 and "Down" in toast(r)
    assert warned(dm.post(f"/c/main/table/tokens/{gob.id}/hp", data={"change": "half"}))
    cole = char(db, "Cole")
    mine = Token(campaign_id=p.campaign_id, place_id=p.id, kind="character", character_id=cole.id, name="Cole")
    db.add(mine)
    db.flush()
    assert warned(dm.post(f"/c/main/table/tokens/{mine.id}/hp", data={"change": "-1"}))  # (a character's are on its sheet)
    assert dm.post(f"/c/main/table/tokens/{mine.id}/rename", data={"name": "Someone"}).status_code == 422
    dm.post(f"/c/main/table/tokens/{gob.id}/rename", data={"name": "  The   scout "})
    db.refresh(gob)
    assert gob.name == "The scout"


def test_a_creature_not_in_the_books_is_said_plainly(dm, db, table):
    _, p = table
    r = dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "no-such-creature"})
    assert warned(r) and not db.scalar(select(Token))


def test_creatures_are_found_by_name_and_kind(dm, db, table):
    page = dm.get("/c/main/table/creatures", params={"q": "gob"}).text
    assert "Goblin" in page
    assert "Goblin" not in dm.get("/c/main/table/creatures", params={"q": "zzzz"}).text


def test_the_party_needs_a_map_first(dm, db, table):
    _, p = table
    p.map_key = None
    db.flush()
    assert warned(dm.post(f"/c/main/table/places/{p.id}/party"))
    assert not db.scalar(select(Token))


def test_a_down_creature_threatens_no_one_and_reach_comes_from_its_stat_block(dm, db, table):
    """A creature at 0 Hit Points makes no Opportunity Attack; one added before reach was kept on its token has it
    looked up from its stat block."""
    campaign, p = table
    gob = _goblin(dm, db, p)
    cole = char(db, "Cole")
    mine = Token(campaign_id=campaign.id, place_id=p.id, kind="character", character_id=cole.id, name="Cole")
    db.add(mine)
    db.flush()
    assert [t["name"] for t in tokens.threats(db, campaign, mine)] == [gob.name]
    gob.hp = dict(gob.hp, current=0)
    db.flush()
    assert tokens.threats(db, campaign, mine) == []
    gob.monster = {k: v for k, v in gob.monster.items() if k != "reach"}
    assert tokens.reach(db, campaign, gob) == measure.reach_of(rules_data.find("monster", gob.monster["key"], db, campaign.id))


def test_a_grid_says_what_it_needs(dm, db, table):
    _, p = table
    assert warned(dm.post(f"/c/main/table/places/{p.id}/grid", data={"across": "0"}))
    assert warned(dm.post(f"/c/main/table/places/{p.id}/grid", data={"across": "5000"}))  # (squares too small to use)
    dm.post(f"/c/main/table/places/{p.id}/grid", data={"across": "20", "x": "0", "y": "0"})
    db.refresh(p)
    assert p.grid["size"] == 35
    dm.post(f"/c/main/table/places/{p.id}/rename", data={"name": "  The   crypt "})
    db.refresh(p)
    assert p.name == "The crypt"


def test_a_picture_without_a_grid_gets_a_first_guess(dm, db, table):
    """A picture brings no grid: 30 squares across until the DM sets it (a Universal VTT file brings its own)."""
    campaign, _ = table
    p = Place(campaign_id=campaign.id, name="A cave", position=2)
    db.add(p)
    db.flush()
    r = dm.post(f"/c/main/table/places/{p.id}/map", files={"file": ("cave.png", _png(600, 300), "image/png")})
    db.refresh(p)
    assert p.map_key and p.grid == {"size": 20.0, "x": 0, "y": 0} and "Set its grid" in toast(r)


def test_a_scene_pin_moves_and_comes_off(dm, db, table):
    _, p = table
    dm.post("/c/main/table/scenes", data={"place": str(p.id), "x": "3", "y": "2"})
    s = db.scalar(select(ScenePin))
    dm.post(f"/c/main/table/scenes/{s.id}/pin", data={"place": str(p.id), "x": "5", "y": "6"})
    db.refresh(s)
    assert (s.x, s.y) == (5, 6)
    dm.post(f"/c/main/table/scenes/{s.id}/pin", data={"x": "-1"})
    db.refresh(s)
    assert (s.x, s.y, s.place_id) == (None, None, p.id)  # (off the map, still the place's)
    assert "The ruined chapel" in dm.get("/c/main/table").text


# ------------------------------------------------------------------ the fight's edges


def test_the_fights_buttons_say_when_theres_nothing_to_do(dm, db, table):
    """Begin, End turn, Undo and End with no fight (or none waiting) each say so; Start needs someone on the map and
    no fight already running."""
    _, p = table
    for path in ("begin", "next", "undo", "end"):
        assert warned(dm.post(f"/c/main/table/fight/{path}")), path
    assert warned(dm.post(f"/c/main/table/places/{p.id}/fight"))  # (no one on the map)
    _goblin(dm, db, p)
    dm.post(f"/c/main/table/places/{p.id}/fight")
    assert warned(dm.post(f"/c/main/table/places/{p.id}/fight"))  # (one is running)
    dm.post("/c/main/table/fight/begin")
    assert warned(dm.post("/c/main/table/fight/begin"))  # (it began already)


def test_creatures_added_mid_fight_join_it_with_one_roll_per_group(dm, db, table):
    """+ Creatures during a fight: they join the order, a group of the same creature on one Initiative."""
    campaign, p = table
    _goblin(dm, db, p)
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post("/c/main/table/fight/begin")
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "goblin-warrior", "count": "3"})
    order = db.get(Campaign, campaign.id).fight["order"]
    joined = [x for x in order if x["name"].startswith("Goblin Warrior ")]
    assert len(order) == 4 and len(joined) == 3 and len({x["initiative"] for x in joined}) == 1
    assert sum(1 for x in order if x.get("active")) == 1  # (whose turn it is didn't change)


def test_a_late_initiative_roll_doesnt_move_anyone_once_the_fight_began(dm, player, db, table):
    """After Begin only the DM moves anyone: a player's roll then doesn't land."""
    from app import table_fight

    campaign, p = table
    campaign.shown_place_id = p.id
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/party")
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post("/c/main/table/fight/begin")
    cole = char(db, "Cole")
    assert table_fight.rolled(db, db.get(Campaign, campaign.id), cole, "", 25) is False


def test_a_creatures_initiative_comes_from_its_stat_block():
    from app import table_fight

    assert table_fight._mod(None) == 0
    assert table_fight._mod({"initiative": 4}) == 4
    assert table_fight._mod({"abilities": {"dex": 15}}) == 2
    assert table_fight._mod({"abilities": {}}) == 0


def test_a_token_that_never_joined_leaves_the_fight_as_it_was(dm, db, table):
    from app import table_fight

    campaign, p = table
    _goblin(dm, db, p)
    dm.post(f"/c/main/table/places/{p.id}/fight")
    before = db.get(Campaign, campaign.id).fight["order"]
    table_fight.left(db, db.get(Campaign, campaign.id), 999999)
    assert db.get(Campaign, campaign.id).fight["order"] == before
