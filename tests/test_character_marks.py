"""A player's marks on their character: pins, the Shortlist, notes, Remind me and free-text reminders, and their
order. Only the character's player makes them; the DM never sees notes or reminders (CLAUDE.md › Privacy)."""

import json

import pytest
from sqlalchemy import select

from app import characters
from app.importer import import_bundle
from app.models import PlayerNote
from tests.table_setup import BUNDLE, COLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_only_the_player_stars_and_reminds(player, admin, db):
    """A standing rule: pins, the Shortlist and Remind me are the character's player's; nobody else changes them (an
    admin neither)."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert 'class="pick star' in page and 'class="pick remind' in page
    r = player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Heat Metal"})
    assert r.status_code == 200 and 'class="ico-pin"' in r.text and 'aria-pressed="true"' in r.text
    situ = cole.snapshot.summary["situational"][0]["key"]
    player.post(f"/characters/{cole.id}/pick", data={"kind": "remind", "ref": situ})
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert "Advantage on saving throws against being charmed (Fey Ancestry)" in battle  # Reminders
    assert "Heat Metal" in battle.split("Bonus action")[0]  # pinned: shown in the Action column
    assert "/all/action?add=1" in battle  # the column's + Add
    adding = player.get(f"/characters/{cole.id}/all/action?add=1").text
    assert "not pinned yet" in adding and "Heat Metal" not in adding  # leaves out what's pinned
    every = player.get(f"/characters/{cole.id}/all/action").text
    assert "Heat Metal" in every
    assert ">Cantrips <" in every and ">2nd-level spells <" in every and 'data-opt-kind="spell"' in every  # bucketed, with chips
    h = lambda label: every.index(f'<h3 class="divider">{label} ')  # noqa: E731
    assert h("Attacks") < h("Cantrips") < h("Items")
    assert admin.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Moonbeam"}).status_code == 403
    assert 'class="pick star"' not in admin.get(f"/characters/{cole.id}").text  # admins can't change them either
    player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Heat Metal"})  # toggles off
    assert "Heat Metal" not in player.get(f"/characters/{cole.id}/battle").text.split("Bonus action")[0]


def _marks(db, ch):
    from app.models import CharacterPick
    return {(p.kind, p.ref): p.note for p in db.scalars(select(CharacterPick).where(CharacterPick.character_id == ch.id))}


def test_pinning_also_shortlists_and_unpinning_leaves_the_shortlist(db):
    from app import picks

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    assert picks.toggle(db, cole, "star", "spell:Heat Metal", "Heat Metal") is True
    assert {("star", "spell:Heat Metal"), ("fav", "spell:Heat Metal")} <= set(_marks(db, cole))
    assert picks.toggle(db, cole, "star", "spell:Heat Metal") is False
    assert ("star", "spell:Heat Metal") not in _marks(db, cole) and ("fav", "spell:Heat Metal") in _marks(db, cole)


def test_one_note_per_thing_marked_or_not(db):
    from app import picks

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    picks.set_note(db, cole, "spell:Moonbeam", "  Opener vs. groups  ")  # no mark needed
    picks.toggle(db, cole, "remind", "spell:Moonbeam")
    picks.toggle(db, cole, "fav", "spell:Moonbeam")
    assert _marks(db, cole) == {("note", "spell:Moonbeam"): "Opener vs. groups", ("remind", "spell:Moonbeam"): "", ("fav", "spell:Moonbeam"): ""}
    picks.set_note(db, cole, "spell:Moonbeam", "")  # an empty note removes it
    assert ("note", "spell:Moonbeam") not in _marks(db, cole)


def test_dm_never_sees_reminders(dm, db):
    """A standing rule (CLAUDE.md › Privacy): character notes are visible to players but never the DM. Reminders are
    the player's, like notes."""
    from app.models import CharacterPick

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    db.add(CharacterPick(character_id=cole.id, kind="remind", ref="custom", label="SECRET REMINDER"))
    db.add(CharacterPick(character_id=cole.id, kind="star", ref="spell:Heat Metal"))
    db.flush()
    battle = dm.get(f"/characters/{cole.id}/battle").text
    assert "SECRET REMINDER" not in battle and "aren't shown to the DM" in battle
    assert "ico-pin" not in dm.get(f"/characters/{cole.id}/all/action").text


