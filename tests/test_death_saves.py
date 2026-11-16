"""Death saving throws (app/death_saves.py, roadmap step 6; Brett, 2026-10-29, docs/mockups/death-saves.html): the marks
kept on the sheet through the bridge, a death save that marks itself, damage and healing at 0 in the hit points window,
and a reminder as a dying character's turn starts."""

from sqlalchemy import select

from app import characters, ddb_bridge, death_saves, hit_points
from app.models import BridgeIntent, Campaign
from tests.table_setup import char


def hit(n):
    return [{"amount": n, "type": ""}]


AT_0 = {"current": 0, "max": 51, "temp": 0}


def test_dropping_to_0_starts_unconscious_crossable_for_a_ruling():
    w = hit_points.work({"current": 7, "max": 51, "temp": 0}, "damage", hit(12), [], set())
    assert w["down"] and w["unconscious"] and not w["death_fail"]
    step = next(s for s in w["steps"] if s.get("key") == "unconscious")
    assert step["value"] == "Unconscious" and "next turn" in step["why"]
    assert not hit_points.work({"current": 7, "max": 51, "temp": 0}, "damage", hit(12), [], {"unconscious"})["unconscious"]


def test_damage_at_0_is_a_failure_a_critical_hit_two():
    """2024 Player's Handbook, Damage at 0 Hit Points; while Stable, the saves start over."""
    w = hit_points.work(AT_0, "damage", hit(8), [], set(), death={"success": 1, "fail": 1, "stable": False})
    assert w["death_fail"] == 1 and not w["unconscious"] and "makes 2" in w["steps"][-1]["why"]
    w = hit_points.work(AT_0, "damage", hit(8), [], set(), death={"success": 0, "fail": 1, "stable": False}, crit=True)
    assert w["death_fail"] == 2 and "the DM rules" in w["steps"][-1]["why"]  # three
    w = hit_points.work(AT_0, "damage", hit(8), [], set(), death={"success": 3, "fail": 2, "stable": True})
    assert "start over" in w["steps"][-1]["why"] and "makes 1" in w["steps"][-1]["why"]
    assert hit_points.work(AT_0, "damage", hit(8), [], {"death"})["death_fail"] == 0  # crossed out


def test_massive_damage_marks_nothing_and_names_it_for_the_dm():
    w = hit_points.work(AT_0, "damage", hit(51), [], set())
    assert w["massive"] == 51 and not w["death_fail"] and w["steps"][-1]["title"] == "Massive damage"
    w = hit_points.work({"current": 7, "max": 31, "temp": 0}, "damage", hit(45), [], set())
    assert w["massive"] == 38 and w["unconscious"]


def test_healing_from_0_ends_unconscious_and_clears_the_marks():
    w = hit_points.work(AT_0, "heal", hit(5), [], set())
    assert w["up"] and any(s.get("key") == "unconscious" and s["value"] == "Unconscious ends" for s in w["steps"])
    assert not hit_points.work(AT_0, "heal", hit(5), [], {"unconscious"})["up"]
    assert not hit_points.work({"current": 3, "max": 51, "temp": 0}, "heal", hit(5), [], set())["up"]


def test_what_a_death_save_counts_as():
    assert [death_saves.outcome(t, n) for t, n in ((14, None), (9, None), (10, None), (1, 1), (20, 20))] == \
        ["success", "failure", "success", "nat1", "nat20"]


def down(db, sheet, success=0, fail=0):
    """Cole at 0 Hit Points on D&D Beyond, with these marks."""
    sheet["removedHitPoints"] = 51
    sheet["deathSaves"] = {"successCount": success, "failCount": fail, "isStabilized": False}
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    return cole


def made(db, cole):
    """What the bridge would make on Cole's sheet now: each field's end value."""
    rows = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id).order_by(BridgeIntent.id))
    return ddb_bridge.plan([{"kind": it.kind, "data": it.data} for it in rows], ddb_bridge.numbers(cole))[0]


