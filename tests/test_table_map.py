"""askdnd's table, the map's own rules (docs/plans/2026-11-06-table-build-plan.md slices 8 to 10): moving and measuring
(app/measure.py), fog and Difficult Terrain (app/fog.py), spell areas (app/areas.py)."""

from sqlalchemy import select

from app import areas, fog, measure
from app.models import Campaign, Place, Token
from tests.table_setup import char
from tests.test_table_places import table


# ------------------------------------------------------------------ measuring, as the 2024 rules count
def test_a_move_counts_feet_by_the_diagonal_rule_and_difficult_terrain():
    steps = measure.path((0, 0), (3, 3))
    assert len(steps) == 3 and all(s[2] for s in steps)  # (three diagonal steps)
    assert measure.cost(steps)["feet"] == 15  # (2024: every square 5 feet, diagonals too)
    assert measure.cost(steps, "alternate")["feet"] == 20  # (the DMG's option: 5, 10, 5)
    rough = measure.cost(measure.path((0, 0), (4, 0)), "5", {"2,0", "3,0"})
    assert rough == {"feet": 30, "squares": 4, "rough": 2}  # (Difficult Terrain: 1 extra foot for every foot)
    assert measure.cost(measure.path((0, 0), (2, 0)), "5", {"2,1"}, size=2)["rough"] == 2  # (a Large creature's lower squares)
    assert measure.path((2, 2), (2, 2)) == []


def test_leaving_a_creatures_reach_is_said_and_the_distance_counts_edges():
    cole = {"x": 0, "y": 0, "size": 1}
    assert measure.apart(cole, {"x": 1, "y": 1, "size": 1}) == 5  # (touching at a corner)
    assert measure.apart(cole, {"x": 3, "y": 0, "size": 2}) == 15
    ogre = {"id": 1, "name": "Ogre", "x": 1, "y": 0, "size": 2, "reach": 5}
    whip = {"id": 2, "name": "Bone Whip", "x": 0, "y": 3, "size": 1, "reach": 15}
    assert [x["name"] for x in measure.leaves(cole, (0, 0), (-2, 0), [ogre, whip])] == ["Ogre"]  # (still in the whip's 15 feet)
    assert measure.says("Cole", []) == ""
    assert measure.says("Cole", [{"name": "Ogre"}, {"name": "Enemy 1"}]).startswith("Cole left the reach of Ogre and Enemy 1: an Opportunity Attack")
    assert measure.reach_of({"actions": [{"text": "Melee Attack Roll: +6, reach 10 ft. Hit: 9"}]}) == 10
    assert measure.reach_of(None) == 5


def test_a_move_in_any_direction_enters_the_squares_on_its_way():
    """The bug-planting check (Nov 15): the squares down and up as well as across, a crooked move's own diagonals."""
    assert measure.path((0, 0), (0, 2)) == [(0, 1, False), (0, 2, False)]
    assert measure.path((3, 4), (1, 1)) == [(2, 3, True), (2, 2, False), (1, 1, True)]
    assert measure.cost(measure.path((0, 0), (1, 3)))["feet"] == 15  # (one diagonal among three steps)


def test_distance_counts_sizes_and_touching_or_overlapping_is_five():
    small = {"x": 0, "y": 0}  # (no size: one square)
    assert measure.apart(small, {"x": 2, "y": 0}) == 10
    assert measure.apart(small, {"x": 3, "y": 0, "size": 0.25}) == 15  # (Tiny takes half a square at least)
    assert measure.apart({"x": 0, "y": 0, "size": 3}, {"x": 5, "y": 0}) == 15  # (a Huge creature's far edge)
    assert measure.apart({"x": 4, "y": 0}, {"x": 0, "y": 0, "size": 3}) == 10
    assert measure.apart({"x": 1, "y": 1, "size": 2}, {"x": 1, "y": 1}) == 5  # (sharing squares: as close as can be)


