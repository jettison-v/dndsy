"""Your creatures (app/creatures.py; docs/plans/2026-11-03-your-creatures.md): a creature on a character's D&D Beyond sheet
that isn't a Wild Shape form gets a switch by the name on Battle, and Battle is drawn as the creature's, with the numbers
that grow with its master worked out. Made-up stat blocks in D&D Beyond's shape (never a book's words)."""

import pytest
from sqlalchemy import select

from app import characters, creatures
from app.models import Campaign, TableRoll
from tests.table_setup import char

ZAP = 990001


def made_up(name="Homunculus Servant", group=12, cid=ZAP, removed=0):
    """A creature as D&D Beyond's sheet lists it, with older words (a "Weapon Attack … to hit", damage without its average)."""
    return {"id": cid, "entityTypeId": 1, "name": None, "groupId": group, "isActive": False, "removedHitPoints": removed, "temporaryHitPoints": 0,
            "definition": {"name": name, "armorClass": 13, "averageHitPoints": 1, "hitPointDice": {"diceString": "1d4"}, "challengeRatingId": 1,
                           "sizeId": 2, "passivePerception": 12, "movements": [{"movementId": 1, "speed": 20}, {"movementId": 4, "speed": 30}],
                           "stats": [{"statId": i, "value": v} for i, v in zip(range(1, 7), (4, 15, 12, 10, 10, 7), strict=True)],
                           "savingThrows": [{"statId": 2}], "skills": [{"skillId": 14, "value": 2, "additionalBonus": 2}],
                           "conditionImmunities": [11], "senses": [{"senseId": 2, "notes": "60 ft."}],
                           "specialTraitsDescription": "<p><strong>Might of the Master.</strong> Made-up words: it grows with its master.</p>",
                           "actionsDescription": "<p><strong>Zap.</strong> Ranged Weapon Attack: +4 to hit, range 30 ft., one target. Hit: 1d4 + 2 force damage.</p>",
                           "reactionsDescription": "<p><strong>Carry.</strong> It carries a touch spell for its master.</p>",
                           "characteristicsDescription": "<p>A made-up helper.</p>"}}


@pytest.fixture(autouse=True)
def labs(db, sheet):
    """Your creatures is a Labs feature (app/vtt.py): on for Cole's campaign, with a made-up creature on his sheet."""
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["sync", "labs", "creatures"]
    sheet["creatures"] = [*sheet.get("creatures", []), made_up()]
    characters.refresh(db, cole)
    db.flush()
    return cole


def master(level=10, intelligence=16, pb=4):
    return {"classes": [{"name": "Artificer", "level": level}], "proficiency_bonus": pb,
            "abilities": [{"key": "intelligence", "score": intelligence}], "creatures": []}


def test_an_older_stat_block_is_read_in_the_2024_words():
    assert creatures.modern("Zap. Ranged Weapon Attack: +4 to hit, range 30 ft. Hit: 1d4 + 2 force damage.") == \
        "Zap. Ranged Attack Roll: +4, range 30 ft. Hit: 4 (1d4 + 2) Force damage."
    assert "6 (2d6 - 1) Piercing damage plus 3 (1d6) fire damage" in creatures.modern("Hit: 2d6 - 1 piercing damage plus 3 (1d6) fire damage.")


def test_its_numbers_grow_with_its_master(db, labs):
    """Brett, Nov 3 ("work them out"): a Homunculus Servant's Hit Points from its book's rule, and Might of the Master (its own
    trait) adds the master's Proficiency Bonus above 2 to its attack, damage, saves and skills."""
    c = creatures.yours(characters.character_summary(labs))[0]
    k = creatures.card(master(), c)
    assert k["hp"]["max"] == 1 + 3 + 10 and k["hp"]["current"] == 14 and "Tasha's Cauldron of Everything" in k["notes"][0]
    zap = k["columns"]["Action"]["all"][0]
    assert (zap["name"], zap["hit"], zap["recipe"]["events"][0]["parts"]) == ("Zap", "+6", ["1d4+4 force"]) and "worn item" not in zap["meta"]
    assert next(s["label"] for s in k["saves"] if s["key"] == "dex") == "+6"  # (Dex +2, proficient +2, Might +2)
    assert k["skills"] == [{"name": "Perception", "label": "+6"}] and k["immune"] == ["Poisoned"] and k["walk"] == 20
    assert "Right after its master's turn" in k["turn"] and [o["name"] for o in k["columns"]["Action"]["all"]] == ["Zap", "Dodge"]
    low = creatures.card(master(level=2, intelligence=10, pb=2), c)
    assert low["hp"]["max"] == 3 and low["columns"]["Action"]["all"][0]["hit"] == "+4"  # (level 2: +4 as the stat block says)