def test_the_sheet_tells_the_marks(db, sheet):
    cole = down(db, sheet, 2, 1)
    st = death_saves.state(characters.character_summary(cole))
    assert st == {"success": 2, "fail": 1, "stable": False, "out": False}


def test_a_death_save_rolled_at_the_table_marks_itself_and_a_reroll_moves_it(player, db, sheet, monkeypatch):
    """Brett, 2026-10-29 (question 1, A): the player pressed Roll for it, and the rule says what it counts as."""
    from app import table_rolls

    cole = down(db, sheet, 1, 0)
    dice = iter([6, 15])  # a failure, then Heroic Inspiration rerolls it into a success
    monkeypatch.setattr(table_rolls, "die", lambda n: next(dice) if n == 20 else 1)
    r = player.post("/rolls", data={"character": cole.id, "kind": "death", "label": "Death save"})
    assert r.status_code == 200 and "a failure (1 ✓ · 1 ✗)" in r.json()["death"]["text"]
    assert made(db, cole)["death"] == {"successCount": 1, "failCount": 1}
    rid = r.json()["roll"]["id"]
    r = player.post("/rolls", data={"parent": rid, "action": "reroll", "label": "Heroic Inspiration"})
    assert r.status_code == 200 and "a success (2 ✓ · 0 ✗)" in r.json()["death"]["text"]
    assert made(db, cole)["death"] == {"successCount": 2, "failCount": 0}


def test_a_natural_20_brings_you_back_with_1_hit_point(player, db, sheet):
    cole = down(db, sheet, 0, 2)
    r = player.post(f"/characters/{cole.id}/death", data={"result": "nat20"})  # rolled privately, in the browser
    assert r.status_code == 200 and "back up with 1 Hit Point" in r.json()["text"]
    end = made(db, cole)
    assert end["hp"]["removedHitPoints"] == 50 and end["death"] == {"successCount": 0, "failCount": 0}


def test_stable_or_at_three_failures_nothing_more_is_marked(player, db, sheet):
    cole = down(db, sheet, 3, 0)
    assert player.post(f"/characters/{cole.id}/death", data={"result": "failure"}).status_code == 204
    cole = down(db, sheet, 0, 3)
    assert player.post(f"/characters/{cole.id}/death", data={"result": "success"}).status_code == 204
    assert not db.scalars(select(BridgeIntent)).all()


def test_with_hit_points_a_death_save_marks_nothing(player, db, sheet):
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/death", data={"result": "failure"}).status_code == 204


def test_only_the_characters_player_marks_a_private_roll(dm, db, sheet):
    cole = down(db, sheet)
    assert dm.post(f"/characters/{cole.id}/death", data={"result": "failure"}).status_code == 404


def test_the_hit_points_window_marks_damage_at_0_and_unconscious(player, db, sheet):
    """Brett, 2026-10-29 (questions 2 and 3, A): applying marks the failures; dropping to 0 starts Unconscious; healing
    from 0 ends it and clears the marks."""
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "damage", "amount": "40"})
    assert r.status_code == 200 and "down to 0, Unconscious" in r.headers["HX-Trigger"]
    end = made(db, cole)
    assert end["hp"]["removedHitPoints"] == 51 and end[death_saves.UNCONSCIOUS] is True

    db.query(BridgeIntent).delete()
    cole = down(db, sheet, 0, 1)
    page = player.get(f"/characters/{cole.id}/hp?mode=damage").text
    assert "A critical hit" in page
    player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "damage", "amount": "6", "crit": "1"})
    assert made(db, cole)["death"] == {"successCount": 0, "failCount": 3}

    db.query(BridgeIntent).delete()
    player.post(f"/characters/{cole.id}/hp/apply", data={"mode": "heal", "amount": "5"})
    end = made(db, cole)
    assert end["hp"]["removedHitPoints"] == 46 and end["death"] == {"successCount": 0, "failCount": 0}


