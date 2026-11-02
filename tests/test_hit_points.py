"""Hit points with the working, aware of Wild Shape (app/hit_points.py, roadmap step 5.4): the 2024 rules as one tested
function, the DM's rolls heard from D&D Beyond's game log, and Apply from Table rolls through the bridge."""

from sqlalchemy import select

from app import ddb_bridge, hit_points
from app.models import BridgeIntent, TableRoll
from tests.roles import set_role
from tests.table_setup import char

FULL = {"current": 51, "max": 51, "temp": 0}
COLD = [{"key": "form:resistance:cold", "kind": "resistance", "type": "cold", "from": "the Polar Bear"}]


def hit(n, t=""):
    return [{"amount": n, "type": t}]


def test_resistance_halves_rounded_down_immunity_and_vulnerability():
    w = hit_points.work(FULL, "damage", hit(23, "cold"), COLD, set())
    assert (w["taken"], w["hp_after"]) == (11, 40)
    assert w["parts"][0]["steps"][0]["value"] == "23 → 11"
    assert hit_points.work(FULL, "damage", hit(23, "fire"), COLD, set())["taken"] == 23  # (another type)
    imm = [{"key": "own:immunity:poison", "kind": "immunity", "type": "poison", "from": "your sheet"},
           {"key": "own:resistance:poison", "kind": "resistance", "type": "poison", "from": "your sheet"}]
    assert hit_points.work(FULL, "damage", hit(30, "poison"), imm, set())["taken"] == 0
    both = [{"key": "a", "kind": "vulnerability", "type": "fire", "from": "x"}, {"key": "b", "kind": "resistance", "type": "fire", "from": "y"}]
    assert hit_points.work(FULL, "damage", hit(9, "fire"), both, set())["taken"] == 8  # halved first (4), then doubled


def test_a_crossed_out_defense_is_a_ruling():
    w = hit_points.work(FULL, "damage", hit(23, "cold"), COLD, {"form:resistance:cold"})
    assert w["taken"] == 23 and w["parts"][0]["steps"][0]["off"]


def test_temporary_hit_points_first_and_the_form_stays():
    form = {"beast": {"name": "Polar Bear"}}
    w = hit_points.work({"current": 51, "max": 51, "temp": 18}, "damage", hit(30, "piercing"), COLD, set(), form)
    assert (w["temp_after"], w["hp_after"]) == (0, 39)
    assert any(s["title"] == "Out of Temporary Hit Points" and "Polar Bear" in s["value"] for s in w["steps"])
    w = hit_points.work({"current": 51, "max": 51, "temp": 18}, "damage", hit(10), [], set(), form)
    assert (w["temp_after"], w["hp_after"]) == (8, 51) and not any(s["title"].startswith("Out of") for s in w["steps"])


def test_concentration_dc_is_ten_or_half_the_damage_up_to_thirty():
    save = {"bonus": 7, "label": "+7", "adv": True, "why": "War Caster"}
    assert hit_points.work(FULL, "damage", hit(11), [], set(), None, "Moonbeam", save)["conc"]["dc"] == 10
    assert hit_points.work(FULL, "damage", hit(44), [], set(), None, "Moonbeam", save)["conc"]["dc"] == 22
    assert hit_points.work({**FULL, "max": 300, "current": 300}, "damage", hit(90), [], set(), None, "Moonbeam", save)["conc"]["dc"] == 30
    w = hit_points.work({**FULL, "temp": 10}, "damage", hit(6), [], set(), None, "Moonbeam", save)
    assert w["conc"]["dc"] == 10  # (damage the Temporary Hit Points took is still damage taken)
    assert hit_points.work(FULL, "damage", hit(0), [], set(), None, "Moonbeam", save)["conc"] is None


def test_at_zero_and_massive_damage_are_pointed_out():
    w = hit_points.work({"current": 5, "max": 20, "temp": 0}, "damage", hit(12), [], set())
    assert w["down"] and not w["massive"]
    w = hit_points.work({"current": 5, "max": 20, "temp": 0}, "damage", hit(25), [], set())
    assert w["massive"] == 20 and "kills outright" in w["steps"][-1]["why"]