def test_a_familiar_keeps_its_stat_block_and_rolls_its_own_initiative():
    owl = creatures.card(master(), _parsed(made_up("Owl", group=2, cid=7)))
    assert owl["hp"]["max"] == 1 and owl["own_initiative"] and "rolls its own Initiative" in owl["turn"]


def _parsed(raw):
    from app.ddb_sheet import parse_character
    from tests.table_setup import COLE

    return next(x for x in parse_character({**COLE, "creatures": [raw]})["creatures"] if x["id"] == raw["id"])


def test_wild_shape_forms_are_not_creatures(db, labs, sheet):
    sheet["creatures"].append(made_up("Ape", group=13, cid=5))
    characters.refresh(db, labs)
    assert [c["kind"] for c in creatures.yours(characters.character_summary(labs))] == ["Homunculus Servant"]


def test_battle_has_the_switch_and_draws_the_creature(player, db, labs):
    page = player.get(f"/characters/{labs.id}/battle").text
    assert 'class="who-switch' in page and f'href="/characters/{labs.id}/battle?creature={ZAP}"' in page and ">Homunculus</a>" in page
    k = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "Cole's Homunculus Servant" in k and 'data-who="Homunculus Servant"' in k and ">Zap</b>" in k and "Back to Cole" in k
    assert "1d4+3 force" in k and "<b>1</b>" in k  # (Might of the Master: Cole's Proficiency Bonus +3; no Artificer, so D&D Beyond's 1 HP)
    assert "Cole's Homunculus" not in player.get(f"/characters/{labs.id}/battle?creature=12345").text  # (not his: his own Battle)


def test_without_labs_there_is_no_switch(player, db, labs):
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    assert "who-switch" not in player.get(f"/characters/{labs.id}/battle").text
    assert "Cole's Homunculus" not in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text


def test_a_creatures_roll_says_whose_it_is(player, db, labs):
    """Table rolls says "Cole (Homunculus Servant)"; a name that isn't one of his creatures is ignored."""
    for who in ("Homunculus Servant", "Tarrasque"):
        r = player.post("/rolls", data={"character": labs.id, "kind": "attack", "label": "Zap", "mod": "6", "who": who})
        assert r.status_code == 200
    rows = list(db.scalars(select(TableRoll).where(TableRoll.character_id == labs.id).order_by(TableRoll.id)))
    assert [r.who for r in rows[-2:]] == ["Homunculus Servant", ""]


def test_party_gives_it_its_own_card_after_its_masters(player, db, labs):
    """Brett, Nov 4 (Creatures as Characters boards 7 and 8, C): on Party a creature is as easy to see as a character, its own
    card as the second half of its master's (whose it is, its Hit Points, AC, Speed and turn), opening its Battle; its
    master's says "with" it and carries its picture."""
    page = player.get("/party").text
    pair = page.index('<div class="pt-pair" style="--parts: 2">')
    master, mine = page.index('data-modal-url="/characters/%d/brief"' % labs.id), page.index('class="section pt-card pt-creature-card"')
    assert pair < master < mine and page.count("</article>", master, mine) == 1
    assert page.index("</article>", mine) < page.index("</div>", page.index("</article>", mine))  # (both halves in one card)
    assert 'class="pt-badge roll-av" title="With Homunculus Servant"' in page[master:mine]
    card = page[mine:page.index("</article>", mine)]
    assert "Cole's Homunculus" in card and f'href="/characters/{labs.id}/battle?creature={ZAP}" data-no-peek' in card
    assert "<b>1</b><span class=\"note\"> / 1" in card and "Right after its master" in card  # (Cole has no Artificer levels: D&D Beyond's 1)
    assert "with Homunculus" in page[master:mine]
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    assert "pt-creature-card" not in player.get("/party").text


# ------------------------------------------------------------------ its Hit Points on D&D Beyond (slice 2)


def ops(db, ch):
    from app import ddb_bridge

    return ddb_bridge.outbox(db, ch)["ops"]


def test_its_damage_and_healing_go_to_d_and_d_beyond_as_its_sheet_sends_them(player, db, labs):
    """Brett, Nov 3 ("keep D&D Beyond up to date"): PUT creature/hp, as D&D Beyond's own sheet sends it (tried on Vi's test
    sheet); temporary hit points take damage first, and it never takes more than its maximum."""
    r = player.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "3", "to": "damage"})  # (Cole: its stat block's 1 HP)
    assert r.status_code == 204 and "took 3" in r.headers["HX-Trigger"]
    op, = ops(db, labs)
    assert (op["method"], op["path"]) == ("PUT", "/character/v5/creature/hp")
    assert op["body"] == {"characterId": 75423618, "id": ZAP, "removedHitPoints": 1, "temporaryHitPoints": 0}  # (1 HP: at 0)
    assert "Cole's Homunculus Servant" in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text


