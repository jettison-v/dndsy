"""The Product Taxonomy (app/data/taxonomy.json, app/fft/taxonomy.py; Brett, Nov 18, docs/mockups/product-taxonomy/: two
levels, a batch of fixes per Product Area, Feedback grouped by Product Area): the list is sound and docs/MAP.md follows
it, an issue's Feature puts it in its Product Area's batch, and the pages show it."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules, taxonomy, views
from app.fft.models import FftArea, FftEvent, FftIssue, FftItem, FftTryIssue
from app.importer import import_bundle
from app.main import app
from tests.table_setup import BUNDLE

ROOT = taxonomy.FILE.parent.parent.parent
CLAUDE = "c" * 40


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


# ------------------------------------------------------------------ the list, and docs/MAP.md


def test_the_list_is_two_levels_with_keys_that_fit():
    raw = json.loads(taxonomy.FILE.read_text())["areas"]
    keys = [a["key"] for a in raw] + [f["key"] for a in raw for f in a["features"]]
    assert len(keys) == len(set(keys)), "a key is used twice"
    assert all(re.fullmatch(r"[a-z][a-z0-9]{1,19}", k) for k in keys), "keys are short, lower case, no spaces (they're stored on issues)"
    assert all(a["features"] and a["title"] and a["what"] for a in raw)
    assert taxonomy.path("hp") == "Battle › Hit points" and taxonomy.path("") == "" and taxonomy.path("gone") == ""


def test_docs_map_is_ordered_by_the_list_and_every_section_has_one_feature():
    """docs/MAP.md: a heading per Product Area in the list's order, then Everywhere; each top-level section is named in
    exactly one Feature's `map`, and sits under that Feature's Product Area, in the Features' order."""
    text = (ROOT / "docs" / "MAP.md").read_text()
    heads = re.findall(r"^## (.+)$", text, re.M)
    assert heads == [a.title for a in taxonomy.areas()] + ["Everywhere"]
    claimed = [(t, f) for a in taxonomy.areas() for f in a.features for t in f.map]
    names = [t for t, _ in claimed]
    assert len(names) == len(set(names)), "a section is named by two Features"
    for a, part in zip(taxonomy.areas(), re.split(r"^## .+$", text, flags=re.M)[1:], strict=False):
        found = re.findall(r"^- \*\*([^*]+)\*\*", part, re.M)
        assert found == [t for f in a.features for t in f.map], f"{a.title}'s sections, in its Features' order"


# ------------------------------------------------------------------ a Feature puts an issue in its batch


def test_a_feature_puts_an_issue_in_its_product_areas_batch_made_when_first_needed(db):
    assert db.scalar(select(FftArea).where(FftArea.key == "battle")) is None
    issue = rules.new_issue(db, "claude", "Temp HP box is cramped", feature="hp")
    battle = db.get(FftArea, issue.area_id)
    item = db.get(FftItem, battle.item_id)
    assert battle.key == "battle" and battle.title == "Battle" and item.standing and item.title == "Fixes and polish"
    other = rules.new_issue(db, "claude", "Death saves reset", feature="death")
    assert other.area_id == battle.id  # (one batch per Product Area)
    rules.set_feature(db, "claude", other, "dice")
    assert db.get(FftArea, other.area_id).key == "rolls" and other.feature == "dice"
    with pytest.raises(rules.RuleError):
        rules.set_feature(db, "claude", other, "nonsense")
    ev = db.scalars(select(FftEvent).where(FftEvent.kind == "issue_feature", FftEvent.thing_id == other.id).order_by(FftEvent.id)).all()[-1]
    assert "to" not in ev.data  # (an issue event's "to" is its state: the record's replay reads it)
    assert views.event_words(ev) == f"Issue {other.id} is about Rolls and dice › Dice (was Battle › Death saves)"


