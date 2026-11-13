"""askdnd's table (docs/plans/2026-11-06-table-build-plan.md): places and their maps (app/places.py), tokens
(app/tokens.py), the DM's scene notes (app/scene_notes.py), a creature's side panel (app/table_creatures.py), askdnd
running the fight (app/table_fight.py) and your turn's bar (app/turn_bar.py)."""

import base64
import io
import json

import pytest
from sqlalchemy import select

from app import access, places
from app.models import Campaign, Character, Place, ScenePin, TableRoll, Token
from tests.roles import set_role
from tests.table_setup import char


def _png(w=700, h=490) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (90, 80, 60)).save(out, "PNG")
    return out.getvalue()


def _uvtt(ppg=70, cols=10, rows=7) -> bytes:
    return json.dumps({"format": 0.3, "resolution": {"map_origin": {"x": 0, "y": 0}, "map_size": {"x": cols, "y": rows},
                                                     "pixels_per_grid": ppg},
                       "line_of_sight": [[{"x": 1, "y": 1}, {"x": 5, "y": 1}, {"x": 5, "y": 4}]],
                       "portals": [{"bounds": [{"x": 5, "y": 2}, {"x": 5, "y": 3}], "closed": True}],
                       "image": base64.b64encode(_png(ppg * cols, ppg * rows)).decode()}).encode()


@pytest.fixture
def table(db, sheet):
    """Main with askdnd's VTT on, dm@ its DM and player@ playing Cole (the `sheet` fixture), a place with a map."""
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.vtt_pieces = ["sync", "labs", "vtt"]
    set_role(db, "dm@example.com", "dm")
    set_role(db, "player@example.com", "player")
    db.flush()
    access.invalidate()
    from app import files

    key = files.put(db, campaign.id, places.read_map(_png(), "map.png")["data"], "image/webp")
    p = Place(campaign_id=campaign.id, name="The ruined chapel", position=1, map_w=700, map_h=490, map_key=key,
              grid={"size": 70, "x": 0, "y": 0}, fog={"on": False, "shown": []})
    db.add(p)
    db.flush()
    return campaign, p


def test_a_dungeon_alchemist_file_brings_its_grid_and_walls():
    """Maps from any builder (DECISIONS 2026-11-02): a Universal VTT file's grid and walls come with it; a picture's grid
    is set by hand."""
    got = places.read_map(_uvtt(), "chapel.dd2vtt")
    assert (got["w"], got["h"]) == (700, 490) and got["grid"] == {"size": 70.0, "x": -0.0, "y": -0.0}
    assert [1.0, 1.0, 5.0, 1.0] in got["walls"] and [5.0, 2.0, 5.0, 3.0] in got["walls"]  # (walls and the door)
    pic = places.read_map(_png(), "map.png")
    assert pic["grid"] is None and pic["data"][:4] == b"RIFF"  # (kept as WebP)
    with pytest.raises(places.MapError):
        places.read_map(b"not a map", "map.png")


def test_the_dm_adds_a_place_and_its_map_and_shows_it(dm, player, db, table):
    campaign, _ = table
    assert dm.post("/c/main/table/places", data={"name": "The crypt"}).status_code == 204
    crypt = db.scalar(select(Place).where(Place.name == "The crypt"))
    r = dm.post(f"/c/main/table/places/{crypt.id}/map", files={"file": ("crypt.dd2vtt", _uvtt(), "application/octet-stream")})
    assert r.status_code == 204 and "grid and walls" in r.headers["HX-Trigger"]
    db.refresh(crypt)
    assert crypt.map_key and crypt.grid["size"] == 70
    assert player.get(f"/c/main/table/places/{crypt.id}/map").status_code == 404  # (not shown to players yet)
    assert "The crypt" not in player.get("/c/main/table").text
    dm.post(f"/c/main/table/places/{crypt.id}/show")
    db.refresh(campaign)
    assert campaign.shown_place_id == crypt.id
    assert player.get(f"/c/main/table/places/{crypt.id}/map").status_code == 200
    assert 'aria-label="The map of The crypt"' in player.get("/c/main/table").text
    assert player.post("/c/main/table/places", data={"name": "Mine"}).status_code == 403  # (places are the DM's)