def maxima(db, ch):
    from app.models import BridgeIntent

    return [(i.data["value"], i.state) for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == ch.id).order_by(BridgeIntent.id))
            if str(i.data.get("field", "")).startswith("creature_max:")]


def test_askdnd_sets_the_rules_maximum_on_d_and_d_beyond_by_itself(player, db, labs, sheet):
    """Brett, Nov 4 (Creatures as Characters, A: askdnd keeps D&D Beyond's Extras in step): D&D Beyond counts damage against
    the maximum it shows (its stat block's 1 for a Homunculus Servant), so a read sets the rule's there (its character value
    43), with no button; − and + work at once, as it's on its way."""
    sheet["classes"][0]["definition"]["name"] = "Artificer"  # (Cole as an artificer, for the rule)
    characters.refresh(db, labs)
    (value, _), = maxima(db, labs)
    assert value > 1
    op, = ops(db, labs)
    assert (op["method"], op["path"]) == ("PUT", "/character/v5/custom/value")
    assert {k: op["body"][k] for k in ("typeId", "valueId", "contextId", "value")} == {"typeId": 43, "valueId": str(ZAP), "contextId": None, "value": value}
    k = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "Set D&amp;D Beyond to" not in k and "askdnd sets" not in k and "−/+" in k
    assert player.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "3", "to": "damage"}).status_code == 204
    characters.refresh(db, labs)
    assert len(maxima(db, labs)) == 1  # (on its way: not asked again)


def test_the_maximum_is_never_made_again_once_undone_nor_over_a_typed_one(db, labs, sheet):
    """One undone isn't made again; one its player or DM typed on D&D Beyond stays theirs; after a level-up askdnd's own
    number moves on."""
    sheet["classes"][0]["definition"]["name"] = "Artificer"
    characters.refresh(db, labs)
    from app.models import BridgeIntent

    it = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == labs.id)).one()
    first = it.data["value"]
    it.state = "dismissed"
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "dismissed")]
    it.state = "live"  # (made: D&D Beyond holds askdnd's number)
    sheet["characterValues"] = [{"typeId": 43, "valueId": str(ZAP), "value": first}]
    sheet["classes"][0]["level"] += 1  # (a level-up: the rule's number grows)
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "live"), (first + 1, "waiting")]
    db.delete(db.scalars(select(BridgeIntent).where(BridgeIntent.state == "waiting")).one())
    sheet["characterValues"] = [{"typeId": 43, "valueId": str(ZAP), "value": 9}]  # (typed on D&D Beyond)
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(first, "live")]


def test_without_your_creatures_on_nothing_is_set(db, labs, sheet):
    db.get(Campaign, labs.campaign_id).vtt_pieces = ["sync"]
    sheet["classes"][0]["definition"]["name"] = "Artificer"
    characters.refresh(db, labs)
    assert maxima(db, labs) == []


def test_a_creature_change_is_only_for_its_player_or_the_dm(dm, db, labs):
    from tests.roles import set_role

    assert dm.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "1", "to": "heal"}).status_code == 404  # (not the DM yet)
    set_role(db, "dm@example.com", "dm")
    assert dm.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "1", "to": "heal"}).status_code == 204


def test_the_extension_sends_a_character_value_only_for_a_creature():
    """extension 0.10.0 and 0.11.0: custom/value is on its list, but only for a creature's values 42, 43 and 44 (ddb-page.js)."""
    import os

    js = open(os.path.join(os.path.dirname(__file__), "..", "extension", "askdnd-bridge", "ddb-page.js")).read()
    assert "const CREATURE_VALUES = new Set([42, 43, 44])" in js and "!CREATURE_VALUES.has(Number(op.body.typeId))" in js


# ------------------------------------------------------------------ a familiar in play (round 2: app/companions.py)
OWL, RAVEN = 990002, 990003


def familiar_sheet(db, labs, sheet):
    """Cole with two familiar forms on his Extras (made-up stat blocks) and Find Familiar among his spells (one of his
    1st-level spells renamed, its words his own)."""
    sheet["creatures"] = [*sheet["creatures"], {**made_up("Owl", 2, OWL), "name": "Pip"}, made_up("Raven", 2, RAVEN, removed=1)]

    def rename(x):
        if isinstance(x, dict):
            d = x.get("definition")
            if isinstance(d, dict) and d.get("level") == 1 and "school" in d and not d.get("concentration"):
                d["name"] = "Find Familiar"
                return True
            return any(rename(v) for v in x.values())
        return isinstance(x, list) and any(rename(v) for v in x)
    assert rename(sheet)
    characters.refresh(db, labs)
    db.flush()
    from app import spellbook as sb

    return next(e for e in sb.entries(characters.character_summary(labs)) if e["name"] == "Find Familiar")


