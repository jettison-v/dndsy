"""Player notes (app/player_notes.py): only the character's player writes them, every
player reads them, the DM never sees them; each kind keeps its structure."""

import json

import pytest
from sqlalchemy import select
from starlette.datastructures import FormData

from app import characters
from app import player_notes as pn
from app.importer import import_bundle
from app.models import PlayerNote
from tests.test_characters import BUNDLE, admin, char, dm, no_network, owned_by, player  # noqa: F401


def form(**fields) -> FormData:
    items = []
    for k, v in fields.items():
        items += [(k, x) for x in v] if isinstance(v, list) else [(k, v)]
    return FormData(items)


def test_combos_keep_turns_in_order_and_drop_empty_ones():
    title, status, data = pn.parse("combo", form(
        title="Grapple then Moonbeam", when="Big melee enemy",
        turn_label=["Setup", "", ""], turn_action=["Moonbeam", "Rend twice", ""], turn_bonus=["Wild Shape", "", ""],
        turn_reaction=["", "", ""], turn_move=["", "", ""], turn_notes=["", "", ""]))
    assert title == "Grapple then Moonbeam" and status == ""
    assert [t["label"] for t in data["turns"]] == ["Setup", "Turn 2"]  # the empty third turn is dropped
    assert data["turns"][0]["steps"] == [{"kind": "action", "text": "Moonbeam"}, {"kind": "bonus", "text": "Wild Shape"}]  # older form
    assert data["when"] == "Big melee enemy"


def test_combo_steps_keep_the_players_order():
    """A Bonus action can come before the Action (Brett): steps stay in page order, per turn."""
    _, _, data = pn.parse("combo", FormData([
        ("title", "Bear then beam"),
        ("turn_label", "Setup"), ("step_kind", "bonus"), ("step_text", "Wild Shape into Polar Bear"),
        ("step_kind", "move"), ("step_text", "Close to 5 ft"), ("step_kind", "action"), ("step_text", "Rend twice"),
        ("turn_notes", "Only if it's in reach"),
        ("turn_label", ""), ("step_kind", "action"), ("step_text", ""),  # an empty turn is dropped
        ("turn_label", "Payoff"), ("step_kind", "action"), ("step_text", "Moonbeam"), ("turn_notes", ""),
    ]))
    assert [t["label"] for t in data["turns"]] == ["Setup", "Payoff"]
    assert [s["kind"] for s in data["turns"][0]["steps"]] == ["bonus", "move", "action"]
    assert data["turns"][0]["notes"] == "Only if it's in reach"
    assert pn.combo_steps({"action": "Rend", "bonus": "Wild Shape"}) == [{"kind": "action", "text": "Rend"}, {"kind": "bonus", "text": "Wild Shape"}]


def test_leveling_quest_and_general_structures():
    _, _, lv = pn.parse("leveling", form(step_level=["7", ""], step_class=["Druid", ""], step_take=["Elemental Fury", ""],
                                         step_why=["Primal Strike in forms", ""], step_done=["", ""]))
    assert lv["steps"] == [{"level": "7", "class": "Druid", "take": "Elemental Fury", "why": "Primal Strike in forms", "done": False}]
    title, status, q = pn.parse("quest", form(goal="Find my father", step_text=["Ask in Oakhurst", ""], step_done=["1", ""], status="bogus"))
    assert title == "Untitled quest" and status == "open" and q["steps"] == [{"text": "Ask in Oakhurst", "done": True}]
    _, _, g = pn.parse("general", form(body="**Remember** the owl"))
    assert g == {"body": "**Remember** the owl"}
    with pytest.raises(ValueError):
        pn.parse("diary", form())