def test_healing_stops_at_the_maximum_and_temporary_hit_points_dont_add_up():
    assert hit_points.work({"current": 40, "max": 51, "temp": 5}, "heal", hit(20), [], set())["hp_after"] == 51
    assert hit_points.work({**FULL, "temp": 7}, "temp", hit(10), [], set())["temp_after"] == 10  # the higher
    assert hit_points.work({**FULL, "temp": 7}, "temp", hit(5), [], set())["temp_after"] == 7
    assert hit_points.work({**FULL, "temp": 7}, "temp", hit(5), [], set(), temp_take=True)["temp_after"] == 5  # you choose


def test_a_monsters_attack_names_its_damage_type():
    """D&D Beyond's roll carries no damage type (checked Oct 28), so it comes from the attack in the rules data, which
    it names (Brett, Oct 28: what D&D Beyond doesn't give is shown as looked up)."""
    assert hit_points.attack_type(None, None, "Ogre", "Greatclub") == ("bludgeoning", "SRD 5.2.1")
    assert hit_points.attack_type(None, None, "Ogre", "Javelin", "2d6+4") == ("piercing", "SRD 5.2.1")
    assert hit_points.attack_type(None, None, "Nobody", "Greatclub") == ("", "")


def game_roll(rid="g-1", entity="monster", eid="4904825", name="Ogre", action="Greatclub", kind="damage", total=17, scope="gameId"):
    """A roll as D&D Beyond's game log brings it to a sheet in the game (the shape heard on Oct 28)."""
    return {"eventType": "dice/roll/fulfilled", "entityType": entity, "entityId": eid, "messageScope": scope, "messageTarget": "8215895",
            "data": {"rollId": rid, "action": action, "context": {"entityType": entity, "name": name}, "rolls": [{
                "diceNotation": {"constant": 4, "set": [{"count": 2, "dieType": "d8", "dice": [{"dieType": "d8", "dieValue": 6}, {"dieType": "d8", "dieValue": 7}]}]},
                "rollType": kind, "rollKind": "", "result": {"total": total}}]}}


def test_the_dms_rolls_in_the_game_come_into_table_rolls_once(player, dm, db, sheet):
    """Heard on a player's open sheet: the monster's damage with its type, kept once however many sheets hear it."""
    assert player.post("/bridge/others-roll/75423618", json=game_roll()).json() == {"ok": True}
    assert player.post("/bridge/others-roll/75423618", json=game_roll()).json() == {"ok": False}  # (heard again)
    row = db.scalar(select(TableRoll).where(TableRoll.ddb_roll_id == "g-1"))
    assert (row.who, row.label, row.kind, row.total, row.character_id, row.parts[0]["kind"]) == ("Ogre", "Greatclub", "damage", 17, None, "bludgeoning")
    html = dm.get("/rolls").text
    assert "Ogre" in html and "bludgeoning" in html and "(SRD 5.2.1)" in html and "the DM" in html
    assert player.post("/bridge/others-roll/75423618", json=game_roll("g-2", entity="user", eid="1")).json() == {"ok": False}  # plain dice
    assert dm.post("/bridge/others-roll/75423618", json=game_roll("g-3")).json() == {"ok": False}  # only the player's own browser
    cole = char(db, "Cole")  # a roll for Cole made on another page (the encounter's) is his
    assert player.post("/bridge/others-roll/75423618", json=game_roll("g-4", entity="character", eid="75423618", kind="check", action="Athletics")).json() == {"ok": True}
    assert db.scalar(select(TableRoll.character_id).where(TableRoll.ddb_roll_id == "g-4")) == cole.id