def test_a_familiar_exists_only_once_its_cast(player, db, labs, sheet):
    """Brett, 2026-11-04 ("They only exist when you cast them"): a familiar on the sheet's Extras isn't on Battle's switch
    or Party until Find Familiar brings it; a Homunculus Servant (not a familiar) always is."""
    familiar_sheet(db, labs, sheet)
    battle = player.get(f"/characters/{labs.id}/battle").text
    assert f"creature={ZAP}" in battle and f"creature={OWL}" not in battle and f"creature={RAVEN}" not in battle
    assert f"creature={OWL}" not in player.get("/party").text
    assert "Cole's Pip" not in player.get(f"/characters/{labs.id}/battle?creature={OWL}").text


def test_casting_find_familiar_brings_the_one_you_pick_one_at_a_time(player, db, labs, sheet):
    """Board 2: the Cast window lists the forms on Extras and Celestial, Fey or Fiend; the one picked is here, made what
    was picked. Cast again with another form: the familiar takes it (one at a time). Undo puts it back as it was."""
    e = familiar_sheet(db, labs, sheet)
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    win = player.get(url).text
    assert 'name="familiar"' in win and f'value="{OWL}" checked' in win and 'value="Fey"' in win
    r = player.post(url, data={"way": "ritual", "familiar": str(OWL), "kind": "Fey"})
    assert r.status_code == 200 and "Pip (Fey) is here" in r.json()["text"]
    db.refresh(labs)
    assert labs.companions == {str(OWL): {"state": "here", "kind": "Fey"}}
    assert f"creature={OWL}" in player.get("/party").text
    r = player.post(url, data={"way": "ritual", "familiar": str(RAVEN), "kind": "Fiend"})
    assert "takes a new form: Raven (Fiend)" in r.json()["text"]
    db.refresh(labs)
    assert labs.companions == {str(RAVEN): {"state": "here", "kind": "Fiend"}}
    assert r.json()["undo"]["healed"] == f"{RAVEN}:1"  # (one that had taken damage comes back whole, through the bridge)
    assert player.post(r.json()["undoUrl"], data=r.json()["undo"]).status_code == 200
    db.refresh(labs)
    assert labs.companions == {str(OWL): {"state": "here", "kind": "Fey"}}


def test_the_pocket_dimension_dismissing_and_zero_hit_points(player, dm, db, labs, sheet):
    """Board 3: sent to the pocket dimension and back (its player or the DM), dismissed forever, and gone at 0 Hit Points
    until cast again; its Battle says where it is."""
    from tests.roles import set_role

    familiar_sheet(db, labs, sheet)
    labs.companions = {str(OWL): {"state": "here", "kind": "Celestial"}}
    db.flush()
    where = f"/characters/{labs.id}/creatures/{OWL}/where"
    assert "Send to the pocket dimension" in player.get(f"/characters/{labs.id}/battle?creature={OWL}").text
    assert player.post(where, data={"to": "away"}).status_code == 204
    page = player.get(f"/characters/{labs.id}/battle?creature={OWL}").text
    assert "In the pocket dimension" in page and "Bring it back" in page
    assert player.post(where, data={"to": "away"}).status_code == 409  # (already there)
    assert dm.post(where, data={"to": "here"}).status_code == 404  # (not the DM yet)
    set_role(db, "dm@example.com", "dm")
    assert dm.post(where, data={"to": "here"}).status_code == 204
    r = player.post(f"/characters/{labs.id}/creatures/{OWL}/hp", data={"amount": "5", "to": "damage"})
    assert r.status_code == 204 and "disappears" in r.headers["HX-Trigger"]
    db.refresh(labs)
    assert labs.companions[str(OWL)] == {"state": "gone", "kind": "Celestial", "why": "0 Hit Points"}
    assert "Cast Find Familiar" in player.get(f"/characters/{labs.id}/battle?creature={OWL}").text
    labs.companions = {str(OWL): {"state": "here", "kind": "Celestial"}}
    db.flush()
    assert player.post(where, data={"to": "gone"}).status_code == 204
    db.refresh(labs)
    assert labs.companions[str(OWL)]["why"] == "dismissed"


