"""Your spells (app/spells_known.py; roadmap step 5, Brett's picks 3–4, Nov 13): a cantrip swapped, a spell learned, a
Wizard's spellbook, each a spell on the class's list on D&D Beyond or not, with D&D Beyond's own Manage Spells request
(POST and DELETE spell, recorded on Levi's test seat, Nov 14); the rule said, never enforced; Undo puts it back."""

from sqlalchemy import select

from app import characters, ddb_bridge, ddb_fields, spells_known
from app.models import BridgeIntent
from tests.table_setup import char

DRUID = 184968818  # (Cole's Druid class on his sheet)
GUIDANCE_ENTRY = 91000001  # (its entry on the Druid list: the saved sheet has no ids there, so the test gives one)


def url(db, **q):
    cole = char(db, "Cole")
    return f"/characters/{cole.id}/spells/learn" + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else "")


def give_ids(db, sheet):
    """The class's list as D&D Beyond sends it now, with each spell's entry id (askdnd's own read keeps it)."""
    for sp in sheet["askdnd"]["availableSpells"]["2190878"]:
        if sp["definition"]["name"] == "Guidance":
            sp.update(id=GUIDANCE_ENTRY, entityTypeId=435869154)
    characters.refresh(db, char(db, "Cole"))


def mending(sheet) -> str:
    return str(next(s["id"] for cs in sheet["classSpells"] for s in cs["spells"] if s["definition"]["name"] == "Mending"))


def intents(db):
    return [(i.kind, i.data["entry"], i.data["value"]) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]


def test_a_druid_swaps_a_cantrip(player, db, sheet):
    give_ids(db, sheet)
    page = player.get(url(db)).text
    assert "Your Druid cantrips" in page and "gain a Druid level" in page
    assert f'name="out" value="{mending(sheet)}"' in page and f'<option value="{GUIDANCE_ENTRY}"' in page
    r = player.post(url(db, cls="Druid", kind="cantrips"), data={"out": mending(sheet), "in": str(GUIDANCE_ENTRY)})
    assert r.status_code == 200, r.text
    assert intents(db) == [("learn", int(mending(sheet)), False), ("learn", GUIDANCE_ENTRY, True)]
    shown = player.get(url(db)).text  # (on its way: shown at once)
    assert f'name="out" value="{GUIDANCE_ENTRY}"' in shown and f'name="out" value="{mending(sheet)}"' not in shown
    j = r.json()
    assert player.post(j["undoUrl"], data=j["undo"]).status_code == 200
    cole = char(db, "Cole")
    sync = ddb_bridge.as_shown(db, cole, characters.character_summary(cole)).get("sync") or {}
    assert not [k for k in sync if k.startswith("learn:")]  # (back as it was: nothing to send)
    assert player.post(j["undoUrl"], data={**j["undo"], "in": str(GUIDANCE_ENTRY)}).status_code == 409  # (a changed Undo)


def test_what_cant_be_learned_here_is_refused(player, db, sheet):
    give_ids(db, sheet)
    for bad in ({}, {"out": "1"}, {"in": mending(sheet)}, {"out": mending(sheet), "in": mending(sheet)}):
        assert player.post(url(db, cls="Druid", kind="cantrips"), data=bad).status_code == 409, bad
    assert player.post(url(db, cls="Druid", kind="spells"), data={"in": "424242"}).status_code == 409  # (a Druid prepares: cantrips only)
    assert player.post(url(db), data={"in": str(GUIDANCE_ENTRY)}).status_code == 200  # (no kind named: the window's own, cantrips)
    assert [i[1] for i in intents(db)] == [GUIDANCE_ENTRY]


def test_sheet_offers_it_and_only_where_there_is_something_to_change(player, db, sheet):
    give_ids(db, sheet)
    cole = char(db, "Cole")
    spells_tab = player.get(f"/characters/{cole.id}").text.split('id="t-spells"')[1].split('id="t-forms"')[0]
    assert "data-learn-spells" in spells_tab and "Swap a cantrip" in spells_tab


def test_only_the_characters_own_player(db, sheet, monkeypatch):
    from tests.table_setup import sign_in

    other = sign_in(monkeypatch, db, "someone@example.com")
    assert other.get(url(db)).status_code == 404 and other.post(url(db), data={"in": "1"}).status_code == 404


def test_who_learns_and_who_keeps_a_spellbook():
    druid = {"class": "Druid", "learns": False, "spellbook": False, "spells": [
        {"key": "a", "name": "Mending", "level": 0, "state": "known", "learn": {"entry": 1}},
        {"key": "b", "name": "Guidance", "level": 0, "state": "available", "learn": {"entry": 2}},
        {"key": "c", "name": "Cure Wounds", "level": 1, "state": "prepared", "learn": {"entry": 3}},
        {"key": "d", "name": "Shillelagh", "level": 0, "state": "always", "learn": {"entry": 4}}]}
    warlock = {**druid, "class": "Warlock", "learns": True}
    wizard = {**druid, "class": "Wizard", "spellbook": True}
    assert [b["kinds"] for b in spells_known.books({"spellbook": [druid, warlock, wizard]})] == [["cantrips"], ["cantrips", "spells"], ["cantrips", "spells"]]
    have, can = spells_known.lists(druid, "cantrips")
    assert [r["name"] for r in have] == ["Mending"] and [r["name"] for r in can] == ["Guidance"]  # (Shillelagh is always: not swapped)
    assert [r["name"] for r in spells_known.lists(warlock, "spells")[0]] == ["Cure Wounds"]
    assert "Long Rest" in spells_known._rule(wizard, "cantrips") and "Warlock level" in spells_known._rule(warlock, "spells")
    assert spells_known.books({"spellbook": [{**druid, "spells": []}]}) == []


def test_d_and_d_beyonds_own_request_for_a_spell_learned():
    """Recorded on Levi's test seat, Nov 14: Manage Spells › Add Spells sends POST spell, and removing one DELETE spell,
    with the same body; the extension checks the class's list for the entry."""
    extra = {"spellId": 2618840, "entityTypeId": 435869154}
    body = {"characterId": 9, "characterClassId": 5, "spellId": 2618840, "id": 77, "entityTypeId": 435869154}
    assert ddb_fields.write(9, "learn:5:77", True, {}, extra) == {"method": "POST", "path": "/character/v5/spell", "body": body}
    assert ddb_fields.write(9, "learn:5:77", False, {}, extra) == {"method": "DELETE", "path": "/character/v5/spell", "body": body}
    raw = {"classSpells": [{"characterClassId": 5, "spells": [{"id": 77, "definition": {"name": "Starry Wisp"}}]}],
           "askdnd": {"availableSpells": {"1": [{"id": 78, "definition": {"name": "Guidance"}}]}}}
    assert ddb_fields.value(raw, "learn:5:77") is True and ddb_fields.value(raw, "learn:5:78") is False
    ddb_fields.put(raw, "learn:5:77", False)
    ddb_fields.put(raw, "learn:5:78", True)
    assert [s["definition"]["name"] for s in raw["classSpells"][0]["spells"]] == ["Guidance"]
    assert ddb_fields.name(raw, "learn:5:78") == "Guidance" and ddb_fields.text(raw, "learn:5:78", True) == "learned"
