"""Magic items on Battle (app/conditions.py): item actions, conditions and their Advantage."""

import json

from app import characters
from app import conditions as cd
from app.importer import import_bundle
from tests.test_characters import BUNDLE, admin, char, dm, no_network, owned_by, player  # noqa: F401
from tests.test_suggestions import HX

RING = {"key": "item:9", "name": "Ring of Invisibility", "base_name": "Ring of Invisibility", "magic": True, "equipped": True,
        "attunement": "attuned", "battle": False, "summary": "While wearing this ring, you can take a Magic action to…"}


def test_the_ring_gives_two_actions_only_while_attuned():
    names = [(a["cost"], a["name"], a.get("starts"), a.get("ends")) for a in cd.item_actions(RING)]
    assert names == [("Action", "Turn Invisible", "Invisible", None), ("Bonus action", "Become visible", None, "Invisible")]
    assert cd.item_actions({**RING, "attunement": "required"}) == []  # needs attunement first
    cloak = {**RING, "key": "item:3", "name": "Cloak of Billowing", "base_name": "Cloak of Billowing",
             "attunement": None, "summary": "As a Bonus Action, you make it billow."}
    assert [(a["cost"], a["name"]) for a in cd.item_actions(cloak)] == [("Bonus action", "Use: Cloak of Billowing")]


def test_conditions_offer_advantage_with_the_reason():
    reasons = cd.adv_reasons([{"name": "Invisible", "source": "Ring of Invisibility"}])
    assert reasons["attack"] == ["Invisible (Ring of Invisibility): Advantage on your attack rolls, unless the target can see you"]
    assert reasons["initiative"]
    assert cd.add([], "Invisible", "Ring") == [{"name": "Invisible", "source": "Ring"}]
    assert cd.end([{"name": "Invisible"}], "Invisible") == []


def test_only_the_player_turns_invisible_and_everyone_sees_it(player, admin, dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    url = f"/characters/{cole.id}"
    assert admin.post(f"{url}/conditions", data={"name": "Invisible"}).status_code == 403
    assert player.post(f"{url}/conditions", data={"name": "Flying"}).status_code == 400  # not one askdnd tracks
    r = player.post(f"{url}/conditions", data={"name": "Invisible", "source": "Ring of Invisibility"}, headers=HX)
    assert r.status_code == 200 and 'class="cond-pill"' in r.text
    adv = json.loads(r.text.split("data-cond-adv='")[1].split("'")[0])
    assert adv["attack"][0].startswith("Invisible (Ring of Invisibility)")
    assert "cond-pill" in dm.get(f"{url}/battle").text  # the DM sees it too
    player.post(f"{url}/conditions/end", data={"name": "Invisible"}, headers=HX)
    db.refresh(cole)
    assert not cole.conditions