def test_find_familiar_works_with_the_sheet_out_of_reach_as_a_ritual(player, db, labs, sheet):
    """The familiar is askdnd's, like a Wild Shape form: with Cole's sheet closed, Find Familiar still casts as a Ritual
    or without a slot (nothing for D&D Beyond), and a slot is refused as for any spell."""
    from datetime import UTC, datetime, timedelta

    e = familiar_sheet(db, labs, sheet)
    labs.sheet_heard_at = datetime.now(UTC) - timedelta(minutes=10)
    db.flush()
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    win = player.get(url).text
    assert 'name="familiar"' in win and "so only as a Ritual" in win and 'value="slot:' not in win
    assert player.post(url, data={"way": "ritual", "familiar": str(OWL), "kind": "Fiend"}).status_code == 200
    db.refresh(labs)
    assert labs.companions[str(OWL)]["state"] == "here"
    assert player.post(url, data={"way": "slot:1", "familiar": str(OWL), "kind": "Fiend"}).status_code == 409


def test_casting_keeps_d_and_d_beyonds_extras_in_step(player, db, labs, sheet):
    """Brett, 2026-11-04, option A (extension 0.11.0): the familiar that's here is switched on on its Extras, with what it
    is (D&D Beyond's creature type, 44) and the name it was given; every other form is switched off; sending it away
    switches it off. As D&D Beyond's own sheet sends them (tried on Levi's test sheet, Nov 4)."""
    from app.models import BridgeIntent

    e = familiar_sheet(db, labs, sheet)
    sheet["creatures"][-1]["isActive"] = True  # (the Raven switched on there by hand)
    characters.refresh(db, labs)
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    assert 'name="familiar_name" value="Pip"' in player.get(url).text  # (the name it has on D&D Beyond)
    r = player.post(url, data={"way": "ritual", "familiar": str(OWL), "kind": "Fey", "familiar_name": "Moss"})
    assert "Moss (Fey) is here" in r.json()["text"]
    got = {op["path"].rsplit("/v5/", 1)[1] + ("" if "typeId" not in op["body"] else f":{op['body']['typeId']}"): op["body"] for op in ops(db, labs)}
    assert got["creature/status"] in ({"characterId": 75423618, "id": OWL, "isActive": True}, {"characterId": 75423618, "id": RAVEN, "isActive": False})
    fields = sorted(i.data["field"] for i in db.scalars(select(BridgeIntent).where(BridgeIntent.kind == "set")))
    assert fields == sorted([f"creature_active:{OWL}", f"creature_active:{RAVEN}", f"creature_type:{OWL}", f"creature_name:{OWL}"])
    values = {i.data["field"]: i.data["value"] for i in db.scalars(select(BridgeIntent).where(BridgeIntent.kind == "set"))}
    assert values == {f"creature_active:{OWL}": True, f"creature_active:{RAVEN}": False, f"creature_type:{OWL}": 8, f"creature_name:{OWL}": "Moss"}
    assert got["custom/value:44"]["value"] == 8 and got["creature"] == {"characterId": 75423618, "id": OWL, "name": "Moss", "description": None, "groupId": 2}
    for i in db.scalars(select(BridgeIntent)):
        db.delete(i)
    db.flush()
    assert player.post(f"/characters/{labs.id}/creatures/{OWL}/where", data={"to": "away"}).status_code == 204
    away = {i.data["field"]: i.data["value"] for i in db.scalars(select(BridgeIntent).where(BridgeIntent.kind == "set"))}
    assert away == {f"creature_active:{RAVEN}": False}  # (the Owl is still off on D&D Beyond: the cast's changes weren't made here)


# ------------------------------------------------------------------ its picture (the one Picture window, Nov 4)


def picture_png():
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (400, 300), (30, 120, 90)).save(out, "PNG")
    return out.getvalue()


def test_a_creatures_picture_in_the_picture_window(player, dm, db, labs, sheet):
    """Brett, 2026-11-04 (Pictures in askdnd): pressing its picture on its Battle opens the one Picture window; its player
    (or the DM) uploads one, and Battle and Party show it in place of D&D Beyond's art. A familiar keeps one picture
    across its forms."""
    from tests.roles import set_role

    ref = {"for": f"creature:{labs.id}:{ZAP}"}
    assert f'data-modal-url="/pictures?for=creature:{labs.id}:{ZAP}"' in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "Homunculus Servant&#39;s picture" in player.get(f"/pictures?for=creature:{labs.id}:{ZAP}").text
    assert dm.post("/pictures/upload", data=ref, files={"file": ("h.png", picture_png(), "image/png")}).status_code == 404  # (not the DM yet)
    r = player.post("/pictures/upload", data=ref, files={"file": ("h.png", picture_png(), "image/png")})
    assert r.status_code == 204 and "Picture saved" in r.headers["HX-Trigger"]
    url = f"/characters/{labs.id}/creatures/{ZAP}/picture?size=thumb"
    assert url in player.get("/party").text.replace("&amp;", "&") and url in player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text.replace("&amp;", "&")
    assert player.get(url).status_code == 200
    set_role(db, "dm@example.com", "dm")
    assert dm.get(url).status_code == 200  # (the table sees it)
    familiar_sheet(db, labs, sheet)
    labs.companions = {str(OWL): {"state": "here", "kind": "Fey"}}
    db.flush()
    player.post("/pictures/upload", data={"for": f"creature:{labs.id}:{OWL}"}, files={"file": ("p.png", picture_png(), "image/png")})
    labs.companions = {str(RAVEN): {"state": "here", "kind": "Fey"}}  # (a new form: the same familiar, the same picture)
    db.flush()
    assert f"/characters/{labs.id}/creatures/familiar/picture?size=thumb" in player.get(f"/characters/{labs.id}/battle?creature={RAVEN}").text.replace("&amp;", "&")


