"""Items that bring a creature (app/item_creatures.py; Brett chose A and A, Nov 9, docs/mockups/item-creatures/): the DM
sets one up once (askdnd fills in what its words say), its player uses it and askdnd keeps the creature as its own, it's
commanded from its master's column, and it ends at 0 Hit Points or Dismiss, spent until the rest that brings it back.
Made-up item words only: a campaign's homebrew text never goes in the repo."""

import pytest

from app import characters, character_views as views, creatures, item_creatures as ic
from app.models import Campaign
from tests.table_setup import char

WORDS = ("A carved tooth. As an action, you may toss it into an empty space within 15 feet of you, where it becomes an "
         "undead creature you control. Its creature type is undead and it has immunity to necrotic damage and the frightened "
         "condition. Roll initiative for the creature. On each of your turns you may use a bonus action to command the creature "
         "if it's within 30 feet of you. It lasts for one hour or until it drops to 0 hit points, after which the tooth can't be "
         "used again until you finish a long rest.")


def test_its_words_fill_in_the_setup_but_never_the_creature():
    cfg = ic.read(WORDS)
    assert cfg == {"creature": "", "cost": "Action", "range": 15, "type": "Undead", "immune": "necrotic damage, Frightened", "init": "own",
                   "command": "Bonus action", "command_range": 30, "lasts": "1 hour or until 0 Hit Points", "back": "Long Rest"}
    assert ic.read("As a bonus action, a beast appears at dawn.")["cost"] == "Bonus action"
    assert ic.read("It returns at dawn.")["back"] == "Dawn" and ic.until({"back": "Dawn"}) == "dawn"
    assert ic.looks_like({"text": WORDS}) and not ic.looks_like({"text": "A plain rope, 50 feet long."})


@pytest.fixture
def tooth(db, sheet):
    """Cole with Your creatures on and his first item renamed and reworded as an item that brings a creature."""
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["sync", "labs", "creatures"]
    d = sheet["inventory"][0]["definition"]
    d["name"], d["description"] = "Testing Tooth", f"<p>{WORDS}</p>"
    characters.refresh(db, cole)
    from tests.roles import set_role

    set_role(db, "dm@example.com", "dm")
    db.commit()
    it = next(x for x in characters.character_summary(cole)["inventory"] if x["name"] == "Testing Tooth")
    return cole, it["key"]


def _setup(who, cole, key, **more):
    data = {"creature": "Wolf", "type": "Undead", "immune": "necrotic damage, Frightened", "cost": "Action", "range": "15", "init": "own",
            "command": "Bonus action", "command_range": "30", "lasts": "1 hour or until 0 Hit Points", "back": "Long Rest", **more}
    return who.post(f"/characters/{cole.id}/bring/{key}/setup", data=data)


def test_the_dm_sets_it_up_and_its_player_brings_commands_and_ends_it(dm, player, db, tooth):
    cole, key = tooth
    assert "It brings a creature" in dm.get(f"/characters/{cole.id}/detail?ref={key}").text  # (the DM's, under Correct this)
    assert "It brings a creature" not in player.get(f"/characters/{cole.id}/detail?ref={key}").text
    assert "doesn't know what it brings yet" in player.get(f"/characters/{cole.id}/bring/{key}").text
    assert player.post(f"/characters/{cole.id}/bring/{key}").status_code == 409
    assert _setup(player, cole, key).status_code == 403  # (the DM's to set up)
    assert _setup(dm, cole, key).status_code == 204
    from app import house_rules

    house_rules.invalidate()
    for who in (player, dm):  # (Sheet's action list and Battle draw its Use: ASKDND-V2-R, Sheet failed on it)
        for mode in ("", "/battle", "/plan"):
            assert who.get(f"/characters/{cole.id}{mode}").status_code == 200, mode
    assert f'/bring/{key}"' in player.get(f"/characters/{cole.id}").text
    win = player.get(f"/characters/{cole.id}/bring/{key}").text
    assert "Undead Wolf" in win and "Immune to necrotic damage, Frightened" in win and "Then spent until a Long Rest" in win
    r = player.post(f"/characters/{cole.id}/bring/{key}", data={"name": "Snap"})
    assert r.status_code == 200 and r.json()["text"].startswith("Snap is here")
    db.refresh(cole)
    wolf = creatures.own(cole)[0]
    assert (wolf["name"], wolf["kind"], wolf["item"]) == ("Snap", "Wolf", "Testing Tooth")
    assert "Frightened" in wolf["block"]["condition_immunities"] and wolf["block"]["traits"][0]["name"] == "Changed by the Testing Tooth"
    page = player.get(f"/characters/{cole.id}/battle?creature={wolf['id']}").text
    assert "From the Testing Tooth" in page and "up to 1 hour or until 0 Hit Points" in page and "Dismiss" in page
    k = creatures.card(characters.character_summary(cole), wolf)
    assert k["own_initiative"] and "commands it with a Bonus Action within 30 feet" in k["turn"]
    # Its master's column: Command it, while it's here
    sheet = views.apply_overrides(characters.character_summary(cole), house_rules.sheet_overrides(db, cole.campaign_id))
    rows = {o["key"]: o for o in ic.options(cole, sheet)}
    assert rows[f"bring:{key}"]["meta"].startswith("Snap is here") and rows[f"bring:{key}:command"]["cost"] == "Bonus action"
    assert player.post(f"/characters/{cole.id}/bring/{key}").status_code == 409  # (in use)
    # 0 Hit Points: it goes, the item is spent until the Long Rest, whose window brings it back
    assert player.post(f"/characters/{cole.id}/creatures/{wolf['id']}/hp", data={"amount": "99", "to": "damage"}).status_code == 204
    db.refresh(cole)
    it = next(x for x in sheet["inventory"] if x["key"] == key)
    assert ic.state(cole, it) == "spent" and "Spent: back after a Long Rest" in player.get(f"/characters/{cole.id}/bring/{key}").text
    assert "Testing Tooth: ready again" in player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert "Testing Tooth" not in player.get(f"/characters/{cole.id}/rest?kind=short").text
    assert player.post(f"/characters/{cole.id}/rest?kind=long", data={"items_back": "1"}).status_code == 200
    db.refresh(cole)
    assert ic.state(cole, it) == "ready"


def test_undo_and_dismiss(dm, player, db, tooth):
    cole, key = tooth
    _setup(dm, cole, key)
    from app import house_rules

    house_rules.invalidate()
    r = player.post(f"/characters/{cole.id}/bring/{key}").json()
    assert player.post(r["undoUrl"], data=r["undo"]).status_code == 200
    db.refresh(cole)
    assert not creatures.own(cole)
    player.post(f"/characters/{cole.id}/bring/{key}")
    assert dm.post(f"/characters/{cole.id}/bring/{key}/dismiss").status_code == 204  # (the DM can too)
    db.refresh(cole)
    assert creatures.where(cole, creatures.own(cole)[0]) == "gone"
    assert "Brings Undead Wolf" in dm.get("/c/" + db.get(Campaign, cole.campaign_id).slug + "/manage/house-rules").text
    assert _setup(dm, cole, key, creature="No Such Beast").status_code == 409
    assert _setup(dm, cole, key, creature="").status_code == 204  # (removed)

