"""Magic items on Battle (app/conditions.py): item actions, conditions and their Advantage."""

import pytest
import json

from app import characters, live
from app import conditions as cd
from app.importer import import_bundle
from tests.table_setup import BUNDLE, char, owned_by
from tests.test_suggestions import HX

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)

RING = {"key": "item:9", "name": "Ring of Invisibility", "base_name": "Ring of Invisibility", "magic": True, "equipped": True,
        "attunement": "attuned", "battle": False, "summary": "While wearing this ring, you can take a Magic action to…"}


def test_the_ring_gives_two_actions_only_while_attuned():
    names = [(a["cost"], a["name"], a.get("starts"), a.get("ends")) for a in cd.item_actions(RING)]
    assert names == [("Action", "Turn Invisible", "Invisible", None), ("Bonus action", "Become visible", None, "Invisible")]
    assert cd.item_actions({**RING, "attunement": "required"}) == []  # needs attunement first
    cloak = {**RING, "key": "item:3", "name": "Cloak of Billowing", "base_name": "Cloak of Billowing",
             "attunement": None, "summary": "As a Bonus Action, you make it billow."}
    assert [(a["cost"], a["name"]) for a in cd.item_actions(cloak)] == [("Bonus action", "Use: Cloak of Billowing")]


def test_every_condition_lists_what_it_changes_in_the_roll_window():
    fx = cd.roll_effects([{"name": "Invisible", "source": "Ring of Invisibility"}, {"name": "Poisoned"},
                          {"name": "Restrained"}, {"name": "Exhaustion", "level": 2}, {"name": "Stunned"}])
    assert {"mode": "adv", "text": "Invisible (Ring of Invisibility): Advantage on your attack rolls, unless the target can see you"} in fx["attack"]
    assert {"mode": "dis", "text": "Poisoned: Disadvantage on ability checks"} in fx["check"]
    assert fx["save:dex"][0]["mode"] == "dis" and fx["save:str"][0]["text"].startswith("Stunned")  # auto-fail, as a note
    assert fx["d20"] == [{"mode": "note", "text": "Exhaustion 2: −4 to this roll (−2 per level)"}]
    assert fx["initiative"][0]["mode"] == "adv" and any(e["mode"] == "dis" for e in fx["initiative"])  # Invisible vs Incapacitated
    assert set(cd.CONDITIONS) >= {"Blinded", "Charmed", "Frightened", "Grappled", "Prone", "Unconscious"} and all(cd.rules_text(n) for n in cd.KNOWN)


def test_conditions_are_added_once_and_exhaustion_has_a_level():
    assert cd.add([], "Invisible", "Ring") == [{"name": "Invisible", "source": "Ring"}]
    assert cd.add([{"name": "Exhaustion", "source": "", "level": 1}], "Exhaustion", level=9) == [{"name": "Exhaustion", "source": "", "level": 6}]
    assert cd.end([{"name": "Invisible"}], "Invisible") == []


def test_potions_offer_a_track_button_for_what_they_start():
    growth = {"key": "item:5", "name": "Potion of Growth", "base_name": "Potion of Growth", "magic": True, "battle": True}
    assert cd.on_use(growth)["starts"] == "Enlarged" and cd.item_actions(growth) == []  # stays a "Use an item" option