# ------------------------------------------------------------------ in the fight (slice 3, Nov 4)


def told(turn=1, extra=()):
    from tests.test_fight import heard

    f = heard(turn=turn)
    f["order"] += [dict(x, active=False) for x in extra]
    return f


def test_a_creature_sharing_its_masters_initiative_is_listed_right_after_them(player, db, labs):
    """Brett, 2026-11-04 (Creatures as Characters board 4: never forgotten): a Homunculus Servant (it shares its master's
    Initiative) sits right after Cole in the fight's order, with its Hit Points, AC and turn; Party's Rows show it."""
    from app import fight

    campaign = db.get(Campaign, labs.campaign_id)
    fight.heard(db, campaign, told())
    order = fight.for_person(db, campaign, "player@example.com")["order"]
    assert [x["name"] for x in order][:2] == ["Cole", "Homunculus Servant"]
    hom = order[1]
    assert hom["sub"] and hom["initiative"] == 18 and hom["whose"] == "Cole's Homunculus" and hom["creature"]["hp"]["max"] == 1
    rows = player.get("/party").text
    assert 'class="ft-creature pet"' in rows and f'href="/characters/{labs.id}/battle?creature={ZAP}" data-no-peek' in rows


def test_a_familiar_is_the_vtts_own_token_or_listed_under_its_master(player, db, labs, sheet):
    """A familiar has its own Initiative: the VTT's companion token for it (by its name) is it; a monster token is only
    by a name its player gave it, so an enemy Owl stays an enemy; one the VTT hasn't got is listed under its master."""
    from app import fight

    familiar_sheet(db, labs, sheet)
    labs.companions = {str(OWL): {"state": "here", "kind": "Fey"}}  # (Pip, an Owl)
    db.flush()
    campaign = db.get(Campaign, labs.campaign_id)
    fight.heard(db, campaign, told(extra=[{"key": "t-owl", "name": "Owl", "kind": "monster", "initiative": 12}]))
    order = fight.for_person(db, campaign, "player@example.com")["order"]
    enemy = next(x for x in order if x["key"] == "t-owl")
    assert "creature" not in enemy  # (an Owl monster isn't Pip)
    pip = next(x for x in order if x.get("creature") and x["name"] == "Pip")
    assert pip["sub"] and pip["missing"] and pip["initiative"] is None  # (not in the VTT's order yet)
    fight.heard(db, campaign, told(extra=[{"key": "t-pip", "name": "Pip", "kind": "companion", "initiative": 14}]))
    order = fight.for_person(db, campaign, "player@example.com")["order"]
    pip = next(x for x in order if x["key"] == "t-pip")
    assert pip["creature"]["id"] == OWL and not pip["sub"] and pip["whose"] == "Cole's familiar"
    assert [x["key"] for x in order].count("t-pip") == 1 and not any(x["key"] == f"cr:{labs.id}:{OWL}" for x in order)


def test_a_creatures_turn_is_a_corner_card_for_its_masters_player(db, labs, sheet):
    """One sharing its master's Initiative: when its master's turn ends. A familiar: when its own token's turn begins."""
    from app import fight

    familiar_sheet(db, labs, sheet)
    labs.companions = {str(OWL): {"state": "here", "kind": "Fey"}}
    db.flush()
    campaign = db.get(Campaign, labs.campaign_id)
    pip = {"key": "t-pip", "name": "Pip", "kind": "companion", "initiative": 14}
    fight.heard(db, campaign, told(turn=1, extra=[pip]))
    fight.heard(db, campaign, told(turn=2, extra=[pip]))  # (Cole's turn ends: the Homunculus's begins)
    said = [(r["kind"], r["name"], r["character"]) for r in campaign.fight["reminders"]]
    assert ("creature", "Homunculus Servant", labs.id) in said
    f = told(turn=1, extra=[pip])
    for x in f["order"]:
        x["active"] = x["key"] == "t-pip"
    fight.heard(db, campaign, f)
    assert ("creature", "Pip", labs.id) in [(r["kind"], r["name"], r["character"]) for r in campaign.fight["reminders"]]