def test_apply_to_cole_works_it_out_and_makes_it_through_the_bridge(player, dm, db, sheet):
    """A standing rule (Brett, 2026-10-28): normally the player applies a hit, the DM can too; a roll is applied once to
    each character; the Concentration save is the player's to roll, on their screen, also when the DM applied it."""
    cole = char(db, "Cole")
    cole.concentration = {"spell": "Moonbeam", "key": "moonbeam", "level": 2, "round": 1, "rounds": 10}
    db.commit()
    player.post("/bridge/others-roll/75423618", json=game_roll())
    rid = db.scalar(select(TableRoll.id).where(TableRoll.ddb_roll_id == "g-1"))
    assert f"/characters/{cole.id}/hp?roll={rid}" in player.get("/rolls").text  # Apply to Cole
    page = player.get(f"/characters/{cole.id}/hp?roll={rid}").text
    assert "Ogre · Greatclub" in page and "Take 17" in page and "Concentration: Moonbeam" in page and "DC 10" in page
    assert "bludgeoning is the Ogre's Greatclub in SRD 5.2.1" in page  # looked up, and it says so
    r = player.post(f"/characters/{cole.id}/hp/apply", data={"roll": rid, "mode": "damage", "amount": "17", "type": "bludgeoning"})
    assert r.status_code == 200 and "closePanel" in r.headers["HX-Trigger"]
    it = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == cole.id))
    assert (it.kind, it.data) == ("hp", {"amount": -17})
    assert player.post(f"/characters/{cole.id}/hp/apply", data={"roll": rid, "mode": "damage", "amount": "17"}).status_code == 409  # once
    rolls = player.get("/rolls").text
    assert "Cole took 17" in rolls and "Concentration (Moonbeam), DC 10" in rolls and "Roll the save" in rolls
    assert "Roll the save" not in dm.get("/rolls").text  # (the player's to roll)

    set_role(db, "dm@example.com")  # the DM applies the next one, from Apply to…
    player.post("/bridge/others-roll/75423618", json=game_roll("g-2", total=9))
    rid2 = db.scalar(select(TableRoll.id).where(TableRoll.ddb_roll_id == "g-2"))
    assert f"/characters/{cole.id}/hp?roll={rid2}" in dm.get("/rolls").text
    assert dm.post(f"/characters/{cole.id}/hp/apply", data={"roll": rid2, "mode": "damage", "amount": "9"}).status_code == 200
    assert "Roll the save" in player.get("/rolls").text


def test_without_a_reachable_sheet_nothing_is_applied(player, db, sheet):
    """Decided 2026-10-28: a change for D&D Beyond is taken only while the sheet can be reached."""
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.commit()
    assert "can't be reached" in player.get(f"/characters/{cole.id}/hp?mode=damage").text
    assert player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "damage", "amount": "5"}).status_code == 409
    assert not db.scalars(select(BridgeIntent)).all()


def test_someone_elses_character_has_no_hit_points_window(monkeypatch, db, sheet):
    from tests.table_setup import sign_in
    other = sign_in(monkeypatch, db, "someone@example.com")
    assert other.get(f"/characters/{char(db, 'Cole').id}/hp").status_code == 404


def test_temporary_hit_points_are_set_on_d_and_d_beyond(player, db, sheet):
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "temp", "amount": "18"}).status_code == 200
    it = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == cole.id))
    assert (it.kind, it.data) == ("temp", {"value": 18})
    vals, _, _, _ = ddb_bridge.plan([{"kind": "temp", "data": {"value": 18}}], ddb_bridge.numbers(cole))
    assert vals["hp"]["temporaryHitPoints"] == 18 and vals["hp"]["removedHitPoints"] == 14


def test_typing_an_amount_starts_keep_or_take_again_on_the_higher(player, db, sheet):
    """Nov 2, found by the live test: the window opened on "Keep 0" with no amount yet, and typing 5 left it there, so
    Set stayed at 0. A choice holds for the amount it was made on."""
    cole = char(db, "Cole")
    work = lambda **f: player.post(f"/characters/{cole.id}/hp/work", data={"mode": "temp", **f}).text
    assert "Set 5 temp" in work(amount="5", take="0", take_for="0")  # (typed after the window opened)
    assert "Set 0 temp" in work(amount="5", take="0", take_for="5")  # kept on purpose
    assert player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "temp", "amount": "5", "take": "0", "take_for": "0"}).status_code == 200
    it = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == cole.id))
    assert (it.kind, it.data) == ("temp", {"value": 5})


def test_in_a_wild_shape_form_its_resistances_count(player, db, sheet):
    """Cole as a Polar Bear (Circle of the Moon): the Bear's Cold resistance halves a cold hit."""
    cole = char(db, "Cole")
    cole.wild_shape = "Polar Bear"
    db.commit()
    page = player.get(f"/characters/{cole.id}/hp?mode=damage").text
    assert "Polar Bear" in page and "resists or is immune" in page
    r = player.post(f"/characters/{cole.id}/hp/work", data={"mode": "damage", "amount": "22", "type": "cold"}).text
    assert "Resistant to cold" in r and "22 → 11" in r and "the Polar Bear" in r


def test_a_characters_own_damage_offers_no_apply_but_healing_does(player, db, sheet):
    """Damage the DM rolled hits the party; a character's own damage goes to enemies. Healing comes from anyone."""
    cole = char(db, "Cole")
    for rid, kind in (("own-dmg", "damage"), ("own-heal", "heal")):
        db.add(TableRoll(campaign_id=cole.campaign_id, character_id=cole.id, label="Roll", kind=kind, formula="1d8", dice=[5], total=5, ddb_roll_id=rid))
    db.commit()
    ids = dict(db.execute(select(TableRoll.ddb_roll_id, TableRoll.id).where(TableRoll.ddb_roll_id.like("own-%"))).all())
    html = player.get("/rolls").text
    assert f"hp?roll={ids['own-heal']}" in html and f"hp?roll={ids['own-dmg']}" not in html


