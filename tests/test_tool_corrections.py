"""Tool corrections: an admin regroups a sheet item (side panel) or fixes how askdnd reads one, everywhere it
shows; Manage › Tool corrections lists them as a fix list."""

import pytest
from sqlalchemy import select

from app import characters
from app.importer import import_bundle
from tests.table_setup import BUNDLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_side_panel_for_everything_and_admin_regrouping(player, admin, db):
    from app.models import ToolCorrection

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert "data-panel-url=\"/characters/%d/detail?ref=" % cole.id in page and "<details class=\"opt" not in page
    for ref in ("spell:Barkskin", "feature:Druid:Wild Shape", "action:Wild Shape", "attack:unarmed",
                cole.snapshot.summary["inventory"][0]["key"], cole.snapshot.summary["situational"][0]["key"], "form:Polar Bear"):
        r = player.get(f"/characters/{cole.id}/detail", params={"ref": ref})
        assert r.status_code == 200 and "<html" not in r.text and 'class="mech"' in r.text, ref
    wild = player.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    assert "for 3 hours" in wild  # D&D Beyond's formula {{(classlevel/2)@rounddown}} filled in
    assert "regroup for every character" not in wild
    assert player.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "x", "field": "battle", "value": "hide"}).status_code == 403
    admin.post(f"/characters/{cole.id}/override", data={"ref": "feature:Wood Elf:Fleet of Foot", "oref": "feature:Fleet of Foot",
                                                        "field": "feature_group", "value": "use"})
    features = player.get(f"/characters/{cole.id}").text.split('id="t-features"')[1].split('id="t-situ"')[0]
    fleet = next(r for r in features.split(' data-ls-row ')[1:] if "<b>Fleet of Foot</b>" in r)
    assert 'data-group-label="Wood Elf"' in fleet  # regrouped: now with the features you use
    assert "regroup for every character" in admin.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    admin.post(f"/characters/{cole.id}/override", data={"ref": "attack:unarmed", "oref": "attack:Unarmed Strike", "field": "battle", "value": "hide"})
    assert "Unarmed Strike" not in player.get(f"/characters/{cole.id}/battle").text.split("Bonus action")[0]
    assert db.scalar(select(ToolCorrection).where(ToolCorrection.ref == "attack:Unarmed Strike")).set_by == "admin@example.com"


def test_universal_regrouping_and_the_tool_corrections_page(player, admin, db):
    from app.models import ToolCorrection

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    panel = admin.get(f"/characters/{cole.id}/detail", params={"ref": cole.snapshot.summary["inventory"][-1]["key"]}).text
    assert "Show in askdnd" in panel and "Inventory group" in panel  # gear is clickable and can be regrouped
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "item:Bag of Holding", "field": "item_group", "value": "Gear"})
    items = player.get(f"/characters/{cole.id}").text.split('id="t-items"')[1].split('id="t-features"')[0]
    bag = next(r for r in items.split(' data-ls-row ')[1:] if "Bag of Holding" in r)
    assert 'data-group-label="Gear"' in bag  # no longer under Equipped
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "spell:Heat Metal", "field": "hide", "value": "hide"})
    assert "Heat Metal" not in player.get(f"/characters/{cole.id}").text
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "spell:Healing Word", "field": "cost", "value": "Action"})
    page = admin.get("/manage/tool-corrections").text
    assert "Bag of Holding" in page and "Heat Metal" in page and "Undo" in page
    o = db.scalar(select(ToolCorrection).where(ToolCorrection.ref == "spell:Heat Metal"))
    admin.post(f"/manage/tool-corrections/overrides/{o.id}/delete")
    assert "Heat Metal" in player.get(f"/characters/{cole.id}").text
    assert player.get("/manage/tool-corrections").status_code == 403
    assert player.post(f"/characters/{cole.id}/link", data={"ddb_link": "1"}).status_code == 403


def test_saving_a_regrouping_returns_only_that_setting(admin, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    r = admin.post(f"/characters/{cole.id}/override", data={"ref": "feature:Druid:Wild Shape", "oref": "feature:Wild Shape",
                                                            "field": "feature_group", "value": "passive"})
    assert r.status_code == 200 and r.text.strip().startswith('<div class="ov-field">') and "peek-head" not in r.text
    assert "✓ Saved" in r.text and 'class="ov-opt on" aria-pressed="true"' in r.text and "Saved for every character" in r.headers["HX-Trigger"]
    panel = admin.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    assert panel.count('class="ov-field"') == 2  # Show in askdnd + Features group, each saved on its own


def test_tool_corrections_are_a_fix_list(admin, db):
    """Brett, 2026-10-23: a correction patches askdnd until its code gets it right; then it shows as built in."""
    from app.models import ToolCorrection

    import_bundle(db, BUNDLE)
    characters.refresh(db, char(db, "Cole"))
    db.add_all([ToolCorrection(ref="item:Arrows", field="item_group", value="Weapons"),      # ammunition: built in
                ToolCorrection(ref="spell:Healing Word", field="cost", value="Action"),      # still askdnd's mistake
                ToolCorrection(ref="spell:Divine Smite", field="battle", value="common")])   # nobody here has it
    db.flush()
    page = admin.get("/manage/tool-corrections").text
    needs, built = page.split("<h2>Built into askdnd</h2>")
    assert "Healing Word" in needs and "Arrows" not in needs and "Arrows" in built and "Remove" in built
    assert "Divine Smite" in needs and "no character has it now" in needs
    assert "1 tool correction to build into askdnd" in admin.get("/c/main/manage", follow_redirects=True).text  # not the unseen one