def test_hidden_creatures_never_reach_a_players_page(dm, player, db, table):
    """A standing rule (Oct 28, the parked turn order; askdnd Runs the Fight): a creature the DM hid is hers alone, on the
    map, in the order and in its side panel; a creature's numbers reach players only as the battle settings say."""
    campaign, p = table
    campaign.shown_place_id = p.id
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "goblin-warrior", "count": "1", "hidden": "1"})
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "ogre", "count": "1"})
    gob = db.scalar(select(Token).where(Token.name == "Goblin Warrior"))
    ogre = db.scalar(select(Token).where(Token.name == "Ogre"))
    assert gob.hidden and not ogre.hidden and ogre.hp["max"] == 68
    page = player.get("/c/main/table").text
    assert "Ogre" in page and "Goblin" not in page
    assert player.get(f"/c/main/table/tokens/{gob.id}").status_code == 404
    seen = player.get(f"/c/main/table/tokens/{ogre.id}").text
    assert "Healthy" in seen and "68" not in seen and "Greatclub" not in seen  # (its numbers and stat block are the DM's)
    dm.post(f"/c/main/table/tokens/{ogre.id}/hp", data={"change": "-40"})
    assert "Bloodied" in player.get(f"/c/main/table/tokens/{ogre.id}").text
    full = dm.get(f"/c/main/table/tokens/{ogre.id}").text
    assert "<b>28</b>" in full and "Greatclub" in full and "Goblin" in dm.get("/c/main/table").text
    dm.post("/c/main/table/settings", data={"enemy_hp": "numbers"})
    assert "28" in player.get(f"/c/main/table/tokens/{ogre.id}").text


def test_the_dms_scene_notes_are_hers_alone(dm, admin, player, db, table):
    """A standing rule (Brett, Nov 6): the DM's scene notes are hers alone: not players, not reviewers or admins (Brett
    included), not View as; no one else learns a scene exists."""
    _, p = table
    r = dm.post("/c/main/table/scenes", data={"place": str(p.id), "x": "3", "y": "2"})
    assert r.status_code == 204
    s = db.scalar(select(ScenePin))
    dm.post(f"/c/main/table/scenes/{s.id}", data={"name": "The altar", "intro": "Rain drips through the roof.\n\nThe lever is DC 15.",
                                                  "purpose": "Where they learn who took the bell. See @The altar"})
    page = dm.get(f"/c/main/table/scenes/{s.id}").text
    assert '<div class="readaloud">Rain drips through the roof.</div>' in page and "The lever is DC 15." in page
    assert f'data-panel-url="/c/main/table/scenes/{s.id}">@The altar' in page  # (an @ name opens that scene)
    assert "The altar" in dm.get(f"/c/main/table?place={p.id}").text
    for who in (player, admin):
        assert who.get(f"/c/main/table/scenes/{s.id}").status_code == 404
        assert who.post(f"/c/main/table/scenes/{s.id}", data={"purpose": "x"}).status_code == 404
        assert "The altar" not in who.get(f"/c/main/table?place={p.id}").text
    admin.post("/view-as", data={"email": "dm@example.com"})
    assert admin.get(f"/c/main/table/scenes/{s.id}").status_code == 404


