"""Magic items on Battle (app/conditions.py): item actions, conditions and their Advantage."""

import pytest
import json

from app import characters
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


def test_the_halo_shows_the_most_serious_family_and_poisoned_invisible_blinded_their_own():
    """Brett, 2026-10-28 (docs/mockups/conditions-on-battle.html): red can't act, amber hindered, blue helped, the most
    serious only; Poisoned green, Invisible white and Blinded black each a ring of their own, stacked; Unconscious
    darkens the edges too."""
    rings = lambda *names: cd.rings([{"name": n} for n in names])  # noqa: E731
    assert rings() == [] and rings("Prone") == ["hindered"] and rings("Enlarged") == ["helped"]
    assert rings("Prone", "Stunned", "Enlarged") == ["cant"]
    assert rings("Poisoned", "Prone") == ["hindered", "poisoned"] and rings("Poisoned") == ["poisoned"]
    assert rings("Invisible") == ["invisible"] and rings("Blinded", "Unconscious") == ["cant", "dark"]
    assert {cd.family(n) for n in cd.KNOWN} == {"cant", "hindered", "helped"}


def test_a_condition_shows_on_battle_party_and_your_menu_bar_button(player, dm, db):
    """Everyone at the table sees a character's conditions (as on the pills): the DM's Battle for Cole has the halo and
    an emblem per condition with what it does, the Party card its icons, and the player's own menu bar button a dot each."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    for n, lv in (("Poisoned", 0), ("Prone", 0), ("Exhaustion", 2)):
        player.post(f"/characters/{cole.id}/conditions", data={"name": n, "level": lv or 1}, headers=HX)
    page = dm.get(f"/characters/{cole.id}/battle").text
    assert '<i data-ring="hindered"' in page and '<i data-ring="poisoned"' in page
    corner = page.split('class="cond-corner"')[1].split("</div>")[0]
    assert [x.split('"')[0] for x in corner.split('data-name="')[1:]] == ["Poisoned", "Prone", "Exhaustion"]  # newest nearest the corner
    assert 'class="cond-lv">2<' in corner and "Disadvantage on attack rolls" in corner
    party = dm.get("/c/main/party").text
    assert 'data-ring="hindered"' in party and 'title="Exhaustion 2"' in party
    dots = player.get("/c/main/").text.split("data-cond-dots")[1].split("</span>")[0]
    assert 'title="Poisoned, Prone, Exhaustion"' in dots and dots.count("<i data-cond=") == 3
    player.post(f"/characters/{cole.id}/conditions", data={"name": "Invisible"}, headers=HX)
    assert 'id="battle-body" class="cond-ghost"' in dm.get(f"/characters/{cole.id}/battle").text  # the portrait fades