def test_only_the_player_turns_invisible_and_everyone_sees_it(player, admin, dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    url = f"/characters/{cole.id}"
    assert admin.post(f"{url}/conditions", data={"name": "Invisible"}).status_code == 403
    assert player.post(f"{url}/conditions", data={"name": "Hasted"}).status_code == 400  # not one askdnd tracks
    r = player.post(f"{url}/conditions", data={"name": "Invisible", "source": "Ring of Invisibility"}, headers=HX)
    assert r.status_code == 200 and 'class="cond-pill"' in r.text
    adv = json.loads(r.text.split("data-cond-adv='")[1].split("'")[0])
    assert adv["attack"][0]["text"].startswith("Invisible (Ring of Invisibility)")
    assert "cond-pill" in dm.get(f"{url}/battle").text  # the DM sees it too
    player.post(f"{url}/conditions/end", data={"name": "Invisible"}, headers=HX)
    db.refresh(cole)
    assert not cole.conditions


def test_the_edge_takes_the_newest_three_conditions_own_colours():
    """Brett, 2026-10-28 (docs/mockups/conditions-on-battle.html): the page's edge shows each of the newest three in its
    own colour, so several conditions show as several colours; Blinded or Unconscious also darken the page's edges."""
    edge = lambda *names: cd.edge([{"name": n} for n in names])  # noqa: E731
    assert edge() == [] and edge("Prone") == ["prone"]
    assert edge("Grappled", "Prone", "Poisoned", "Water Breathing") == ["water-breathing", "poisoned", "prone"]  # newest first
    assert cd.darkens([{"name": "Unconscious"}]) and not cd.darkens([{"name": "Prone"}])


def test_d_and_d_beyonds_conditions_show_with_askdnds_own():
    """Brett, 2026-10-28 (synced both ways): D&D Beyond holds the 15 conditions and Exhaustion. Where the bridge works,
    those are D&D Beyond's (askdnd adds where one came from, and keeps the item effects D&D Beyond doesn't have);
    elsewhere askdnd shows what's ticked there along with its own."""
    sheet = cd.from_sheet({"conditions": [{"id": 11, "level": None}, {"id": 4, "level": 2}, {"id": 99}, "x"]})
    assert sheet == [{"name": "Poisoned"}, {"name": "Exhaustion", "level": 2}]
    own = [{"name": "Invisible", "source": "Ring of Invisibility"}, {"name": "Poisoned", "source": "Giant Spider"},
           {"name": "Exhaustion", "source": "", "level": 1}, {"name": "Enlarged", "source": "Potion of Growth"}]
    synced = cd.shown(own, sheet, synced=True)  # Invisible ended on D&D Beyond (or isn't made yet): left out
    assert [(c["name"], c.get("level"), c.get("source"), c["on_ddb"]) for c in synced] == [
        ("Poisoned", None, "Giant Spider", True), ("Exhaustion", 2, "", True), ("Enlarged", None, "Potion of Growth", False)]
    assert [c["name"] for c in cd.shown(own, sheet, synced=False)] == ["Poisoned", "Exhaustion", "Invisible", "Enlarged"]  # D&D Beyond's first
    assert cd.shown(own, None, synced=True) == own  # a copy read before askdnd kept D&D Beyond's: askdnd's own


def test_a_condition_shows_on_battle_party_and_your_menu_bar_button(player, dm, db):
    """Everyone at the table sees a character's conditions (as on the pills): the DM's Battle for Cole has the edge and
    a badge per condition after his name with what it does (on Sheet too), the Party card its icons, and the player's own
    menu bar button a dot each."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    for n, lv in (("Poisoned", 0), ("Prone", 0), ("Exhaustion", 2)):
        player.post(f"/characters/{cole.id}/conditions", data={"name": n, "level": lv or 1}, headers=HX)
    page = dm.get(f"/characters/{cole.id}/battle").text
    assert "--edge: var(--cond-exhaustion), var(--cond-prone), var(--cond-poisoned), var(--cond-exhaustion)" in page
    for mode in ("/battle", ""):  # Brett, 2026-10-29: after the name on every character page
        badges = dm.get(f"/characters/{cole.id}{mode}").text.split('class="char-name"')[1].split('<div class="muted char-sub">')[0]
        assert [x.split('"')[0] for x in badges.split('data-name="')[1:]] == ["Poisoned", "Prone", "Exhaustion"]  # in the order they started
        assert 'class="cond-lv">2<' in badges and "Disadvantage on attack rolls" in badges
    party = dm.get("/c/main/party").text
    assert 'style="--h: var(--cond-exhaustion)" data-conds' in party and 'aria-label="Exhaustion 2"' in party.split('class="cond-badges"')[1]
    dots = player.get("/c/main/").text.split("data-cond-dots")[1].split("</span>")[0]
    assert 'title="Poisoned, Prone, Exhaustion"' in dots and dots.count("<i data-cond=") == 3
    player.post(f"/characters/{cole.id}/conditions", data={"name": "Invisible"}, headers=HX)
    assert 'id="battle-body" class="cond-ghost"' in dm.get(f"/characters/{cole.id}/battle").text  # the portrait fades


def dots(db, character):
    return next(r for r in live.rows_from(db) if r["id"] == character.id)["conditions"]


def test_with_the_bridge_a_condition_is_made_on_d_and_d_beyond_and_shows_at_once_marked_until_its_there(player, db, sheet):
    """A standing rule (Brett, 2026-10-28: changes only while the sheet can be reached; conditions synced both ways;
    2026-10-29: the page shows a change at once, marked until D&D Beyond has it): starting or ending one D&D Beyond
    holds becomes a change for the sheet, sent at once from whatever page it's made on, shown as made with its quiet mark
    (on its way, ending, or given up to make on the sheet; no words but the hover title) until D&D Beyond has it."""
    from sqlalchemy import select

    from app.models import BridgeIntent

    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/conditions", data={"name": "Poisoned", "source": "Giant Spider"}, headers=HX)
    assert r.status_code == 200 and json.loads(r.headers["HX-Trigger"])["bridgeDeliver"]["ddbId"] == "75423618"  # sent now, from Battle
    it = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id)).all()[-1]
    assert (it.kind, it.data) == ("set", {"field": "condition:11", "value": True})
    assert 'data-sync="on"' in r.text.split('class="cond-bar"')[1]  # shown already, on its way
    assert "Poisoned" in dots(db, cole)  # the menu bar's too (review, 2026-10-29)
    badge = player.get(f"/characters/{cole.id}/battle").text.split('class="cond-badges"')[1]
    assert 'data-name="Poisoned" data-mark="' in badge and 'data-sync="on"' in badge
    sheet["conditions"] = [{"id": 11, "level": None}, {"id": 4, "level": 3}]  # made (and Exhaustion 3 ticked there)
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'data-name="Poisoned"' in page and "Giant Spider" in page and 'class="cond-lv">3<' in page and "data-sync" not in page
    r = player.post(f"/characters/{cole.id}/conditions/end", data={"name": "Exhaustion"}, headers=HX)
    it = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id).order_by(BridgeIntent.id)).all()[-1]
    assert it.data == {"field": "exhaustion", "value": 0}
    assert 'data-sync="ending"' in r.text and "Ending…" not in r.text and "var(--cond-exhaustion)" not in r.text  # no words; off the edge already
    assert "Exhaustion" not in dots(db, cole)
    it.state = "not_yet"  # it gave up: to make on the sheet
    db.commit()
    assert "Exhaustion" in dots(db, cole)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'data-sync="failed" title="D&amp;D Beyond didn&#39;t take this: make it there"' in page  # said only on hover
    cole.sheet_heard_at = None  # the sheet can't be reached: nothing is taken
    db.commit()
    assert player.post(f"/characters/{cole.id}/conditions", data={"name": "Prone"}, headers=HX).status_code == 409
    assert player.post(f"/characters/{cole.id}/conditions", data={"name": "Enlarged"}, headers=HX).status_code == 200  # askdnd's own


def test_a_condition_ending_keeps_its_place_until_its_gone(player, db, sheet):
    """Brett, 2026-10-29: with three conditions, ending the first mustn't move it to the end."""
    cole = char(db, "Cole")
    sheet["conditions"] = [{"id": 11, "level": None}, {"id": 12, "level": None}, {"id": 2, "level": None}]  # Poisoned, Prone, Charmed
    characters.refresh(db, cole)
    r = player.post(f"/characters/{cole.id}/conditions/end", data={"name": "Poisoned"}, headers=HX)
    pills = [x.split('"')[0] for x in r.text.split('class="cond-bar"')[1].split('data-mark="')[1:] if ":cond:" in x.split('"')[0]]
    assert pills == [f"{cole.id}:cond:Poisoned", f"{cole.id}:cond:Prone", f"{cole.id}:cond:Charmed"]
    assert r.text.split(f'data-mark="{cole.id}:cond:Poisoned"')[1].startswith(' data-sync="ending"')


def test_a_hit_on_its_way_shows_on_battle_and_party_at_once(player, dm, db, sheet):
    """Brett, 2026-10-29: the numbers change at once; the Hit points tile is marked until D&D Beyond has the hit."""
    cole = char(db, "Cole")
    r = player.post(f"/bridge/hp/{cole.id}", data={"amount": "-10"})
    assert json.loads(r.headers["HX-Trigger"])["bridgeDeliver"]["ddbId"] == "75423618"
    tile = dm.get(f"/characters/{cole.id}/battle").text.split(f'data-mark="{cole.id}:hp"')[1][:400]
    assert 'data-sync="on"' in tile and "<b>27</b>" in tile  # 37 − 10, before D&D Beyond has it
    assert 'data-sync="on"' in dm.get("/c/main/party").text.split(f'data-mark="{cole.id}:hp"')[1][:80]
    from sqlalchemy import select

    from app.models import BridgeIntent

    sheet["removedHitPoints"] = 24  # made, and the read-back counted it (ddb_bridge.delivered)
    characters.refresh(db, cole)
    db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id)).one().state = "live"
    db.commit()
    tile = dm.get(f"/characters/{cole.id}/battle").text.split(f'data-mark="{cole.id}:hp"')[1][:400]
    assert "data-sync" not in tile and "<b>27</b>" in tile