def test_d_and_d_beyonds_attack_and_its_damage_show_as_one(player, dm, db, sheet):
    """Brett, 2026-10-29 (no guessing): D&D Beyond rolls an attack and its damage separately; the damage joins the attack
    only as the same roller's very next roll for the same attack, to the same people, within two minutes, so Table
    rolls shows them together (and Apply sits on the attack). Anything else stays a roll of its own."""
    send = lambda **k: player.post("/bridge/others-roll/75423618", json=game_roll(**k))  # noqa: E731
    send(rid="a-1", kind="to hit", total=19)
    send(rid="d-1", kind="damage", total=17)
    attack = db.scalar(select(TableRoll).where(TableRoll.ddb_roll_id == "a-1"))
    assert db.scalar(select(TableRoll.parent_id).where(TableRoll.ddb_roll_id == "d-1")) == attack.id
    assert f"/hp?roll={attack.id}" in player.get("/rolls").text  # Apply on the attack, with its damage
    send(rid="a-2", kind="to hit", total=8)
    send(rid="x-1", kind="check", action="Strength", total=12)  # something else in between
    send(rid="d-2", kind="damage", total=11)
    assert db.scalar(select(TableRoll.parent_id).where(TableRoll.ddb_roll_id == "d-2")) is None
    send(rid="a-3", kind="to hit", action="Javelin", total=15)
    send(rid="d-3", kind="damage", action="Greatclub", total=9)  # another attack's name
    assert db.scalar(select(TableRoll.parent_id).where(TableRoll.ddb_roll_id == "d-3")) is None


def test_minus_and_plus_on_battles_tile_open_the_small_window(player, dm, db, sheet):
    """Brett, 2026-11-01 (docs/mockups/hp-flow/ Option B): − and + go straight to the window, ready to type in; the DM has them too."""
    cole = char(db, "Cole")
    page = player.get(f"/characters/{cole.id}/battle").text
    assert f"/characters/{cole.id}/hp?mode=damage&amp;quick=1" in page and f"/characters/{cole.id}/hp?mode=heal&amp;quick=1" in page
    set_role(db, "dm@example.com")
    assert f"/characters/{cole.id}/hp?mode=damage&amp;quick=1" in dm.get(f"/characters/{cole.id}/battle").text
    small = player.get(f"/characters/{cole.id}/hp?mode=heal&quick=1").text
    assert 'class="rp-x"' in small and "peek-head" not in small and "autofocus" in small and 'value="heal" checked' in small


def test_inspiration_is_spent_and_given_through_the_bridge_with_a_question_first(player, dm, db, sheet):
    """Brett, 2026-11-01: the star asks first, then changes it on D&D Beyond; the DM can give it too."""
    cole = char(db, "Cole")
    assert f'data-use-url="/characters/{cole.id}/inspiration"' in player.get(f"/characters/{cole.id}/battle").text
    window = player.get(f"/characters/{cole.id}/inspiration").text
    assert "Give it" in window or "Spend it" in window
    have = "Spend it" in window
    assert player.post(f"/characters/{cole.id}/inspiration", data={"to": "gain" if have else "spend"}).status_code == 409  # already so
    done = player.post(f"/characters/{cole.id}/inspiration", data={"to": "spend" if have else "gain"})
    assert done.status_code == 200 and done.json()["undo"] == {"to": "gain" if have else "spend"}
    intent = db.scalars(select(BridgeIntent)).all()[-1]
    assert intent.kind == "set" and intent.data["field"] == "inspiration" and intent.data["value"] is (not have)
    set_role(db, "dm@example.com")
    assert dm.get(f"/characters/{cole.id}/inspiration").status_code == 200


def test_without_a_reachable_sheet_inspiration_stays_as_it_is(player, db, sheet):
    """Decided 2026-10-28: a change for D&D Beyond is taken only while the sheet can be reached."""
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.commit()
    assert "can't be reached" in player.get(f"/characters/{cole.id}/inspiration").text
    assert player.post(f"/characters/{cole.id}/inspiration", data={"to": "gain"}).status_code == 409

