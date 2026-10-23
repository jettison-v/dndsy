"""Tool corrections and house rules (data organization step 3): a campaign's rulings point at the tool's knowledge
and never edit it; the effective value is tool knowledge, then a tool correction, then the house rule."""

import itertools
import subprocess

from sqlalchemy import select, text

from app import characters, history, house_rules
from app import roll_recipes as rr
from app import table_rolls as tr
from app.importer import import_bundle
from app.models import Campaign, HouseRule, Revision, ToolCorrection
from tests.roles import set_role
from tests.test_characters import BUNDLE, admin, char, client, dm, no_network, owned_by, player  # noqa: F401


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
    import_bundle(db, BUNDLE)
    assert player.get("/manage/house-rules").status_code == 403
    assert dm.get("/manage/house-rules").status_code == 403  # a reviewer (dm@ is on the Railway reviewer list) isn't the DM
    set_role(db, "dm@example.com", "dm")
    page = dm.get("/manage/house-rules").text
    assert "No house rules yet" in page and "One roll for all darts" in page and ">Magic Missile<" in page
    assert player.post("/manage/house-rules", data={"spell": "Magic Missile", "field": "once"}).status_code == 403
    dm.post("/manage/house-rules", data={"spell": "Magic Missile", "field": "once", "reason": "Faster"})
    row = db.scalar(select(HouseRule))
    assert (row.target_key, row.field, row.value, row.reason, row.set_by) == ("Magic Missile", "once", "1", "Faster", "dm")
    assert "One roll for all darts: every dart deals the same damage" in admin.get("/manage/house-rules").text
    assert "House rules" in dm.get("/manage").text
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
    assert "House rule: Magic Missile" in admin.get("/admin/history?show=house").text
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


def test_migration_renames_sheet_corrections_and_adds_house_rules(db_engine):
    url = db_engine.url.render_as_string(hide_password=False)
    env = {"DATABASE_URL": url, "PATH": __import__("os").environ["PATH"]}
    from app.db import Base

    def alembic(*args):
        r = subprocess.run(["alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    Base.metadata.drop_all(db_engine)
    try:
        alembic("upgrade", "ab6c8d2e5f71")
        with db_engine.begin() as c:
            c.execute(text("INSERT INTO sheet_overrides (ref, field, value, set_by) VALUES ('spell:Moonbeam', 'battle', 'hide', 'b@x')"))
        alembic("upgrade", "head")
        with db_engine.begin() as c:
            assert c.execute(text("SELECT ref, field, value, reason FROM tool_corrections")).all() == [("spell:Moonbeam", "battle", "hide", "")]
            c.execute(text("INSERT INTO tool_corrections (ref, field, value) VALUES ('spell:Shield', 'battle', 'hide')"))  # ids continue
        alembic("downgrade", "ab6c8d2e5f71")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM sheet_overrides")).scalar() == 2
        alembic("upgrade", "head")
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)