def test_an_issue_in_a_builds_batch_stays_there_and_its_checks_follow_it(db):
    build = FftItem(title="The Roadmap in askdnd", section="next", place=5)
    db.add(build)
    db.flush()
    batch = FftArea(item_id=build.id, title="Build", place=1)
    db.add(batch)
    db.flush()
    inbuild = rules.new_issue(db, "claude", "Order by drag", area_id=batch.id, feature="roadmap")
    assert inbuild.area_id == batch.id and inbuild.feature == "roadmap"
    loose = rules.new_issue(db, "claude", "Loose")
    check = rules.write_check(db, "claude", title="Try it", steps=["Press [Go]."], expect="It goes.", issue_ids=[loose.id])
    assert check.area_id is None
    rules.set_feature(db, "claude", loose, "search")
    assert check.area_id == loose.area_id and db.get(FftArea, loose.area_id).key == "around"
    later = rules.write_check(db, "claude", title="Again", steps=["Press [Go]."], expect="It goes.", issue_ids=[loose.id])
    assert later.area_id == loose.area_id  # (a check is tried with its issues' batch)


def test_a_product_areas_batch_follows_the_list(db):
    issue = rules.new_issue(db, "claude", "x", feature="hp")
    battle = db.get(FftArea, issue.area_id)
    for change in (lambda: rules.rename_area(db, "claude", battle, "Sheets"), lambda: rules.archive_area(db, "claude", battle),
                   lambda: rules.move_area(db, "claude", battle, db.get(FftItem, battle.item_id)),
                   lambda: rules.merge_area(db, "claude", battle, db.get(FftArea, rules.new_issue(db, "claude", "y", feature="dice").area_id))):
        with pytest.raises(rules.RuleError):
            change()
    battle.title = "Old name"
    assert taxonomy.batch(db, "battle").title == "Battle"  # (a renamed Product Area renames its batch)


def test_an_issue_found_on_a_check_starts_with_what_the_check_tries(db):
    first = rules.new_issue(db, "claude", "Rest wraps", feature="resources")
    rules.fix_ready(db, "claude", first, "https://github.com/jettison-v/dndsy/pull/1")
    check = rules.write_check(db, "claude", title="Rest on one line", steps=["Press [Rest]."], expect="One line.", issue_ids=[first.id])
    rules.preflight(db, "claude", check, True)
    t = rules.record_try(db, "user:1", check, result="failed", found=[rules.Found(title="The Rest button overlaps")])
    found = db.get(FftIssue, db.scalar(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == t.id)))
    assert found.feature == "resources" and found.area_id == first.area_id


# ------------------------------------------------------------------ Claude's side and the pages