def test_without_the_bridge_a_condition_ticked_on_d_and_d_beyond_shows_and_ends_there(player, db, monkeypatch):
    import copy

    from tests.table_setup import COLE

    data = {**copy.deepcopy(COLE), "conditions": [{"id": 1, "level": None}]}
    monkeypatch.setattr(characters, "FETCH", lambda _id: copy.deepcopy(data))
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    assert 'data-name="Blinded"' in player.get(f"/characters/{cole.id}/battle").text and "cond-halo dark" in player.get(f"/characters/{cole.id}/battle").text
    r = player.post(f"/characters/{cole.id}/conditions/end", data={"name": "Blinded"}, headers=HX)
    assert r.status_code == 409 and "end it there" in r.text


def test_exhaustion_and_speed_0_change_speed_with_the_working():
    """2024 rules (SRD 5.2.1 Rules Glossary): each level of Exhaustion reduces Speed by 5 feet; Grappled, Paralyzed,
    Petrified, Restrained and Unconscious make it 0. Speed's panel sums the parts, so the reason shows there (Nov 2:
    found unchecked on the roadmap; the VTT's movement counter starts from this number)."""
    speed = {"walk": 45, "fly": 30, "parts": [("Wood Elf base speed", 35), ("Unarmored Movement", 10)], "notes": []}
    tired = cd.speed_now(speed, [{"name": "Exhaustion", "level": 2}])
    assert (tired["walk"], tired["fly"]) == (35, 20) and sum(v for _, v in tired["parts"]) == 35
    held = cd.speed_now(speed, [{"name": "Exhaustion", "level": 2}, {"name": "Grappled"}])
    assert (held["walk"], held["fly"]) == (0, 0) and sum(v for _, v in held["parts"]) == 0
    assert cd.speed_now(speed, [{"name": "Grappled", "counts": False}]) is speed  # one ending doesn't count
    assert cd.speed_now(speed, [{"name": "Poisoned"}]) is speed and speed["walk"] == 45  # (the sheet's own copy is left alone)
