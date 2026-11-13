"""askdnd's table, the map's own rules (docs/plans/2026-11-06-table-build-plan.md slices 8 to 10): moving and measuring
(app/measure.py), fog and Difficult Terrain (app/fog.py), spell areas (app/areas.py)."""

from sqlalchemy import select

from app import areas, fog, measure
from app.models import Campaign, Token
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