def test_claude_gives_an_issue_its_feature_and_filters_by_it(db, admin, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    before = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        api = TestClient(app)
        h = {"X-Fft-Key": CLAUDE}
        made = api.post("/api/fft/issues", headers=h, json={"title": "Cramped", "feature": "hp"}).json()
        assert made["feature"] == "hp" and made["feature_path"] == "Battle › Hit points"
        loose = api.post("/api/fft/issues", headers=h, json={"title": "Loose"}).json()
        assert api.post(f"/api/fft/issues/{loose['id']}", headers=h, json={"do": "feature", "feature": "nope"}).status_code == 400
        assert api.post(f"/api/fft/issues/{loose['id']}", headers=h, json={"do": "feature", "feature": "search"}).json()["feature"] == "search"
        assert [i["id"] for i in api.get("/api/fft/issues?feature=hp", headers=h).json()["items"]] == [made["id"]]
        keys = [x["key"] for it in api.get("/api/fft/areas", headers=h).json()["items"] for x in it["areas"]]
        assert set(keys) == {"battle", "around"}
    finally:
        app.dependency_overrides[get_db] = before


def test_feedback_groups_issues_by_product_area_and_change_moves_one(db, admin):
    hp = rules.new_issue(db, "claude", "Temp HP box is cramped", feature="hp")
    dice = rules.new_issue(db, "claude", "Dice land off the tray", feature="dice")
    loose = rules.new_issue(db, "claude", "Something new")
    db.flush()
    page = admin.get("/manage/feedback?tab=open").text
    assert 'data-pa-chips' in page and 'data-pa="battle"' in page and 'data-pa="rolls"' in page and 'data-pa="story"' not in page
    groups = re.findall(r'data-group="([^"]*)"', page)
    assert groups == ["", "battle", "rolls"]  # (no Feature yet first, then the list's order)
    only = admin.get("/manage/feedback?tab=open&pa=battle").text
    assert f'data-row="i{hp.id}"' in only and f'data-row="i{dice.id}"' not in only and 'data-feat-tray="battle"' in only
    assert 'data-feature="hp"' in only and 'data-feature="death"' not in only  # (only Features with something open)
    issue = admin.get(f"/manage/item/i{loose.id}").text  # (one issue: the item window)
    assert "No Feature yet" in issue and 'data-feature-pick' in issue and '<optgroup label="Battle">' in issue
    admin.post(f"/manage/feedback/issues/{loose.id}", data={"do": "feature", "feature": "menus"})
    assert loose.feature == "menus" and db.get(FftArea, loose.area_id).key == "around"
    assert admin.post(f"/manage/feedback/issues/{loose.id}", data={"do": "feature", "feature": "nope"}).status_code == 400
    batch = db.get(FftArea, hp.area_id)
    assert 'data-pa="battle"' in admin.get(f"/manage/feedback?tab=open&area={batch.id}").text  # (Where it stands' Open link)


def test_feedbacks_filters_are_one_row_and_each_one_on_is_a_pill_clear_takes_off(db, admin):
    """Brett's pick P1 A (docs/mockups/our-work-audit/, Nov 24): Open · Ready to try, Filters ▾ and what's on, one row;
    each filter that's on is a pill whose × takes it off, a build's own list (Where it stands' link) too, and Clear takes
    them all off."""
    hp = rules.new_issue(db, "claude", "Temp HP box is cramped", feature="hp")
    it = rules.new_item(db, "claude", "A build", section="now")
    db.flush()
    plan = rules.new_area(db, "claude", it, "A build: the build")
    db.flush()
    built = rules.new_issue(db, "claude", "Its button is off", area_id=plan.id)
    db.flush()
    page = admin.get("/manage/feedback?tab=open").text
    row = page.split("data-filter-row", 1)[1].split("</details>", 1)[0]
    assert 'data-views' in row and 'data-filter-menu' in row and 'data-chip="fix"' in row and 'data-pa="battle"' in row
    assert "data-filter-on" not in page and "data-filter-clear" not in page  # (nothing on: no pills, no Clear)
    on = admin.get("/manage/feedback?tab=open&chip=fix&pa=battle&feature=hp").text
    assert [m for m in re.findall(r'data-filter-on="(\w+)"', on)] == ["chip", "pa", "feature"]
    assert 'href="?tab=open&amp;pa=battle&amp;feature=hp" data-filter-on="chip"' in on
    assert 'href="?tab=open" data-filter-clear' in on and 'data-tab="ready"' in on and 'href="?tab=ready&amp;chip=fix&amp;pa=battle&amp;feature=hp"' in on
    build = admin.get(f"/manage/feedback?tab=open&area={plan.id}").text
    assert f'data-row="i{built.id}"' in build and f'data-row="i{hp.id}"' not in build
    assert 'href="?tab=open" data-filter-on="area"' in build and "A build: the build" in build and 'href="?tab=open" data-filter-clear' in build


def test_product_areas_page_and_where_it_stands_show_the_list(db, admin):
    rules.new_issue(db, "claude", "Temp HP box is cramped", feature="hp")
    rules.new_issue(db, "claude", "Loose")
    db.flush()
    page = admin.get("/manage/product-areas").text
    assert page.count('class="panel pa-card"') == len(taxonomy.areas()) and "data-loose" in page
    assert 'href="/manage/feedback?tab=open&amp;pa=battle&amp;feature=hp"' in page
    work = admin.get("/manage/work?tab=queue").text  # (each plan says its open issues' Features)
    assert "Hit points" in work and 'data-stage="' in work
    assert "Product Area" in admin.get("/manage/askdnd").text  # (its Overview card)


def test_product_areas_is_for_admins(db, dm, player):
    for who in (dm, player):
        assert "pa-cards" not in who.get("/manage/product-areas").text