def test_leaving_reach_says_who_and_how_far():
    cole = {"x": 0, "y": 0}
    near = {"id": 7, "name": "Goblin 2", "x": 0, "y": 1}  # (no reach given: 5 feet)
    pike = {"id": 8, "name": "Enemy 1", "x": 4, "y": 2, "reach": 10}
    assert measure.leaves(cole, (3, 2), (3, 8), [near, pike]) == [{"id": 8, "name": "Enemy 1", "reach": 10}]  # (down the map)
    assert measure.leaves(cole, (0, 2), (0, 5), [near]) == [{"id": 7, "name": "Goblin 2", "reach": 5}]
    assert measure.leaves(cole, (0, 2), (0, 0), [near]) == []  # (still beside it)
    assert measure.says("Cole", [{"name": "A"}]).startswith("Cole left the reach of A:")
    assert "of A, B and C:" in measure.says("Cole", [{"name": "A"}, {"name": "B"}, {"name": "C"}])
    whips = {"bonus_actions": [{"text": "reach 15 feet"}], "reactions": [{"text": "Reach 20 ft."}], "legendary_actions": [{"text": "reach 25 ft"}, {}]}
    assert measure.reach_of(whips) == 25
    assert measure.reach_of({k: v for k, v in whips.items() if k != "legendary_actions"}) == 20
    assert measure.reach_of({"bonus_actions": whips["bonus_actions"]}) == 15


def test_a_room_reaches_every_square_inside_its_walls_and_no_further():
    """The bug-planting check (Nov 15): a room spreads all four ways, stops at walls and at the map's edges."""
    walls = [(2, 0, 2, 2)]  # (a wall down the middle of a 4 × 2 map)
    left = {"0,0", "1,0", "0,1", "1,1"}
    assert fog.room(walls, (0, 0), 4, 2) == left and fog.room(walls, (1, 1), 4, 2) == left
    assert fog.room(walls, (3, 0), 4, 2) == {"2,0", "3,0", "2,1", "3,1"}
    assert fog.room(walls, (3, 1), 4, 2) == {"2,0", "3,0", "2,1", "3,1"}
    assert fog.room([], (0, 0), 4, 2) is None  # (no walls: no room to speak of)
    assert fog.room([(500, 500, 501, 500)], (0, 0), 100, 100) is None  # (open past ROOM_MOST squares)
    assert fog._crosses((0, 0), (2, 0), (1, 0), (1, 1))  # (touching counts)
    assert not fog._crosses((0, 0), (2, 0), (3, -1), (3, 1)) and fog._crosses((0, 0), (2, 2), (0, 2), (2, 0))


def test_fog_hides_a_token_only_when_none_of_its_squares_is_shown():
    p = Place(name="x", fog={"on": True, "shown": ["4,3"]})
    assert not fog.covered(p, 3, 3, 2) and fog.covered(p, 3, 3, 1)  # (a Large token: its right-hand square is shown)
    p.fog["shown"] = ["3,4"]
    assert not fog.covered(p, 3, 3, 2) and fog.covered(p, 2, 2, 1)
    assert not fog.covered(Place(name="y", fog={"on": False}), 3, 3) and not fog.covered(None, 3, 3)
    assert fog.runs({"5,0", "1,0", "2,0", "0,2"}) == [(1, 0, 2), (5, 0, 1), (0, 2, 1)]
    assert fog.hidden(Place(name="z", fog={"on": True, "shown": ["1,0"]}), 3, 1) == [(0, 0, 1), (2, 0, 1)]


def test_a_dragged_rectangle_stays_on_the_map():
    import pytest
    from fastapi import HTTPException

    assert fog._squares("3,2,1,1", 10, 10) == {f"{x},{y}" for x in (1, 2, 3) for y in (1, 2)}  # (either corner first)
    assert fog._squares("-2,-1,20,1", 4, 3) == {f"{x},{y}" for x in range(4) for y in (0, 1)}
    assert fog._squares("1,-5,1,40", 4, 3) == {"1,0", "1,1", "1,2"}
    with pytest.raises(HTTPException):
        fog._squares("a,b", 4, 3)