def test_players_move_their_own_tokens_and_it_counts_on_their_turn(dm, player, db, table):
    campaign, p = table
    campaign.shown_place_id = p.id
    cole, trah = char(db, "Cole"), char(db, "Trah")
    db.flush()
    assert dm.post(f"/c/main/table/places/{p.id}/party").status_code == 204
    mine = db.scalar(select(Token).where(Token.character_id == cole.id, Token.kind == "character"))
    theirs = db.scalar(select(Token).where(Token.character_id == trah.id))
    assert player.post(f"/c/main/table/tokens/{theirs.id}/move", data={"x": "1", "y": "1"}).status_code == 403
    dm.post(f"/c/main/table/places/{p.id}/fight")
    player.post("/rolls", data={"character": str(cole.id), "kind": "check", "label": "Initiative", "mod": "40"})
    f = db.get(Campaign, campaign.id).fight
    assert next(x for x in f["order"] if x.get("character") == cole.id)["initiative"] >= 41
    dm.post("/c/main/table/fight/begin")
    assert db.get(Campaign, campaign.id).fight["order"][0]["character"] == cole.id  # (the highest goes first)
    x0, y0 = mine.x, mine.y
    assert player.post(f"/c/main/table/tokens/{mine.id}/move", data={"x": str(x0 + 3), "y": str(y0)}).status_code == 204
    db.refresh(cole)
    assert cole.turn["moved"] == 15  # (three squares, on Cole's turn)
    page = player.get("/c/main/table").text
    assert "of 30 ft left" in page or "ft left" in page
    assert player.post("/c/main/table/fight/next").status_code == 204  # (End turn: their own turn)
    assert player.post("/c/main/table/fight/next").status_code == 403  # (not their turn now)
    for _ in range(10):  # (round the table to Cole again: his bar starts over as his turn begins)
        if db.get(Campaign, campaign.id).fight["order"][0]["active"]:
            break
        dm.post("/c/main/table/fight/next")
    db.refresh(cole)
    assert cole.turn is None


def test_askdnd_runs_the_fight_with_one_roll_per_group(dm, player, db, table):
    """Brett, Nov 6: a group of the same creature rolls one Initiative (the DM can give any its own number). Creatures'
    rolls are only the DM's. Undo puts the last change back; D&D Beyond's VTT isn't listened to while askdnd runs it."""
    campaign, p = table
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "goblin-warrior", "count": "3"})
    dm.post(f"/c/main/table/places/{p.id}/fight")
    f = db.get(Campaign, campaign.id).fight
    gobs = [x for x in f["order"] if x["name"].startswith("Goblin Warrior")]
    assert len(gobs) == 3 and len({x["initiative"] for x in gobs}) == 1 and f["waiting"]
    rolls = list(db.scalars(select(TableRoll).where(TableRoll.label == "Initiative")))
    assert len(rolls) == 1 and rolls[0].visibility == "dm" and rolls[0].who == "Goblin Warrior × 3"
    r = dm.post("/fight/initiative", data={"key": gobs[0]["key"], "to": "30"})  # (the DM splits one off)
    assert r.status_code == 200
    f = db.get(Campaign, campaign.id).fight
    assert f["order"][0]["key"] == gobs[0]["key"] and f["order"][0]["initiative"] == 30
    dm.post("/c/main/table/fight/begin")
    dm.post("/c/main/table/fight/next")
    assert db.get(Campaign, campaign.id).fight["order"][1]["active"]
    dm.post("/c/main/table/fight/undo")
    assert db.get(Campaign, campaign.id).fight["order"][0]["active"]
    from app import fight

    assert fight.heard(db, db.get(Campaign, campaign.id), {"round": 3, "turn": 1, "order": []}) is False
    assert dm.post("/c/main/table/fight/next", headers={}).status_code == 204
    assert player.post("/c/main/table/fight/end").status_code == 403
    dm.post("/c/main/table/fight/end")
    assert db.get(Campaign, campaign.id).fight is None


def test_your_turns_bar_counts_and_never_stops_you(player, db, table):
    """Inform, don't advise (askdnd counts, never stops a move): past your Speed only says so."""
    cole = char(db, "Cole")
    for _ in range(12):
        player.post(f"/characters/{cole.id}/turn", data={"what": "move", "n": "5"})
    player.post(f"/characters/{cole.id}/turn", data={"what": "use", "cost": "action", "n": "-1"})
    db.refresh(cole)
    assert cole.turn == {"moved": 60, "used": ["action"]}
    page = player.get("/c/main/table").text
    assert "past your Speed" in page and 'aria-pressed="true"' in page
    player.post(f"/characters/{cole.id}/turn", data={"what": "dash", "n": "1"})
    assert "past your Speed" not in player.get("/c/main/table").text
    other = db.scalar(select(Character).where(Character.name == "Trah"))
    assert player.post(f"/characters/{other.id}/turn", data={"what": "move", "n": "5"}).status_code == 404