def test_no_character_notes_on_character_pages(dm, db):
    """Character notes are hidden from the DM (CLAUDE.md); these pages never show them. The
    D&D Beyond background and backstory are for the whole table, the DM included."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    db.add(PlayerNote(character_id=cole.id, kind="general", title="Mine", data={"body": "SECRET PLAYER NOTE"}))
    characters.refresh(db, cole)
    for path in ("/party", f"/characters/{cole.id}", f"/characters/{cole.id}/battle", f"/characters/{cole.id}/brief"):
        page = dm.get(path).text
        assert "SECRET PLAYER NOTE" not in page and "PRIVATE ALLY NOTE" not in page
    page = dm.get(f"/characters/{cole.id}").text
    assert 'data-tab="t-story">Background' in page and "Raised by wolves near Womford." in page and "Slow to trust." in page


def test_my_character_comes_first_and_reminders_can_be_removed(player, db):
    import_bundle(db, BUNDLE)
    trah, cole = char(db, "Trah"), char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, trah, "player@example.com")
    page = player.get(f"/characters/{cole.id}/battle").text
    pills = page.split('id="party-menu"')[1].split("</div>\n")[1]  # the menu bar's Party menu
    assert pills.index(">Trah<") < pills.index(">Big C<") < pills.index(">Cole<")  # mine, then by name
    owned_by(db, cole, "player@example.com")
    trah.owner_id = None
    situ = cole.snapshot.summary["situational"][0]["key"]
    player.post(f"/characters/{cole.id}/pick", data={"kind": "remind", "ref": situ})
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert 'class="forget-x"' in battle and 'hx-swap="delete"' in battle
    assert "#t-situ" not in battle  # links never jump to a tab


def test_drag_and_drop_order_is_saved_for_the_player_only(player, admin, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'data-sort-column="Action"' in page and "sortablejs@1.15.2" in page
    keys = ["spell:Thorn Whip", "attack:unarmed", "spell:Starry Wisp"]
    from app import picks
    for k in keys:  # Battle shows what the player pinned
        picks.toggle(db, cole, "star", k)
    r = player.post(f"/characters/{cole.id}/order", data={"column": "Action", "keys": keys})
    assert r.status_code == 204
    action = player.get(f"/characters/{cole.id}/battle").text.split('data-econ-col="action"')[1].split('data-econ-col="bonus"')[0]
    assert action.index("Thorn Whip") < action.index("Unarmed Strike") < action.index("Starry Wisp")
    assert admin.post(f"/characters/{cole.id}/order", data={"column": "Action", "keys": keys}).status_code == 403
    assert "data-sort-column" not in admin.get(f"/characters/{cole.id}/battle").text


def test_item_notes_are_stored_apart_and_everyone_sees_them(player, dm, db):
    """A standing rule (CLAUDE.md › Privacy, Brett 2026-10-17): players' item notes from D&D Beyond are visible to
    everyone, the DM included, and stored only in character_item_notes, never in fixtures or git."""
    from app.models import CharacterItemNote

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    flask = next(i for i in COLE["inventory"] if i["definition"]["name"] == "Flask")
    with_note = {**COLE, "characterValues": COLE["characterValues"] + [{"typeId": 9, "valueId": str(flask["id"]), "value": "Blessed by Myna"}]}
    characters.refresh(db, cole, fetch=lambda _id: with_note)
    assert "Blessed by Myna" not in json.dumps(cole.snapshot.raw) and "Blessed by Myna" not in json.dumps(cole.snapshot.summary)
    assert db.scalar(select(CharacterItemNote)).note == "Blessed by Myna"
    for who in (player, dm):  # the DM sees item notes too
        panel = who.get(f"/characters/{cole.id}/detail", params={"ref": f"item:{flask['id']}"}).text
        assert "Player's note" in panel and "Blessed by Myna" in panel
    characters.refresh(db, cole, fetch=lambda _id: COLE)  # note deleted on D&D Beyond
    assert db.scalar(select(CharacterItemNote)) is None


def test_a_pin_announces_itself_so_the_page_updates_without_a_refresh(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    r = player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Heat Metal", "marks": "star,fav,remind"})
    event = json.loads(r.headers["HX-Trigger"])["marksChanged"]
    assert event == {"character": cole.id, "kind": "star", "ref": "spell:Heat Metal", "on": True, "fav": True}  # pinning shortlists
    body = player.get(f"/characters/{cole.id}/battle", headers={"HX-Request": "true"}).text  # the page's own swap (app.js showInPlace)
    assert "Heat Metal" in body.split('data-econ-col="action"')[1].split('data-econ-col="bonus"')[0]


def test_a_note_announces_itself_so_the_rows_update_without_a_refresh(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    r = player.post(f"/characters/{cole.id}/pick/note", data={"ref": "spell:Moonbeam", "note": "  Opener vs. groups "})
    assert json.loads(r.headers["HX-Trigger"])["noteChanged"] == {"character": cole.id, "ref": "spell:Moonbeam", "note": "Opener vs. groups"}
    assert "data-ls-notes" in player.get(f"/characters/{cole.id}/plan").text  # Plan's spell list offers "Full notes"
    r = player.post(f"/characters/{cole.id}/pick/note", data={"ref": "spell:Moonbeam", "note": ""})
    assert json.loads(r.headers["HX-Trigger"])["noteChanged"]["note"] == ""  # cleared: the line goes away


def test_free_text_reminders_are_the_players_and_show_on_battle(player, admin, dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    r = player.post(f"/characters/{cole.id}/reminders", data={"text": "  Ask the DM   about the map "})
    assert r.status_code == 204 and json.loads(r.headers["HX-Trigger"])["marksChanged"]["kind"] == "remind"
    assert "Ask the DM about the map" in player.get(f"/characters/{cole.id}/battle").text
    assert "Ask the DM about the map" in player.get(f"/characters/{cole.id}/plan").text
    assert player.post(f"/characters/{cole.id}/reminders", data={"text": "   "}).status_code == 400
    assert admin.post(f"/characters/{cole.id}/reminders", data={"text": "x"}).status_code == 403
    assert "Ask the DM" not in dm.get(f"/characters/{cole.id}/battle").text