# ------------------------------------------------------------------ areas, from the spell's own words
def test_a_spells_area_comes_from_its_words_and_says_whos_in_it():
    assert areas.from_spell({"text": "Each creature in a 20-foot-radius Sphere centered on that point"}) == {"shape": "sphere", "feet": 20, "wide": 5}
    assert areas.from_spell({"text": "A 100-foot-long, 5-foot-wide Line blasts out"}) == {"shape": "line", "feet": 100, "wide": 5}
    assert areas.from_spell({"text": "each creature in a 15-foot Cone"})["shape"] == "cone"
    assert areas.from_spell({"text": "You touch a creature."}) is None
    tokens = [{"id": 1, "name": "Enemy 1", "x": 3, "y": 3, "size": 1}, {"id": 2, "name": "Enemy 2", "x": 9, "y": 3, "size": 1},
              {"id": 3, "name": "Ogre", "x": 6, "y": 0, "size": 2}]
    ball = {"shape": "sphere", "feet": 10, "x": 4, "y": 4}
    assert [t["name"] for t in areas.inside(ball, tokens)] == ["Enemy 1"]
    cone = {"shape": "cone", "feet": 15, "x": 4, "y": 3.5, "angle": 0}  # (east, from the edge of Enemy 1's square)
    assert [t["name"] for t in areas.inside(cone, tokens)] == []
    line = {"shape": "line", "feet": 30, "wide": 5, "x": 0, "y": 3.5, "angle": 0}
    assert [t["name"] for t in areas.inside(line, tokens)] == ["Enemy 1"]  # (Enemy 2 is 45 feet away)
    aura = {"shape": "emanation", "feet": 10, "x": 3, "y": 3, "size": 1, "token": 1}
    assert [t["name"] for t in areas.inside(aura, tokens)] == []  # (not its own creature)
    assert areas.outline(ball)["circle"] == (4, 4, 2.0) and areas.named({"shape": "line", "feet": 60, "wide": 10}) == "60-ft Line (10 ft wide)"


def test_an_area_covers_what_its_shape_and_direction_say():
    """The bug-planting check (Nov 15): each shape, pointing each way, by the 2024 rules on a grid."""
    cone = {"shape": "cone", "feet": 15, "x": 0, "y": 0, "angle": 90}  # (south: 3 squares long, as wide as it is far)
    assert areas.covers(cone, 0, 2) and areas.covers(cone, 0.9, 2) and not areas.covers(cone, 1.1, 2) and not areas.covers(cone, 0, -1)
    assert not areas.covers(cone, 0, 0) and not areas.covers(cone, 0, 3.1)  # (not its own point; no further than 15 feet)
    west = {"shape": "line", "feet": 20, "wide": 10, "x": 5, "y": 5, "angle": 180}
    assert areas.covers(west, 2, 5.9) and not areas.covers(west, 2, 6.1) and not areas.covers(west, 6, 5)  # (10 ft wide: a square either side)
    assert areas.covers({"shape": "line", "feet": 20, "x": 0, "y": 0}, 3, 0.4) and not areas.covers({"shape": "line", "feet": 20, "x": 0, "y": 0}, 3, 0.6)
    cube = {"shape": "cube", "feet": 10, "x": 0, "y": 0, "angle": 0}
    assert areas.covers(cube, 2, 1) and not areas.covers(cube, 2, 1.1) and not areas.covers(cube, 2.1, 0)
    aura = {"shape": "emanation", "feet": 10, "x": 3, "y": 3, "size": 2}  # (Large: from its edges)
    assert areas.covers(aura, 1, 1) and areas.covers(aura, 7, 7) and not areas.covers(aura, 7.1, 5) and not areas.covers(aura, 5, 0.9)
    assert areas.covers({"shape": "emanation", "feet": 5, "x": 0, "y": 0}, 2, 2) and not areas.covers({"shape": "emanation", "feet": 5, "x": 0, "y": 0}, 2.1, 0)
    assert areas.covers({"shape": "cylinder", "feet": 10, "x": 0, "y": 0}, 1.2, 1.5) and not areas.covers({"shape": "sphere", "feet": 10, "x": 0, "y": 0}, 1.5, 1.5)
    assert not areas.covers({"shape": "blob", "feet": 10, "x": 0, "y": 0}, 0, 0)