def test_a_familiar_that_is_here_lends_its_master_its_eyes_and_its_touch(player, db, labs, sheet):
    """Board 3 (Find Familiar): on the master's own Battle, See through its eyes (a Bonus Action) and Deliver a touch
    spell (its Reaction) while it's here; greyed with the reason while it's away or gone; nothing before it's cast. Its
    own Battle lists them too, as its master's."""
    from app import companions

    familiar_sheet(db, labs, sheet)
    s = characters.character_summary(labs)
    assert companions.master_options(labs, s) == []  # (not cast yet)
    labs.companions = {str(OWL): {"state": "here", "kind": "Fey"}}
    eyes, touch = companions.master_options(labs, s)
    assert (eyes["name"], eyes["cost"], eyes["form_why"]) == ("See through Pip's eyes", "Bonus action", "")
    assert (touch["name"], touch["cost"]) == ("Deliver a touch spell", "Reaction") and "100 ft" in touch["meta"]
    db.flush()
    battle = player.get(f"/characters/{labs.id}/battle").text
    assert "See through Pip&#39;s eyes" in battle and "Deliver a touch spell" in battle
    own = player.get(f"/characters/{labs.id}/battle?creature={OWL}").text
    assert "Cole&#39;s Bonus Action" in own
    labs.companions = {str(OWL): {"state": "away", "kind": "Fey"}}
    assert "pocket dimension" in companions.master_options(labs, s)[0]["form_why"]


def test_find_familiar_as_a_new_form_adds_it_to_extras_and_ties_it_back(player, db, labs, sheet):
    """Board 2, "or a new one" (Nov 4, recorded on Levi's seat: Manage Extras › Familiar › Add sends POST creature with
    D&D Beyond's monster id): a form of the rules the sheet doesn't have is added to Extras through the bridge; askdnd
    keeps the familiar by its monster id until a read finds the new creature, then puts D&D Beyond in step with it."""
    from sqlalchemy import select

    from app import ddb_fields
    from app.models import BridgeIntent

    e = familiar_sheet(db, labs, sheet)
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    win = player.get(url).text
    assert "Or a new form" in win and 'value="new:4775808"' in win  # (the 2024 Cat, by its D&D Beyond id)
    r = player.post(url, data={"way": "ritual", "familiar": "new:4775808", "kind": "Fiend", "familiar_name": "Smudge"})
    assert r.status_code == 200 and "Smudge, a Cat (Fiend), added to D&D Beyond's Extras" in r.json()["text"]
    db.refresh(labs)
    assert labs.companions == {"new:4775808": {"state": "here", "kind": "Fiend", "name": "Smudge"}}
    sets = lambda: {i.data["field"]: i.data["value"] for i in db.scalars(select(BridgeIntent).where(  # noqa: E731
        BridgeIntent.character_id == labs.id, BridgeIntent.kind == "set"))}
    assert sets()["familiar_add:4775808"] == 1
    assert ddb_fields.write(75423618, "familiar_add:4775808", 1)["body"] == {"characterId": 75423618, "groupId": 2, "monsterId": 4775808, "names": [None]}
    cat = made_up("Cat", 2, 990009)
    cat["definition"]["id"] = 4775808
    sheet["creatures"] = [*sheet["creatures"], cat]
    characters.refresh(db, labs)  # (D&D Beyond has it now)
    db.refresh(labs)
    assert labs.companions == {"990009": {"state": "here", "kind": "Fiend"}}
    got = sets()
    assert (got["creature_active:990009"], got["creature_type:990009"], got["creature_name:990009"]) == (True, 9, "Smudge")


