"""Changing spells and Wild Shape forms (app/choosing.py; Brett, Nov 16: the wide window, D on
docs/mockups/changing-spells/): one window over Sheet's own list for cantrips, prepared or learned spells, a Wizard's
spellbook and known forms; a tab per class; why you're changing marks each rule Now or Not now; counts held as D&D Beyond
holds them; a swap past its 2024 rule warned about, never blocked (app.js); one Make, one sealed Undo."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import characters, choosing, ddb_bridge, ddb_fields, level_up
from app.models import BridgeIntent
from tests.roles import set_role
from tests.table_setup import char, plain_id

SPIDER, POLAR_BEAR = "4775844", "5195167"  # (two of Cole's six known forms, by D&D Beyond's monster id)
DIRE_WOLF = choosing._ids()["dire-wolf"]
GUIDANCE_ENTRY = 91000001  # (its entry on the Druid list: the saved sheet has no ids there, so the tests give one)


def spells_url(db, **q):
    cole = char(db, "Cole")
    return f"/characters/{cole.id}/spells/prepare" + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else "")


def forms_url(db):
    return f"/characters/{char(db, 'Cole').id}/wild-shape/forms"


def intents(db):
    return list(db.scalars(select(BridgeIntent).order_by(BridgeIntent.id)))


def give_ids(db, sheet):
    """The class's list as D&D Beyond sends it now, with each spell's entry id (askdnd's own read keeps it): Guidance to
    learn, Aid to prepare."""
    for sp in sheet["askdnd"]["availableSpells"]["2190878"]:
        if sp["definition"]["name"] == "Guidance":
            sp.update(id=GUIDANCE_ENTRY, entityTypeId=435869154)
        if sp["definition"]["name"] == "Aid":
            sp.update(id=21170801, entityTypeId=435869154)
    characters.refresh(db, char(db, "Cole"))


def row(lid, key):
    return f"{lid}|{key}"


# ------------------------------------------------------------------ the spells window


def test_coles_window_has_his_cantrips_and_prepared_spells_each_under_its_rule(player, db, sheet):
    give_ids(db, sheet)
    page = player.get(spells_url(db, why="rest")).text
    assert 'id="peek-title">Change spells' in page and "data-change" in page
    # a rule line per list: its count against the number, and the 2024 rule in few words
    assert 'data-rule="Druid:cantrips"' in page and "Swap 1 when you gain a Druid level" in page
    assert 'data-rule="Druid:spells"' in page and "Change any after a Long Rest" in page
    assert "<b data-rule-count>3</b> of 3" in page and "<b data-rule-count>10</b> of 10" in page
    # why you're changing: set from where it opened
    assert 'data-chg-occ="rest" aria-pressed="true"' in page and 'data-chg-occ="level-druid"' in page and 'data-chg-occ="look"' in page
    # each row's button beside its bookmark: Sheet's own list, every column
    assert 'data-pick="Druid:spells|spell:Healing Word"' in page and 'data-pick="Druid:cantrips|spell:Guidance"' in page
    assert page.count("data-pick-act") >= 10 and "Damage / Healing" in page
    assert 'title="Always prepared: not changed here">Always' in page  # (Starry Wisp, Cure Wounds: always, never a button)


def test_from_sheet_it_asks_why_first_and_from_a_rest_it_does_not(player, db, sheet):
    """Brett chose B (Nov 16, docs/mockups/why-changing/; his feedback 66: the reasons were hard to find): opened with no
    reason (Sheet's button), the window asks first, a tile per reason saying what it lets this character change; with
    one (the Long Rest window, a level-up card) it opens on the list, the reason a chip by the title."""
    give_ids(db, sheet)
    page = player.get(spells_url(db)).text
    assert "data-asking" in page and "data-chg-ask" in page and 'data-chg-main hidden' in page
    tiles = page.split("data-chg-ask")[1].split("data-chg-main")[0]
    assert tiles.count('class="choice-tile"') == 3  # (After a Long Rest, I gained a Druid level, Just looking)
    assert "Druid prepared spells: change any" in tiles and "Druid cantrips: swap 1" in tiles
    chip = lambda html: html.split("data-chg-reason ")[1].split(">")[0]
    assert chip(page).endswith(" hidden")  # (no reason yet: no chip)
    rest = player.get(spells_url(db, why="rest")).text
    assert "data-asking" not in rest and "data-chg-ask" not in rest and "data-chg-main hidden" not in rest
    assert not chip(rest).endswith(" hidden")  # (the chip shows; which reason, the switch under it says)
    assert 'data-chg-occ="rest" aria-pressed="true"' in rest  # (the reasons again, under the chip)


def test_what_a_reason_allows_is_said_from_each_lists_rule():
    from app.choosing import allows

    tabs = [{"cls": "Paladin", "lists": [{"label": "Paladin prepared spells", "may": "swap 1", "occ": ["rest"]}]},
            {"cls": "Sorcerer", "lists": [{"label": "Sorcerer cantrips", "may": "swap 1", "occ": ["level-sorcerer"]},
                                          {"label": "Sorcerer prepared spells", "may": "swap 1", "occ": ["level-sorcerer"]}]}]
    assert allows(tabs, "rest") == "Paladin prepared spells: swap 1"
    assert allows(tabs, "level-sorcerer") == "Sorcerer cantrips: swap 1 · Sorcerer prepared spells: swap 1"
    assert allows(tabs, "level-paladin").startswith("Nothing changes now")
    assert allows(tabs, "look").startswith("See the lists")


def test_one_make_sends_a_cantrip_and_a_spell_letting_go_first_and_undo_puts_both_back(player, db, sheet):
    give_ids(db, sheet)
    cole = char(db, "Cole")
    r = player.post(spells_url(db), json={"changes": [
        {"id": row("Druid:cantrips", "spell:Guidance"), "on": True}, {"id": row("Druid:cantrips", "spell:Mending"), "on": False},
        {"id": row("Druid:spells", "spell:Aid"), "on": True}, {"id": row("Druid:spells", "spell:Healing Word"), "on": False}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["text"].startswith("Cole: ") and "Guidance learned" in j["text"] and "Healing Word unprepared" in j["text"]
    made = [(i.kind, i.data["name"], i.data["value"]) for i in intents(db)]
    assert made[:2] == [("learn", "Mending", False), ("prepare", "Healing Word", False)]  # (letting go first: never more than the number)
    assert sorted(made[2:]) == [("learn", "Guidance", True), ("prepare", "Aid", True)]
    # shown at once, each on its way
    page = player.get(spells_url(db)).text
    assert "<b data-rule-count>3</b> of 3" in page
    # Undo: exactly what askdnd handed back
    u = player.post(j["undoUrl"], json={"undo": j["undo"]})
    assert u.status_code == 200, u.text
    sync = ddb_bridge.as_shown(db, cole, characters.character_summary(cole)).get("sync") or {}
    assert not [k for k in sync if k.startswith(("learn:", "prep:"))]  # (back as it was: nothing to send)
    forged = {**j["undo"], "made": j["undo"]["made"].replace("Guidance", "Fireball")}
    assert player.post(j["undoUrl"], json={"undo": forged}).status_code == 409


def test_counts_are_held_as_d_and_d_beyond_holds_them(player, db, sheet):
    """Brett, Nov 16: D&D Beyond won't prepare more than your number; askdnd won't either (the swap itself is never
    limited)."""
    give_ids(db, sheet)
    r = player.post(spells_url(db), json={"changes": [{"id": row("Druid:spells", "spell:Aid"), "on": True}]})
    assert r.status_code == 409 and r.json()["detail"] == "Druid prepared spells: 11 of 10; unprepare one first."
    r = player.post(spells_url(db), json={"changes": [{"id": row("Druid:cantrips", "spell:Guidance"), "on": True}]})
    assert r.status_code == 409 and "let one go first" in r.json()["detail"]
    assert not intents(db)
    # Two swaps where the rule says one: made (the warning is the window's; the DM rules)
    r = player.post(spells_url(db), json={"changes": [
        {"id": row("Druid:spells", "spell:Aid"), "on": True}, {"id": row("Druid:spells", "spell:Healing Word"), "on": False}]})
    assert r.status_code == 200


def test_what_it_cant_make_is_turned_away_or_left_as_it_is(player, db, sheet):
    give_ids(db, sheet)
    url = spells_url(db)
    for bad in ({}, {"changes": []}, {"changes": [{"id": "x", "on": True}]}, {"changes": [{"id": row("Druid:spells", "spell:Aid"), "on": "yes"}]}):
        assert player.post(url, json=bad).status_code == 409, bad
    # one gone from the list meanwhile, with one it can make: the one is made and the other said (review, Nov 2)
    r = player.post(url, json={"changes": [{"id": row("Druid:spells", "spell:Fireball"), "on": True},
                                           {"id": row("Druid:spells", "spell:Healing Word"), "on": False}]})
    assert r.status_code == 200 and r.json()["text"].endswith("; 1 can't be changed from askdnd now, left as it is")
    assert [i.data["name"] for i in intents(db)] == ["Healing Word"]
    r = player.post(url, json={"changes": [{"id": row("Druid:spells", "spell:Absorb Elements"), "on": True}]})  # (already prepared)
    assert r.json()["text"].startswith("Nothing to change")
    r = player.post(url, json={"changes": [{"id": row("Druid:spells", "spell:Cure Wounds"), "on": False}]})  # (always prepared)
    assert "left as it is" in r.json()["text"] and len(intents(db)) == 1


def test_your_notes_show_in_the_window(player, db, sheet):
    """Brett, 2026-11-02: notes matter when choosing what to prepare."""
    from app import picks

    cole = char(db, "Cole")
    picks.set_note(db, cole, "spell:Healing Word", "Bonus Action: keep for Trah")
    db.commit()
    assert "✎ Bonus Action: keep for Trah" in player.get(spells_url(db)).text


def test_every_place_opens_it(player, db, sheet):
    """Sheet › Spells, the Spell Book, the Long Rest window (for a Long Rest), the level-up card (for that class's level)."""
    cole = char(db, "Cole")
    spells_tab = player.get(f"/characters/{cole.id}").text.split('id="t-spells"')[1].split('id="t-forms"')[0]
    assert "data-change-spells" in spells_tab and "/spells/prepare?cls=Druid" in spells_tab
    assert "data-change-spells" in player.get(f"/characters/{cole.id}/spellbook").text
    rest = player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert "/spells/prepare?why=rest" in rest and "/wild-shape/forms?why=rest" in rest
    short = player.get(f"/characters/{cole.id}/rest?kind=short").text
    assert "data-change-spells" not in short and "data-change-forms" not in short
    cole.level_up = {"from": 7, "to": 8, "hp": 6, "pb": None, "features": [], "spells": [], "slots": [], "casting": ["Druid"]}
    db.commit()
    assert "/spells/prepare?cls=Druid&amp;why=level-druid" in player.get(f"/characters/{cole.id}/battle").text


def test_the_level_up_card_knows_which_class_gained_the_level():
    old = {"level": 7, "classes": [{"name": "Druid", "level": 5}, {"name": "Monk", "level": 2}], "spellbook": [{"class": "Druid"}]}
    new = {"level": 8, "classes": [{"name": "Druid", "level": 6}, {"name": "Monk", "level": 2}], "spellbook": [{"class": "Druid"}]}
    assert level_up.changes(old, new)["casting"] == ["Druid"]
    monk = {**new, "classes": [{"name": "Druid", "level": 5}, {"name": "Monk", "level": 3}]}
    assert level_up.changes(old, monk)["casting"] == []  # (a Monk level: no spells to change)
    assert level_up.merged({"from": 6, "hp": 5, "pb": None, "features": [], "spells": [], "slots": [], "casting": ["Druid"]},
                           {**level_up.changes(old, new), "casting": ["Wizard"]})["casting"] == ["Druid", "Wizard"]


def test_two_spellcasting_classes_get_a_tab_each(player, db, sheet):
    """Brett's pick, Nov 16: Big C's Paladin and Sorcerer (his saved sheet, at Cole's place at the table), each with its
    own lists and rules."""
    sheet.clear()
    sheet.update(json.loads((Path(__file__).parent / "fixtures" / "ddb" / "big_c.json").read_text())["data"])
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    tabs = choosing.spell_lists(characters.character_summary(cole))
    assert [t["cls"] for t in tabs] == ["Paladin", "Sorcerer"]
    pal, sor = tabs
    assert [(L["title"], L["when"], L["k"]) for L in pal["lists"]] == [("Prepared", "swap 1 after a Long Rest", "rest")]
    assert [(L["title"], L["when"]) for L in sor["lists"]] == [("Cantrips", "swap 1 when you gain a Sorcerer level"),
                                                              ("Prepared", "swap 1 when you gain a Sorcerer level")]
    assert {o[0] for o in choosing.occasions(tabs)} == {"rest", "level-paladin", "level-sorcerer", "look"}
    page = player.get(spells_url(db, cls="Sorcerer")).text
    assert 'role="tablist"' in page and 'data-chg-cls="Paladin" aria-selected="false"' in page and 'data-chg-cls="Sorcerer" aria-selected="true"' in page
    assert 'data-cls="Paladin"' in page and 'data-cls="Sorcerer"' in page  # (each row knows its class: the tab shows its own)


def test_who_learns_and_who_keeps_a_spellbook():
    """The 2024 rules for each kind of list (checked against the Player's Handbook, Nov 15)."""
    def sp(key, level, state, **kw):
        return {"key": key, "name": key, "level": level, "state": state, **kw}

    druid = {"class": "Druid", "cantrips_max": 3, "prepared_max": 10, "spells": [
        sp("Mending", 0, "known", learn={"entry": 1}), sp("Guidance", 0, "available", learn={"entry": 2}),
        sp("Shillelagh", 0, "always"), sp("Cure Wounds", 1, "prepared", prep={"entry": 3}), sp("Aid", 2, "available", prep={"entry": 4})]}
    wizard = {**druid, "class": "Wizard", "spellbook": True, "spells": druid["spells"] + [sp("Fly", 3, "available", learn={"entry": 5})]}
    warlock = {"class": "Warlock", "learns": True, "prepared_max": 3, "spells": [sp("Hex", 1, "known", learn={"entry": 6}), sp("Sleep", 1, "available", learn={"entry": 7})]}
    tabs = choosing.spell_lists({"spellbook": [druid, wizard, warlock]})
    by = {L["id"]: L for t in tabs for L in t["lists"]}
    assert by["Druid:cantrips"]["when"] == "swap 1 when you gain a Druid level" and by["Druid:spells"]["when"] == "change any after a Long Rest"
    assert [r["sp"]["name"] for r in by["Druid:cantrips"]["rows"] if r["on"] and not r["always"]] == ["Mending"]  # (Shillelagh is always: listed, not counted)
    assert by["Wizard:cantrips"]["when"] == "swap 1 after a Long Rest" and by["Wizard:book"]["add"] == "Copy in"
    assert [r["sp"]["name"] for r in by["Wizard:book"]["rows"]] == ["Fly"]
    assert by["Warlock:spells"]["kind"] == "learn" and by["Warlock:spells"]["when"] == "swap 1 when you gain a Warlock level"
    assert choosing.spell_lists({"spellbook": [{"class": "Druid", "spells": []}]}) == []


def test_only_the_characters_own_player(player, dm, db, sheet, monkeypatch):
    """As before (app/inventory.py `_guard`): the character's own player changes its sheet's choices."""
    from tests.table_setup import sign_in

    other = sign_in(monkeypatch, db, "someone@example.com")
    assert other.get(spells_url(db)).status_code == 404 and other.post(spells_url(db), json={"changes": []}).status_code == 404
    assert other.get(forms_url(db)).status_code == 404
    set_role(db, "dm@example.com")
    assert dm.get(spells_url(db)).status_code == 404
    assert player.get(f"/characters/{char(db, 'Trah').id}/wild-shape/forms").status_code == 404  # (no Wild Shape)


def test_a_closed_sheet_says_so_and_changes_nothing(player, db, sheet):
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.commit()
    page = player.get(forms_url(db)).text
    assert "D&amp;D Beyond sheet can" in page and "be reached:" in page and "data-chg-make" not in page
    assert player.post(forms_url(db), json={"changes": [{"id": f"Druid:forms|{SPIDER}", "on": False}]}).status_code == 409
    assert intents(db) == []


# ------------------------------------------------------------------ Wild Shape's known forms


def test_the_forms_window_lists_the_forms_you_know_and_the_ones_you_could_learn(player, db, sheet):
    page = player.get(forms_url(db)).text
    assert 'id="peek-title">Change Wild Shape forms' in page and "<b data-rule-count>6</b> of 6" in page and "Swap 1 after a Long Rest" in page
    assert f'data-pick="Druid:forms|{SPIDER}"' in page and f'data-pick="Druid:forms|{DIRE_WOLF}"' in page
    assert 'data-chg-occ="level-druid"' in page and "data-modal-url=\"/characters/" not in page.split("data-ls-rows")[1]  # (a row opens nothing: the window stays)
    assert "data-change-forms" in player.get(f"/characters/{char(db, 'Cole').id}").text.split('id="t-forms"')[1]  # (Sheet › Wild Shape)


@pytest.mark.parametrize(("rating_id", "label"), [(2, "1/8"), (3, "1/4"), (4, "1/2")], ids=plain_id)
def test_a_known_form_shows_its_challenge_rating_as_the_sheet_gives_it(player, db, sheet, rating_id, label):
    """ASKDND-V2-T (Nov 15, the live test on Levi's seat): a known form of CR 1/2 broke the window, its label read as a
    number."""
    for c in sheet["creatures"]:
        if str(c["definition"]["id"]) == SPIDER:
            c["definition"]["challengeRatingId"] = rating_id  # (D&D Beyond's ids: 2, 3, 4 are CR 1/8, 1/4, 1/2)
    characters.refresh(db, char(db, "Cole"))
    assert player.get(forms_url(db)).status_code == 200


def test_a_form_swap_and_its_undo(player, db, sheet):
    r = player.post(forms_url(db), json={"changes": [{"id": f"Druid:forms|{SPIDER}", "on": False}, {"id": f"Druid:forms|{DIRE_WOLF}", "on": True}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "Spider let go" in j["text"] and "Dire Wolf learned" in j["text"]
    assert [(i.data["field"], i.data["value"]) for i in intents(db)] == [(f"wildshape:{SPIDER}", 0), (f"wildshape:{DIRE_WOLF}", 1)]
    u = player.post(j["undoUrl"], json={"undo": j["undo"]})
    assert u.status_code == 200, u.text
    cole = char(db, "Cole")
    assert ddb_bridge.as_shown(db, cole, characters.character_summary(cole)).get("sync", {}).get(f"wildshape:{SPIDER}") is None
    # Six of six: a seventh isn't learned without letting one go (held, as D&D Beyond holds it)
    r = player.post(forms_url(db), json={"changes": [{"id": f"Druid:forms|{DIRE_WOLF}", "on": True}]})
    assert r.status_code == 409 and r.json()["detail"] == "Known forms: 7 of 6; let one go first."


def test_a_locked_beast_on_your_shortlist_says_why(player, db, sheet):
    """As Sheet › Wild Shape: a Beast shortlisted but not yet allowed is listed, with why where its button would be."""
    from app import picks

    cole = char(db, "Cole")
    picks.toggle(db, cole, "fav", "form:Elephant")  # (CR 4: above Cole's CR 2)
    db.commit()
    page = player.get(forms_url(db)).text
    assert 'data-label="Elephant"' in page
    elephant = page.split('data-label="Elephant"')[1].split('class="ls-row')[0]
    assert 'class="chg-lock"' in elephant and "data-pick-act" not in elephant


# ------------------------------------------------------------------ D&D Beyond's own requests


def test_d_and_d_beyonds_own_request_for_a_spell_learned():
    """Recorded on Levi's test seat, Nov 14: Manage Spells › Add Spells sends POST spell, and removing one DELETE spell,
    with the same body; the extension checks the class's list for the entry."""
    extra = {"spellId": 2618840, "entityTypeId": 435869154}
    body = {"characterId": 9, "characterClassId": 5, "spellId": 2618840, "id": 77, "entityTypeId": 435869154}
    learned, let_go = ddb_fields.write(9, "learn:5:77", True, {}, extra), ddb_fields.write(9, "learn:5:77", False, {}, extra)
    assert learned == {"method": "POST", "path": "/character/v5/spell", "body": body}
    assert let_go == {"method": "DELETE", "path": "/character/v5/spell", "body": body}
    raw = {"classSpells": [{"characterClassId": 5, "spells": [{"id": 77, "definition": {"name": "Starry Wisp"}}]}],
           "askdnd": {"availableSpells": {"1": [{"id": 78, "definition": {"name": "Guidance"}}]}}}
    assert ddb_fields.value(raw, "learn:5:77") is True and ddb_fields.value(raw, "learn:5:78") is False
    ddb_fields.put(raw, "learn:5:77", False)
    ddb_fields.put(raw, "learn:5:78", True)
    assert [s["definition"]["name"] for s in raw["classSpells"][0]["spells"]] == ["Guidance"]
    assert ddb_fields.name(raw, "learn:5:78") == "Guidance" and ddb_fields.text(raw, "learn:5:78", True) == "learned"


def test_d_and_d_beyonds_own_requests_for_a_known_form():
    """Recorded on Levi's test seat, Nov 14: learned with POST creature (group 13, the monster), let go of with DELETE
    creature (its id on the sheet); the extension checks it as the sum of the matching creatures' groups."""
    raw = {"creatures": [{"id": 7, "groupId": 13, "definition": {"id": 4775844, "name": "Spider"}},
                         {"id": 8, "groupId": 2, "definition": {"id": 4775844, "name": "Spider"}}]}
    learned, let_go = ddb_fields.write(1, f"wildshape:{DIRE_WOLF}", 1, raw), ddb_fields.write(1, "wildshape:4775844", 0, raw)
    assert learned == {"method": "POST", "path": "/character/v5/creature", "body": {"characterId": 1, "groupId": 13, "monsterId": int(DIRE_WOLF), "names": [None]}}
    assert let_go == {"method": "DELETE", "path": "/character/v5/creature", "body": {"characterId": 1, "id": 7}}
    assert ddb_fields.value(raw, "wildshape:4775844") == 1  # (the familiar Spider isn't a known form)
    read, frm, to = ddb_fields.wire("wildshape:4775844", raw, 1, 0)
    assert ddb_fields.pick(raw, read) == frm == 15 and to == 2  # (13 + 2, then the familiar's 2 alone)
    shown = {"creatures": list(raw["creatures"])}
    ddb_fields.put(shown, "wildshape:4775844", 0)
    assert [c["id"] for c in shown["creatures"]] == [8]
    assert ddb_fields.name(raw, "wildshape:4775844") == "Wild Shape form Spider" and ddb_fields.text(raw, "wildshape:1", 1) == "known"