def test_an_areas_outline_is_drawn_where_it_covers():
    def pts(a):
        return [tuple(round(float(v), 2) for v in p.split(",")) for p in areas.outline(a)["points"].split()]

    assert pts({"shape": "cone", "feet": 10, "x": 1, "y": 1, "angle": 0}) == [(1, 1), (3, 0), (3, 2)]
    assert pts({"shape": "cone", "feet": 10, "x": 1, "y": 1, "angle": 90}) == [(1, 1), (2, 3), (0, 3)]
    assert pts({"shape": "line", "feet": 20, "x": 0, "y": 2, "angle": 0, "wide": 10}) == [(0, 1), (4, 1), (4, 3), (0, 3)]
    assert pts({"shape": "line", "feet": 20, "x": 0, "y": 2}) == [(0, 1.5), (4, 1.5), (4, 2.5), (0, 2.5)]
    assert pts({"shape": "cube", "feet": 15, "x": 0, "y": 0}) == [(0, -1.5), (3, -1.5), (3, 1.5), (0, 1.5)]
    o = areas.outline({"shape": "cube", "feet": 15, "x": 0, "y": 0})
    assert (round(o["lx"], 2), o["ly"]) == (1.5, -1.5)
    assert areas.outline({"shape": "emanation", "feet": 10, "x": 3, "y": 3, "size": 2}) == {"rect": (1, 1, 6, 6, 2), "lx": 4, "ly": 1}
    assert areas.outline({"shape": "sphere", "feet": 20, "x": 2, "y": 2}) == {"circle": (2, 2, 4), "lx": 2, "ly": -2}
    assert areas.named({"shape": "line", "feet": 60}) == "60-ft Line" and areas.named({"shape": "cube", "feet": 10, "wide": 10}) == "10-ft Cube"


def test_whos_in_an_area_counts_every_square_and_an_emanation_follows_its_creature():
    tokens = [{"id": 1, "name": "Cole", "x": 0, "y": 0, "size": 1}, {"id": 2, "name": "Ogre", "x": 2, "y": 2, "size": 2},
              {"id": 3, "name": "Enemy 1", "x": 3, "y": 0, "size": 1}]
    ball = {"shape": "sphere", "feet": 5, "x": 4, "y": 4}  # (a corner of the Ogre's far square)
    assert [t["name"] for t in areas.inside(ball, tokens)] == ["Ogre"]
    aura = {"id": "a", "shape": "emanation", "feet": 5, "token": 1, "by": 9}
    place = type("P", (), {"areas": [aura, {"id": "b", "shape": "sphere", "feet": 5, "x": 3.5, "y": 0.5, "by": 4},
                                     {"id": "c", "shape": "emanation", "feet": 5, "token": 99}]})()
    got = areas.shown(place, tokens, 9, False)
    assert [a["id"] for a in got] == ["a", "b"]  # (an Emanation whose creature isn't seen isn't drawn)
    assert (got[0]["x"], got[0]["y"], got[0]["size"], got[0]["in"], got[0]["mine"]) == (0, 0, 1, [], True)  # (on Cole, not Cole)
    tokens[0] |= {"x": 2, "y": 0}  # (Cole walks: the aura goes with him)
    assert areas.shown(place, tokens, 9, False)[0]["in"] == ["Enemy 1"]
    assert got[1]["in"] == ["Enemy 1"] and got[1]["mine"] is False
    assert all(a["mine"] for a in areas.shown(place, tokens, None, True))  # (the DM takes any away)
    assert not any(a["mine"] for a in areas.shown(place, tokens, None, False))  # (no one's: not a missing id matching a missing by)
    two = [aura | {"token": 3, "x": 3, "y": 0, "size": 1}, tokens[1]]
    assert areas.inside(two[0], [tokens[2], tokens[0]]) == [tokens[0]]  # (its own creature skipped, the next still counted)