@pytest.fixture
def cole(db, player):
    import_bundle(db, BUNDLE)
    c = char(db, "Cole")
    characters.refresh(db, c)
    owned_by(db, c, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    return c


def test_only_the_player_writes_and_the_dm_never_sees(db, cole, player, dm, admin):
    url = f"/characters/{cole.id}"
    r = player.post(f"{url}/notes", data={"kind": "combo", "title": "Bear and beam", "turn_label": "Setup",
                                           "turn_action": "Cast Moonbeam", "turn_bonus": "Wild Shape into Polar Bear",
                                           "turn_reaction": "", "turn_move": "", "turn_notes": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"{url}/plan"  # notes live on Plan
    note = db.scalar(select(PlayerNote))
    page = player.get(f"{url}/plan").text
    assert "Bear and beam" in page and 'data-modal-url="/characters/%d/notes/%d" data-modal-size="large"' % (cole.id, note.id) in page  # combos open large
    panel = player.get(f"{url}/notes/{note.id}").text  # the full note in the side panel
    assert 'data-modal-url="/characters/%d/form?name=Polar%%20Bear"' % cole.id in panel and "/edit" in panel  # forms link
    assert "/edit" not in admin.get(f"{url}/notes/{note.id}").text and dm.get(f"{url}/notes/{note.id}").status_code == 403
    assert "Bear and beam" in player.get(f"{url}/battle").text  # combos show on Battle
    assert "Bear and beam" not in player.get(url).text  # not on Sheet
    assert "Bear and beam" in admin.get(f"{url}/plan").text and "/notes/new" not in admin.get(f"{url}/plan").text  # others read, can't write
    assert admin.post(f"{url}/notes", data={"kind": "general", "body": "x"}).status_code == 403
    assert "Bear and beam" not in dm.get(url).text and "Bear and beam" not in dm.get(f"{url}/battle").text
    assert dm.get(f"{url}/plan", follow_redirects=False).headers["location"] == url  # the DM has no Plan
    r = player.post(f"{url}/notes", data={"kind": "general", "body": "From Play"}, headers={"referer": f"http://testserver{url}/battle"},
                    follow_redirects=False)
    assert r.headers["location"] == f"{url}/battle"  # added from Play's Battle combos: back to Play
    db.delete(db.scalars(select(PlayerNote).order_by(PlayerNote.id.desc())).first())
    assert dm.get(f"{url}/notes/{note.id}/edit").status_code == 403
    player.post(f"{url}/notes/{note.id}/delete")
    assert db.scalar(select(PlayerNote)) is None


def test_import_loads_notes_and_wild_shape_shortlist_notes_once(db, cole):
    from app.models import CharacterPick

    bundle = {"campaign": {"slug": "main", "name": "Main"},
              "player_notes": [{"character": "Cole", "kind": "quest", "title": "Save our sons", "data": {"goal": "Bring them back", "steps": []}}],
              "form_notes": [{"character": "Cole", "form": "Polar Bear", "note": "When: rarely"}]}
    import_bundle(db, bundle)
    import_bundle(db, bundle)  # again: updated, not duplicated
    notes = list(db.scalars(select(PlayerNote)))
    assert len(notes) == 1 and notes[0].status == "open" and notes[0].data["goal"] == "Bring them back"
    assert db.scalar(select(CharacterPick).where(CharacterPick.ref == "form:Polar Bear", CharacterPick.kind == "fav"))
    note = db.scalar(select(CharacterPick).where(CharacterPick.ref == "form:Polar Bear", CharacterPick.kind == "note"))
    assert note.note == "When: rarely"
    with pytest.raises(ValueError):
        import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "player_notes": [{"character": "Nobody", "kind": "general", "title": "x", "data": {}}]})


def test_saving_from_the_modal_updates_in_place_and_notes_can_be_reordered(db, cole, player, admin):
    url = f"/characters/{cole.id}"
    hx = {"HX-Request": "true"}
    for title in ("First", "Second"):
        r = player.post(f"{url}/notes", data={"kind": "general", "title": title, "body": "x"}, headers=hx)
        assert r.status_code == 204 and json.loads(r.headers["HX-Trigger"])["notesChanged"] == {"character": cole.id, "kind": "general"}
    first, second = db.scalars(select(PlayerNote).order_by(PlayerNote.position)).all()
    assert player.post(f"{url}/notes/order", data={"column": "general", "keys": [str(second.id), str(first.id)]}).status_code == 204
    db.refresh(first), db.refresh(second)
    assert second.position < first.position
    assert admin.post(f"{url}/notes/order", data={"column": "general", "keys": [str(first.id)]}).status_code == 403
    plan = player.get(f"{url}/plan").text
    assert plan.index(">Second<") < plan.index(">First<")
    r = player.post(f"{url}/notes/{first.id}/delete", headers=hx)
    assert r.status_code == 204 and "Deleted: First" in r.headers["HX-Trigger"]