def test_battle_shows_the_dying_tile_and_party_how_others_can_help(player, dm, db, sheet):
    cole = down(db, sheet, 2, 1)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "Dying" in page and page.count('class="ds-pip s"') == 2 and page.count('class="ds-pip f"') == 1
    assert 'data-roll="death"' in page
    party = dm.get("/party").text
    assert "Dying" in party and "DC 10 Wisdom (Medicine)" in party
    cole = down(db, sheet, 3, 0)
    assert "Stable" in player.get(f"/characters/{cole.id}/battle").text


def test_a_dying_characters_turn_starts_with_a_reminder(player, dm, db, sheet):
    from app import fight
    from tests.roles import set_role

    cole = down(db, sheet, 1, 2)
    campaign = db.get(Campaign, cole.campaign_id)
    set_role(db, "dm@example.com", "dm")
    order = [{"key": "t-e1", "name": "Enemy 1", "kind": "monster", "initiative": 15},
             {"key": "t-cole", "name": "Cole", "kind": "character", "ddb_id": cole.ddb_id, "initiative": 12}]
    for turn in (1, 2):
        fight.heard(db, campaign, {"round": 1, "turn": turn, "order": [{**x, "active": i == turn - 1} for i, x in enumerate(order)]})
    db.commit()
    mine = fight.for_person(db, campaign, "player@example.com")
    r = next(x for x in mine["reminders"] if x["kind"] == "death")
    assert r["mine"] and "1 ✓ · 2 ✗" in r["text"]
    assert any(x["down"] for x in mine["order"] if x.get("character") == cole.id)  # its token: 0 HP
    assert not next(x for x in fight.for_person(db, campaign, "dm@example.com")["reminders"] if x["kind"] == "death")["mine"]


def test_healing_from_0_outside_the_window_ends_unconscious_too(player, db, sheet):
    """Review, 2026-10-29: a heal made through the bridge's own controls (a potion, the bridge page) also ends
    Unconscious and clears the marks."""
    cole = down(db, sheet, 1, 2)
    sheet["conditions"] = [{"id": 15, "level": None}]
    characters.refresh(db, cole)
    assert player.post(f"/bridge/hp/{cole.id}", data={"amount": "4"}).status_code == 200
    end = made(db, cole)
    assert end["hp"]["removedHitPoints"] == 47 and end["death"] == {"successCount": 0, "failCount": 0}
    assert end[death_saves.UNCONSCIOUS] is False


# ---- the bug-planting check (Nov 15): each count and its edges, without D&D Beyond

class Marked:
    """What death_saves asks of the bridge and the fight, the character dying with these marks."""

    def __init__(self, monkeypatch, success=0, fail=0, stable=None, hp=0):
        self.calls = []
        stable = success >= 3 if stable is None else stable  # (as the sheet reader has it: ddb_sheet.death_saves)
        summary = {"hit_points": {"current": hp, "max": 20}, "death_saves": {"success": success, "fail": fail, "stable": stable}}
        monkeypatch.setattr(death_saves.ddb_bridge, "on_for", lambda db, ch: True)
        monkeypatch.setattr(death_saves.ddb_bridge, "reachable", lambda ch: True)
        monkeypatch.setattr(death_saves.chars, "character_summary", lambda ch: summary)
        monkeypatch.setattr(death_saves.ddb_bridge, "as_shown", lambda db, ch, s: s)
        monkeypatch.setattr(death_saves.ddb_bridge, "add", lambda db, ch, kind, data, label: self.calls.append(("add", kind, data)))
        monkeypatch.setattr(death_saves, "tell", lambda db, ch, kind, text: self.calls.append(("tell", kind)))

    def marks(self):
        return [c[2]["value"] for c in self.calls if c[0] == "add" and c[2].get("field") == "death"]


COLE_ISH = type("Ch", (), {"id": 1, "name": "Cole", "campaign_id": 1, "conditions": None})