def test_an_areas_tokens_are_the_ones_this_person_sees(dm, db, table):
    campaign, p = table
    db.add_all([Token(campaign_id=campaign.id, place_id=p.id, kind="monster", monster={"name": "Goblin"}, name="Seen", x=1, y=1, size=1),
                Token(campaign_id=campaign.id, place_id=p.id, kind="monster", monster={"name": "Goblin"}, name="Lurker", x=2, y=2, size=1, hidden=True)])
    db.flush()
    assert sorted(t["name"] for t in areas.tokens_for(db, p, True)) == ["Lurker", "Seen"]
    assert [(t["name"], t["x"], t["y"], t["size"]) for t in areas.tokens_for(db, p, False)] == [("Seen", 1, 1, 1)]


def test_everyone_at_the_table_places_areas_and_takes_away_their_own(dm, player, db, table):
    campaign, p = table
    campaign.shown_place_id = p.id
    db.flush()
    r = player.post(f"/c/main/table/places/{p.id}/areas", data={"shape": "sphere", "feet": "20", "x": "3", "y": "3", "label": "Fireball"})
    assert r.status_code == 204
    dm.post(f"/c/main/table/places/{p.id}/areas", data={"shape": "cone", "feet": "15", "x": "1", "y": "1", "angle": "45"})
    db.refresh(p)
    mine, hers = p.areas
    assert mine["label"] == "Fireball" and mine["by_name"]
    assert "Fireball" in dm.get("/c/main/table").text and "15-ft Cone" in player.get("/c/main/table").text
    assert player.post(f"/c/main/table/places/{p.id}/areas/{hers['id']}/remove").status_code == 403  # (the DM's)
    assert player.post(f"/c/main/table/places/{p.id}/areas", data={"shape": "blob", "feet": "20", "x": "3", "y": "3"}).status_code == 400
    assert player.post(f"/c/main/table/places/{p.id}/areas/{mine['id']}/remove").status_code == 204
    dm.post(f"/c/main/table/places/{p.id}/areas/all/remove")
    db.refresh(p)
    assert p.areas == []


def test_the_srds_area_spells_all_read():
    """Cast on the table page starts the spell's area (app/casting.py, app.js "areaTool"): every SRD spell that names an
    area in its words gives one askdnd can draw."""
    from app import rules_data

    named = [e for e in rules_data.catalog("spell") if any(f" {s.title()}" in (e.get("text") or "") for s in areas.SHAPES)
             and "-foot" in (e.get("text") or "")]
    assert len(named) > 30
    assert all(areas.from_spell(e) for e in named if e["name"] in ("Fireball", "Burning Hands", "Lightning Bolt", "Spirit Guardians", "Cone of Cold"))


# ------------------------------------------------------------------ fog and terrain
def test_fog_keeps_creatures_under_it_off_a_players_page(dm, player, db, table):
    """A standing rule (Brett, 2026-11-06, the table build plan): what the players can't see never reaches their page."""
    campaign, p = table
    campaign.shown_place_id = p.id
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/party")
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "goblin-warrior", "count": "1"})
    gob = db.scalar(select(Token).where(Token.place_id == p.id, Token.kind == "monster"))
    gob.x, gob.y = 8, 5
    db.flush()
    assert "Goblin Warrior" in player.get("/c/main/table").text
    assert dm.post(f"/c/main/table/places/{p.id}/fog", data={"do": "on"}).status_code == 204
    page = player.get("/c/main/table").text
    assert "Goblin Warrior" not in page and "tmap-fog" in page
    assert "Goblin Warrior" in dm.get("/c/main/table").text  # (the DM sees it, marked under fog)
    dm.post(f"/c/main/table/places/{p.id}/fog", data={"do": "show", "rect": "7,4,9,6"})
    assert "Goblin Warrior" in player.get("/c/main/table").text
    r = dm.post(f"/c/main/table/places/{p.id}/fog", data={"do": "room", "x": "1", "y": "1"})
    assert "no walls" in r.headers["HX-Trigger"]  # (a picture has no walls to bound a room)
    assert player.post(f"/c/main/table/places/{p.id}/fog", data={"do": "off"}).status_code == 403
    dm.post(f"/c/main/table/places/{p.id}/fog", data={"do": "none"})
    db.refresh(p)
    assert p.fog["shown"] == [] and fog.covered(p, 8, 5)


