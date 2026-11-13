"""Tool corrections and house rules (data organization step 3): a campaign's rulings point at the tool's knowledge
and never edit it; the effective value is tool knowledge, then a tool correction, then the house rule."""

import itertools

import pytest
from sqlalchemy import select

from app import characters, history, house_rules
from app import roll_recipes as rr
from app import table_rolls as tr
from app.importer import import_bundle
from app.models import Campaign, HouseRule, Revision, ToolCorrection
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def rule(db, key, field, value="1", reason="", campaign=None):
    campaign = campaign or db.scalar(select(Campaign).order_by(Campaign.id))
    r = HouseRule(campaign_id=campaign.id, target_kind="spell", target_key=key, field=field, value=value, reason=reason, set_by="Mary")
    db.add(r)
    db.flush()
    return r


def test_no_house_rule_means_the_audited_recipe(db):
    import_bundle(db, BUNDLE)
    assert house_rules.spell("Magic Missile") is rr.spell("Magic Missile")
    assert house_rules.spell("Not a spell") is None


def test_one_roll_for_all_darts_changes_only_this_campaign(db):
    import_bundle(db, BUNDLE)
    other = Campaign(slug="other", name="Other")
    db.add(other)
    rule(db, "Magic Missile", "once", reason="Faster at our table")
    mm = house_rules.spell("Magic Missile")
    assert mm["events"][0]["note"] == "Aim them at one creature or several"  # no longer "rolled on its own"
    assert mm["events"][0]["once"] and mm["house_rules"] == [
        {"text": "One roll for all darts: every dart deals the same damage", "reason": "Faster at our table", "by": "Mary"}]
    assert "once" not in rr.spell("Magic Missile")["events"][0]  # the tool's knowledge is untouched
    db.flush()
    assert house_rules.spell("Magic Missile", other.id) is rr.spell("Magic Missile")  # another campaign: as written


def test_one_roll_only_where_something_is_rolled_more_than_once(db):
    import_bundle(db, BUNDLE)
    rule(db, "Scorching Ray", "once")  # each ray has its own attack roll: not offered, and ignored if stored
    assert not house_rules.can_roll_once(rr.spell("Scorching Ray")) and house_rules.can_roll_once(rr.spell("Magic Missile"))
    assert "house_rules" not in house_rules.spell("Scorching Ray")


def test_one_roll_reuses_the_first_darts_dice():
    rolls = itertools.cycle([1, 4, 2])
    each = tr.roll_parts(["1d4+1 force"], 3, each="dart", roll=lambda sides: next(rolls))
    assert [p["total"] for p in each["parts"]] == [2, 5, 3] and each["total"] == 10
    rolls = itertools.cycle([4, 1, 2])
    once = tr.roll_parts(["1d4+1 force"], 3, each="dart", roll=lambda sides: next(rolls), once=True)
    assert [p["total"] for p in once["parts"]] == [5, 5, 5] and once["total"] == 15
    assert [p["label"] for p in once["parts"]] == ["Dart 1", "Dart 2", "Dart 3"]


def test_a_ruling_shows_in_the_roll_window_of_the_spell(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    characters.refresh(db, cole)
    rule(db, "Healing Word", "note", value="Heals at the start of your next turn too")
    page = player.get(f"/characters/{cole.id}").text + player.get(f"/characters/{cole.id}/spellbook").text
    assert "Heals at the start of your next turn too" in page and "house_rules" in page


def test_only_the_dm_and_admins_set_house_rules(player, admin, dm, db):
    """A standing rule: the DM makes every ruling, so only the DM (and admins) set house rules."""
    import_bundle(db, BUNDLE)
    assert player.get("/c/main/manage/house-rules").status_code == 403
    assert dm.get("/c/main/manage/house-rules").status_code == 403  # a reviewer (dm@ is on the Railway reviewer list) isn't the DM
    set_role(db, "dm@example.com", "dm")
    page = dm.get("/c/main/manage/house-rules").text
    assert "No house rules yet" in page and "One roll for all darts" in page and ">Magic Missile<" in page
    assert player.post("/manage/house-rules", data={"spell": "Magic Missile", "field": "once"}).status_code == 403
    dm.post("/manage/house-rules", data={"spell": "Magic Missile", "field": "once", "reason": "Faster"})
    row = db.scalar(select(HouseRule))
    assert (row.target_key, row.field, row.value, row.reason, row.set_by) == ("Magic Missile", "once", "1", "Faster", "dm")
    assert "One roll for all darts: every dart deals the same damage" in admin.get("/c/main/manage/house-rules").text
    assert "House rules" in dm.get("/c/main/manage").text
    dm.post("/manage/house-rules", data={"spell": "Scorching Ray", "field": "once"})  # refused: each ray has an attack roll
    dm.post("/manage/house-rules", data={"spell": "Shield", "field": "note", "value": ""})  # refused: no ruling written
    assert db.scalar(select(HouseRule).where(HouseRule.target_key != "Magic Missile")) is None


def test_removing_a_house_rule_brings_the_rules_back_and_history_can_restore_it(admin, db):
    import_bundle(db, BUNDLE)
    r = rule(db, "Magic Missile", "once", reason="Faster")
    admin.post(f"/manage/house-rules/{r.id}/delete")
    assert db.scalar(select(HouseRule)) is None and house_rules.spell("Magic Missile") is rr.spell("Magic Missile")
    rev = db.scalar(select(Revision).where(Revision.table == "house_rules", Revision.field == "deleted"))
    assert rev.label == "House rule: Magic Missile"
    assert "House rule: Magic Missile" in admin.get("/c/main/manage/history?show=house").text
    history.restore(db, rev)
    assert house_rules.spell("Magic Missile")["house_rules"][0]["reason"] == "Faster"


def test_a_campaigns_house_rule_wins_over_a_tool_correction(db):
    import_bundle(db, BUNDLE)
    db.add(ToolCorrection(ref="feature:Fleet of Foot", field="feature_group", value="always"))
    campaign = db.scalar(select(Campaign))
    db.add(HouseRule(campaign_id=campaign.id, target_kind="sheet", target_key="feature:Fleet of Foot", field="feature_group", value="use"))
    db.add(ToolCorrection(ref="spell:Moonbeam", field="battle", value="hide"))
    db.flush()
    assert house_rules.sheet_overrides(db) == {("feature:Fleet of Foot", "feature_group"): "use", ("spell:Moonbeam", "battle"): "hide"}


def test_tool_corrections_say_why(admin, db):
    import_bundle(db, BUNDLE)
    o = ToolCorrection(ref="spell:Moonbeam", field="battle", value="hide")
    db.add(o)
    db.flush()
    admin.post(f"/manage/tool-corrections/overrides/{o.id}/reason", data={"reason": "  D&D Beyond   lists it twice "})
    assert o.reason == "D&D Beyond lists it twice"
    page = admin.get("/manage/tool-corrections").text
    assert "Tool corrections" in page and 'value="D&amp;D Beyond lists it twice"' in page