def test_a_third_success_is_stable_and_a_third_failure_the_dms_ruling(monkeypatch):
    m = Marked(monkeypatch, success=2)
    assert "Stable" in death_saves.roll(None, COLE_ISH(), "success")
    assert m.marks() == [{"successCount": 3, "failCount": 0}] and ("tell", "stable") in m.calls
    m = Marked(monkeypatch, fail=2)
    assert "three" in death_saves.roll(None, COLE_ISH(), "nat1")
    assert m.marks() == [{"successCount": 0, "failCount": 3}] and ("tell", "out") in m.calls  # (at most three)
    m = Marked(monkeypatch, success=1, fail=1)
    death_saves.roll(None, COLE_ISH(), "failure")
    assert m.marks() == [{"successCount": 1, "failCount": 2}] and not [c for c in m.calls if c[0] == "tell"]


def test_a_reroll_takes_the_first_result_off_before_marking_its_own(monkeypatch):
    m = Marked(monkeypatch, success=1, fail=1)
    death_saves.roll(None, COLE_ISH(), "success", replaces="failure")  # (the failure off, then a success)
    assert m.marks() == [{"successCount": 2, "failCount": 0}]
    m = Marked(monkeypatch, success=0, fail=3)
    death_saves.roll(None, COLE_ISH(), "success", replaces="nat1")  # (the third failure was the reroll's: not out any more)
    assert m.marks() == [{"successCount": 1, "failCount": 1}]
    m = Marked(monkeypatch, success=3)
    death_saves.roll(None, COLE_ISH(), "failure", replaces="success")  # (Stable came from it: rolling again)
    assert m.marks() == [{"successCount": 2, "failCount": 1}]
    m = Marked(monkeypatch, success=1)
    assert death_saves.roll(None, COLE_ISH(), "success", replaces="success") == "" and m.marks() == []  # (the same: nothing)
    m = Marked(monkeypatch, success=3)
    assert death_saves.roll(None, COLE_ISH(), "failure") == "" and m.marks() == []  # (Stable: no more saves)


def test_damage_at_0_counts_failures_and_restarts_them_while_stable(monkeypatch):
    m = Marked(monkeypatch, success=1, fail=2)
    death_saves.hit(None, COLE_ISH(), 2, "crit")
    assert m.marks() == [{"successCount": 1, "failCount": 3}]
    m = Marked(monkeypatch, success=3, fail=1, stable=True)
    death_saves.hit(None, COLE_ISH(), 1, "hit")
    assert m.marks() == [{"successCount": 0, "failCount": 1}]  # (Stable: the saves start over)
    m = Marked(monkeypatch, hp=5)  # (not at 0 on the sheet: from none)
    death_saves.hit(None, COLE_ISH(), 1, "hit")
    assert m.marks() == [{"successCount": 0, "failCount": 1}]


def test_back_up_clears_askdnds_own_unconscious_and_keeps_the_rest(monkeypatch):
    m = Marked(monkeypatch)
    ch = COLE_ISH()
    ch.conditions = [{"name": "Unconscious"}, {"name": "Poisoned"}]
    death_saves.up(None, ch, 5, "healed")
    assert ch.conditions == [{"name": "Poisoned"}]
    assert m.calls[0] == ("add", "hp", {"amount": 5}) and m.marks() == [{"successCount": 0, "failCount": 0}]
    m = Marked(monkeypatch)
    death_saves.down(None, ch)
    assert m.marks() == [{"successCount": 0, "failCount": 0}] and any(c[2].get("value") is True for c in m.calls)


def test_the_sheets_marks_read_with_their_gaps():
    assert death_saves.state({"hit_points": {"current": 0}}) == {"success": 0, "fail": 0, "stable": False, "out": False}
    assert death_saves.state({"hit_points": {"max": 20}}) is None  # (no current given: not at 0)
    assert death_saves.state({"hit_points": {"current": 0}, "death_saves": {"success": 3}})["stable"] is False  # (the sheet's own flag)
    assert death_saves.state({"hit_points": {"current": 0}, "death_saves": {"fail": 3}})["out"] is True
    assert death_saves.state({"hit_points": {"current": 0}, "death_saves": {"fail": 2}})["out"] is False