def test_a_room_stops_at_walls_and_doors():
    walls = [[0, 2, 4, 2], [4, 0, 4, 2]]  # (a room of 4 by 2 in the corner)
    got = fog.room(walls, (1, 1), 10, 6)
    assert got == {f"{x},{y}" for x in range(4) for y in range(2)}
    assert fog.room([], (1, 1), 10, 6) is None
    assert fog.runs({"1,0", "2,0", "3,0", "5,0", "0,2"}) == [(1, 0, 3), (5, 0, 1), (0, 2, 1)]


def test_difficult_terrain_and_the_diagonal_rule_count_on_your_turn(dm, player, db, table):
    campaign, p = table
    campaign.shown_place_id = p.id
    cole = char(db, "Cole")
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/party")
    tok = db.scalar(select(Token).where(Token.character_id == cole.id, Token.kind == "character"))
    tok.x, tok.y = 0, 0
    db.flush()
    assert dm.post(f"/c/main/table/places/{p.id}/terrain", data={"do": "add", "rect": "1,0,2,0"}).status_code == 204
    assert player.post(f"/c/main/table/places/{p.id}/terrain", data={"do": "none"}).status_code == 403
    dm.post("/c/main/table/settings", data={"diagonal": "alternate"})
    dm.post(f"/c/main/table/places/{p.id}/fight")
    player.post("/rolls", data={"character": str(cole.id), "kind": "check", "label": "Initiative", "mod": "40"})
    dm.post("/c/main/table/fight/begin")
    player.post(f"/c/main/table/tokens/{tok.id}/move", data={"x": "3", "y": "0"})  # (two squares of Difficult Terrain)
    db.refresh(cole)
    assert cole.turn["moved"] == 25
    player.post(f"/c/main/table/tokens/{tok.id}/move", data={"x": "5", "y": "2"})  # (two diagonals: 5, then 10)
    db.refresh(cole)
    assert cole.turn["moved"] == 40
    page = player.get("/c/main/table").text
    assert 'data-rule="alternate"' in page and "1,0" in page


def test_leaving_a_creatures_reach_in_a_fight_reminds_the_player_and_the_dm(dm, player, db, table):
    campaign, p = table
    campaign.shown_place_id = p.id
    cole = char(db, "Cole")
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/party")
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "ogre", "count": "1"})
    tok = db.scalar(select(Token).where(Token.character_id == cole.id, Token.kind == "character"))
    ogre = db.scalar(select(Token).where(Token.place_id == p.id, Token.kind == "monster"))
    tok.x, tok.y, ogre.x, ogre.y = 2, 2, 3, 2
    db.flush()
    player.post(f"/c/main/table/tokens/{tok.id}/move", data={"x": "0", "y": "2"})  # (no fight: nothing to remind)
    assert not (db.get(Campaign, campaign.id).fight or {}).get("reminders")
    tok.x = 2
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post("/c/main/table/fight/begin")
    player.post(f"/c/main/table/tokens/{tok.id}/move", data={"x": "0", "y": "2"})
    said = [r for r in db.get(Campaign, campaign.id).fight["reminders"] if r["kind"] == "reach"]
    assert said and said[-1]["text"].startswith("Cole left the reach of Ogre") and said[-1]["character"] == cole.id