def test_your_scratch_pad_is_jotted_off_your_turn_and_rolled_on_it(player, db, table):
    """Prepare your turn (Brett chose A and B, Nov 13: "keep it simple to start, like an executable scratch pad"): lines
    jotted from your Battle in any order, a note each, every line with its own Roll; your turn's start keeps them (a line
    rolled from it is ticked), its end clears them. Only from your own Battle, at most eight, and only your own pad."""
    from app import character_views as views
    from app import characters as chars
    from app import fight

    cole = char(db, "Cole")
    rows = [o for o in views.options(chars.character_summary(cole), set()) if o.get("cost") in ("Action", "Bonus action")][:2]
    url = f"/characters/{cole.id}/turn"
    for o in rows:
        assert player.post(url, data={"what": "pad_add", "key": o["key"]}).status_code == 204
    player.post(url, data={"what": "pad_add", "key": rows[0]["key"]})  # (once each)
    assert player.post(url, data={"what": "pad_add", "key": "nothing:of-mine"}).status_code == 422
    player.post(url, data={"what": "pad_note", "key": rows[1]["key"], "note": "  if the   cultist casts "})
    db.refresh(cole)
    assert cole.turn["pad"] == [{"key": rows[0]["key"]}, {"key": rows[1]["key"], "note": "if the cultist casts"}]
    page = player.get("/c/main/table").text
    assert "Your scratch pad" in page and rows[0]["name"] in page and 'value="if the cultist casts"' in page
    assert page.count(f'data-pad-key="{rows[0]["key"]}"') == 1  # (its own Roll, Cast or Use, as on Battle)
    # Rolled from the pad: its cost used and its line ticked; the turn's own Start over keeps the pad
    player.post(url, data={"what": "use", "cost": "action", "n": "1", "pad": rows[0]["key"]})
    db.refresh(cole)
    assert cole.turn["pad"][0]["done"] is True and cole.turn["used"] == ["action"]
    assert "tbar-pad-line done" in player.get("/c/main/table").text
    player.post(url, data={"what": "start"})
    db.refresh(cole)
    assert cole.turn == {"pad": [{"key": rows[0]["key"]}, {"key": rows[1]["key"], "note": "if the cultist casts"}]}
    # A fight: your turn beginning keeps the pad, its end clears it
    now = {"round": 1, "order": [{"key": "c", "character": cole.id}, {"key": "g", "character": None}]}
    fight.starts_over(db, "c", now)
    assert cole.turn["pad"]
    fight.starts_over(db, "g", now, "c")
    assert not (cole.turn or {}).get("pad")
    # At most eight; Clear empties it; someone else's pad isn't yours
    for o in views.options(chars.character_summary(cole), set())[:10]:
        player.post(url, data={"what": "pad_add", "key": o["key"]})
    db.refresh(cole)
    assert len(cole.turn["pad"]) == 8
    player.post(url, data={"what": "pad_remove", "key": cole.turn["pad"][0]["key"]})
    db.refresh(cole)
    assert len(cole.turn["pad"]) == 7
    player.post(url, data={"what": "pad_clear"})
    db.refresh(cole)
    assert not (cole.turn or {}).get("pad")
    other = db.scalar(select(Character).where(Character.name == "Trah"))
    assert player.post(f"/characters/{other.id}/turn", data={"what": "pad_clear"}).status_code == 404


def _goblin(dm, db, p, at=(4, 1), hidden=False):
    dm.post(f"/c/main/table/places/{p.id}/creatures", data={"key": "goblin-warrior", "count": "1", "x": str(at[0]), "y": str(at[1]),
                                                            **({"hidden": "1"} if hidden else {})})
    return db.scalars(select(Token).where(Token.kind == "monster").order_by(Token.id.desc())).first()