def test_wild_companion_a_familiar_from_a_wild_shape_use_gone_at_a_long_rest(player, db, labs, sheet):
    """Board 2 of Steeds, Summons and Wild Companion (Brett, Nov 4; the 2024 Druid's Wild Companion): Find Familiar's
    ways start with a Wild Shape use (and a slot as Wild Companion); cast so, it's always Fey, spends the Wild Shape use
    through the bridge, and the next Long Rest window lists it leaving, ticked."""
    from sqlalchemy import select

    from app import casting
    from app.models import BridgeIntent

    e = familiar_sheet(db, labs, sheet)
    s = characters.character_summary(labs)
    if not casting.wild_use(s):
        pytest.skip("Cole's test sheet has no Wild Companion")  # (a Druid's, from level 2)
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    win = player.get(url).text
    assert 'value="wild"' in win and "Wild Companion" in win and "always Fey" in win
    r = player.post(url, data={"way": "wild", "familiar": str(OWL), "kind": "Celestial"})
    assert r.status_code == 200 and "as Wild Companion, a Wild Shape use" in r.json()["text"] and "(Fey)" in r.json()["text"]
    db.refresh(labs)
    assert labs.companions[str(OWL)] == {"state": "here", "kind": "Fey", "wild": True}
    spent = [i.data for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == labs.id, BridgeIntent.kind == "use"))]
    assert {"field": casting.wild_use(s)["field"], "delta": 1} in spent
    rest = player.get(f"/characters/{labs.id}/rest?kind=long").text
    assert 'name="wild_leaves"' in rest and "Pip leaves (Wild Companion)" in rest


def test_undoing_a_new_form_stops_it_and_counts_only_familiars(player, db, labs, sheet):
    """Review, Nov 4: Undo after a new form stops its waiting change (D&D Beyond never gets it), and puts back only what
    the cast changed; the read-back counts the Familiar group alone (an Owl kept as a Pet isn't the new one)."""
    from sqlalchemy import select

    from app import ddb_fields
    from app.models import BridgeIntent

    e = familiar_sheet(db, labs, sheet)
    labs.companions = {**(labs.companions or {}), "9000000000001": {"own": True, "state": "here", "c": {"id": 9000000000001}}}
    db.flush()
    url = f"/characters/{labs.id}/cast?key={e['key']}"
    undo = player.post(url, data={"way": "ritual", "familiar": "new:4775808", "kind": "Fey"}).json()["undo"]
    assert undo["added"] == "4775808"
    db.refresh(labs)
    labs.companions = {**labs.companions, "9000000000001": {"own": True, "state": "gone", "c": {"id": 9000000000001}}}  # (changed since)
    db.flush()
    assert player.post(f"/characters/{labs.id}/cast/undo", data={"key": e["key"], **undo}).status_code < 300
    db.refresh(labs)
    add = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == labs.id, BridgeIntent.kind == "set").order_by(BridgeIntent.id))
    assert add.data["field"] == "familiar_add:4775808" and add.state == "dismissed"
    assert "new:4775808" not in labs.companions and labs.companions["9000000000001"]["state"] == "gone"  # (left as it was changed)
    raw = {"creatures": [{"groupId": 5, "definition": {"id": 4775808}}, {"groupId": 2, "definition": {"id": 4775808}}]}
    assert ddb_fields.pick(raw, ddb_fields.steps("familiar_add:4775808")) == 1


def test_askdnds_own_maximum_taken_off_d_and_d_beyond_is_put_back_and_minus_plus_never_wait_for_good(player, db, labs, sheet):
    """Brett, Nov 5 (option B): askdnd's own number gone from D&D Beyond (taken off by hand, or by a reset: the live test
    did it, and − and + waited for good) is put back at the next read, at most once an hour. While askdnd holds back (put
    back lately, or undone), − and + count against D&D Beyond's maximum and the page says why; never waiting for good."""
    from datetime import UTC, datetime, timedelta

    from app.models import BridgeIntent

    sheet["classes"][0]["definition"]["name"] = "Artificer"
    characters.refresh(db, labs)
    it = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == labs.id)).one()
    rule = it.data["value"]
    it.state = "live"  # (made, and then taken off D&D Beyond: its read shows no maximum there)
    db.flush()
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(rule, "live")]  # (put back lately: not again within the hour)
    page = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert "was taken off there. askdnd puts it back within the hour" in page and "−/+" in page
    assert player.post(f"/characters/{labs.id}/creatures/{ZAP}/hp", data={"amount": "1", "to": "damage"}).status_code == 204
    for x in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == labs.id)):
        db.delete(x) if x.kind == "creature_hp" else None
    it.created_at = datetime.now(UTC) - timedelta(hours=2)
    db.flush()
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(rule, "live"), (rule, "waiting")]  # (an hour on: put back)
    again = db.scalars(select(BridgeIntent).where(BridgeIntent.state == "waiting", BridgeIntent.character_id == labs.id)).one()
    again.state = "dismissed"  # (Undo on its corner card)
    db.flush()
    characters.refresh(db, labs)
    assert maxima(db, labs) == [(rule, "live"), (rule, "dismissed")]  # (undone: never made again)
    page = player.get(f"/characters/{labs.id}/battle?creature={ZAP}").text
    assert f"askdnd's <b>{rule}</b>, the rule's, was undone" in page and "−/+" in page and "askdnd sets" not in page