def test_a_creature_a_player_cant_see_is_never_named_to_them(dm, player, db, table):
    """A standing rule (CLAUDE.md, askdnd's table: a creature under fog never reaches a player's page; Nov 7 review): not
    in a reach reminder, whoever moves the token, nor in its side panel, nor on a place the DM hasn't shown."""
    campaign, p = table
    campaign.shown_place_id = p.id
    cole = char(db, "Cole")
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/party", data={"x": "3", "y": "1"})
    mine = db.scalar(select(Token).where(Token.character_id == cole.id, Token.kind == "character"))
    fogged = _goblin(dm, db, p, at=(mine.x + 1, mine.y))
    hidden = _goblin(dm, db, p, at=(mine.x - 1, mine.y), hidden=True)
    p.fog = {"on": True, "shown": [f"{int(mine.x)},{int(mine.y)}"]}  # (only Cole's square shown)
    db.flush()
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post("/c/main/table/fight/begin")
    player.post(f"/c/main/table/tokens/{mine.id}/move", data={"x": str(mine.x), "y": str(mine.y + 4)})
    dm.post(f"/c/main/table/tokens/{mine.id}/move", data={"x": str(mine.x), "y": str(mine.y - 4)})
    said = json.dumps(db.get(Campaign, campaign.id).fight.get("reminders") or [])
    assert fogged.name not in said and hidden.name not in said
    assert player.get(f"/c/main/table/tokens/{fogged.id}").status_code == 404  # (under fog)
    assert dm.get(f"/c/main/table/tokens/{fogged.id}").status_code == 200
    p.fog = {"on": False, "shown": []}
    db.flush()
    assert player.get(f"/c/main/table/tokens/{fogged.id}").status_code == 200
    campaign.shown_place_id = None
    db.flush()
    assert player.get(f"/c/main/table/tokens/{fogged.id}").status_code == 404  # (a place the DM isn't showing)


def test_hiding_or_renaming_a_creature_mid_fight_reaches_the_fight(dm, player, db, table):
    campaign, p = table
    gob = _goblin(dm, db, p)
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post(f"/c/main/table/tokens/{gob.id}/hidden", data={"on": "1"})
    dm.post(f"/c/main/table/tokens/{gob.id}/rename", data={"name": "The Shadow"})
    x = next(x for x in db.get(Campaign, campaign.id).fight["order"] if x.get("token") == gob.id)
    assert x["hidden"] and x["name"] == "The Shadow"


def test_deleting_the_place_a_fight_runs_on_ends_the_fight(dm, db, table):
    campaign, p = table
    _goblin(dm, db, p)
    dm.post(f"/c/main/table/places/{p.id}/fight")
    assert db.get(Campaign, campaign.id).fight
    dm.post(f"/c/main/table/places/{p.id}/delete")
    assert db.get(Campaign, campaign.id).fight is None


def test_taking_the_active_token_off_keeps_whose_turn_it_is_right(dm, db, table):
    campaign, p = table
    a, b, c = (_goblin(dm, db, p, at=(i, 1)) for i in (1, 3, 5))
    dm.post(f"/c/main/table/places/{p.id}/fight")
    dm.post("/c/main/table/fight/begin")
    dm.post("/c/main/table/fight/next")
    f = db.get(Campaign, campaign.id).fight
    active = next(x for x in f["order"] if x["active"])
    dm.post(f"/c/main/table/tokens/{active['token']}/remove")
    f = db.get(Campaign, campaign.id).fight
    i = next(k for k, x in enumerate(f["order"]) if x["active"])
    assert f["turn"] == i + 1 and len(f["order"]) == 2


def test_a_creatures_reach_is_kept_on_its_token(dm, db, table):
    _, p = table
    gob = _goblin(dm, db, p)
    assert gob.monster["reach"] == 5


def test_a_map_too_large_to_read_is_refused_plainly(monkeypatch):
    """Nov 7 review: Pillow's own limit stays (a huge picture is refused, not decoded in memory)."""
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # (so a small picture is "too large" here)
    with pytest.raises(places.MapError, match="too large"):
        places.read_map(_png(), "map.png")
