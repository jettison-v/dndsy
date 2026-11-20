"""The Roadmap in askdnd (Brett's picks, Nov 20, docs/mockups/roadmap-in-askdnd/): ideas that need discussion, each with
its scope as versions, Brett's additions and Claude's answers, his one OK, steps his or Claude's, and the plans
building it; done is History. Claude writes it from chat through the API; only Brett says a scope looks right."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules, testing_page
from app.fft.models import FftAddition, FftIdea, FftItem, FftNote
from app.importer import import_bundle
from app.main import app
from tests.table_setup import BUNDLE

CLAUDE = "c" * 40


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    before = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides[get_db] = before


H = {"X-Fft-Key": CLAUDE}


def _scoped(db, title="The Roadmap in askdnd"):
    it = rules.new_idea(db, "claude", title, "Record items and work them.", where="chat")
    rules.write_scope(db, "claude", it, what="Roadmap items inside askdnd.", inside=["Items by section", "Steps"], not_now=["Players"])
    db.flush()
    return it


def test_an_idea_is_scoped_in_versions_and_brett_says_it_looks_right(db, admin):
    it = _scoped(db)
    add = rules.add_to_item(db, "user:1", it, "Make it its own page.", user_id=None)
    rules.write_scope(db, "claude", it, what="Roadmap items inside askdnd.", inside=["Its own page"], changed="Its own page, from your addition")
    rules.answer_addition(db, "claude", add, "in", "Its own page in Our work.", scope_version=2)
    db.flush()
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-version="2"' in page and 'data-ver="1"' in page and "What changed in v2" in page and 'data-answer="in"' in page
    assert 'data-do="agree"' in page
    assert "v1" in admin.get(f"/manage/roadmap/{it.id}?ver=1").text
    r = admin.post(f"/manage/roadmap/{it.id}", data={"do": "agree", "seen": 1}, follow_redirects=False)  # (read an old version: refused)
    assert r.status_code == 303 and rules.latest_scope(db, it).agreed_at is None
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "agree", "seen": 2})
    assert rules.latest_scope(db, it).agreed_at is not None
    assert 'data-do="agree"' not in admin.get(f"/manage/roadmap/{it.id}").text


def test_the_roadmap_lists_open_items_by_section_and_done_is_history(db, admin):
    now = rules.new_idea(db, "claude", "Found, Fixed, Tried", section="now")
    later = rules.new_idea(db, "claude", "The component library", section="later")
    shipped = rules.new_idea(db, "claude", "The menu bar")
    rules.ship_item(db, "claude", shipped)
    db.flush()
    page = admin.get("/manage/roadmap").text
    assert page.index(f'data-item="{now.id}"') < page.index(f'data-item="{later.id}"') and f'data-item="{shipped.id}"' not in page
    assert 'data-section="now"' in page and 'data-stage-word="idea"' in page and "data-history" in page
    hist = admin.get("/manage/roadmap?history=1").text
    assert f'data-item="{shipped.id}"' in hist and "data-history-head" in hist and f'data-item="{now.id}"' not in hist
    admin.post(f"/manage/roadmap/{later.id}", data={"do": "move", "section": "paused"})
    assert later.section == "paused"
    assert "data-move" in admin.get(f"/manage/roadmap/{now.id}").text


def test_new_idea_and_additions_from_askdnd(db, admin):
    assert 'name="title"' in admin.get("/manage/roadmap/new").text
    r = admin.post("/manage/roadmap", data={"title": "A weekly digest", "words": "Email the table's notes weekly.", "section": "next"}, follow_redirects=False)
    it = db.scalar(select(FftItem).where(FftItem.title == "A weekly digest"))
    assert r.headers["location"] == f"/manage/roadmap/{it.id}"
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "add", "words": "Only for admins."})
    words = [a.words for a in db.scalars(select(FftAddition).where(FftAddition.item_id == it.id).order_by(FftAddition.id))]
    assert words == ["Email the table's notes weekly.", "Only for admins."]
    assert admin.post("/manage/roadmap", data={"title": " ", "section": "next"}).status_code == 400


def test_steps_carry_it_out_and_bretts_wait_in_for_you(db, admin):
    it = _scoped(db)
    db.flush()
    rows = [r for g in testing_page.for_you(db, "laptop") for r in g["rows"]]
    assert any(r["key"] == f"r{it.id}" and r["kind"] == "scope" for r in rows)  # (a scope waiting for his OK)
    win = admin.get(f"/manage/item/r{it.id}").text
    assert 'data-do="agree"' in win
    rules.agree_scope(db, "user:1", it)
    mine = rules.add_step(db, "claude", it, "Try it on askdnd.ai", whose="brett")
    rules.add_step(db, "claude", it, "Build the pages")
    db.flush()
    assert it.next_whose == "brett"  # (its next step is Brett's: R15 skips it)
    rows = [r for g in testing_page.for_you(db, "laptop") for r in g["rows"]]
    assert any(r["key"] == f"r{it.id}" and r["kind"] == "roadmap" for r in rows)
    assert 'data-step="' in admin.get(f"/manage/roadmap/{it.id}?tab=steps").text
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "tick", "step": mine.id})
    assert mine.done_at is not None and it.next_whose == "claude"
    rows = [r for g in testing_page.for_you(db, "laptop") for r in g["rows"]]
    assert not any(r["key"] == f"r{it.id}" for r in rows)


def test_a_note_becomes_a_roadmap_idea_and_undo_takes_it_back(db, admin):
    note = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="idea", text="Could the dice make a sound?")
    db.flush()
    assert "A Roadmap idea" in admin.get(f"/manage/item/n{note.id}").text
    admin.post(f"/manage/feedback/notes/{note.id}", data={"do": "idea"})
    idea = db.get(FftIdea, note.idea_id)
    it = db.get(FftItem, idea.item_id)
    assert idea.state == "roadmap" and it.title and db.scalar(select(FftAddition.words).where(FftAddition.item_id == it.id)) == note.text
    assert 'data-tab="ideas"' not in admin.get("/manage/feedback?tab=open").text  # (no Ideas tab: ideas are the Roadmap's)
    admin.post(f"/manage/feedback/notes/{note.id}/undo")
    assert db.get(FftNote, note.id).state == "waiting" and db.get(FftItem, it.id) is None


def test_claude_writes_the_roadmap_from_chat_and_never_agrees(db, api):
    made = api.post("/api/fft/roadmap", headers=H, json={"title": "Scheduled jobs report", "words": "Wire the jobs to Work.", "size": "M"}).json()
    iid = made["id"]
    assert made["stage"] == "idea" and made["size"] == "M"
    got = api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "scope", "what": "Each job reports its run.", "inside": ["The Mini", "GitHub"], "changed": ""}).json()
    assert got["stage"] == "scoping" and got["scope_version"] == 1
    assert api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "agree"}).status_code == 403  # (only Brett)
    api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "add", "words": "Backups too."})
    whole = api.get(f"/api/fft/roadmap/{iid}", headers=H).json()
    add = whole["additions"][-1]
    assert add["where"] == "chat" and add["words"]["by"] == "Brett" and whole["unanswered"] == 2
    api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "answer", "addition": add["id"], "answer": "in", "words": "Backups too.", "version": 2})
    api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "step", "text": "Report from the Mini"})
    step = api.get(f"/api/fft/roadmap/{iid}", headers=H).json()["steps"][0]
    assert api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "tick", "step": step["id"]}).json()["steps"] == [1, 1]
    assert [x["id"] for x in api.get("/api/fft/roadmap", headers=H).json()["items"]] == [iid]
    assert api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "move", "section": "sideways"}).status_code == 400
    assert api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "ship"}).status_code == 400  # (no result: Brett, Nov 20)
    api.post(f"/api/fft/roadmap/{iid}", headers=H, json={"do": "ship", "result": "Every job reports its run.\nBackups too."})
    assert api.get("/api/fft/roadmap", headers=H).json()["items"] == [] and api.get("/api/fft/roadmap?history=1", headers=H).json()["items"]
    assert api.get("/api/fft/roadmap").status_code == 404  # (no key)


def test_ideas_from_before_are_placed_on_the_roadmap_or_as_an_improvement(db, api):
    a = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="idea", text="A dice sound.")
    b = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="idea", text="Show temp HP beside the total.")
    ia, ib = rules.file_idea(db, "user:1", a), rules.file_idea(db, "user:1", b)
    db.flush()
    assert {x["id"] for x in api.get("/api/fft/ideas", headers=H).json()["items"]} == {ia.id, ib.id}
    item = api.post(f"/api/fft/ideas/{ia.id}", headers=H, json={"do": "roadmap"}).json()["item"]
    issue = api.post(f"/api/fft/ideas/{ib.id}", headers=H, json={"do": "improvement"}).json()["issue"]
    assert db.get(FftItem, item).title and db.get(FftNote, b.id).issue_id == issue and api.get("/api/fft/ideas", headers=H).json()["items"] == []


def test_the_one_order_puts_now_before_later_however_dragged(db):
    later = rules.new_idea(db, "claude", "Later one", section="later")
    now = rules.new_idea(db, "claude", "Now one", section="now")
    rules.order_items(db, "user:1", [later.id, now.id])  # (dragged in the Later section: its place is first)
    db.flush()
    got = list(db.scalars(select(FftItem.id).where(FftItem.id.in_([later.id, now.id])).order_by(rules.item_rank(), FftItem.place)))
    assert got == [now.id, later.id]


def test_a_standing_rule_the_roadmap_is_for_admins_only(db, dm, player):
    """A standing rule (Brett, Nov 16: the tool is admins'): the DM and a player get no Roadmap and change nothing."""
    it = _scoped(db)
    for who in (dm, player):
        for path in ("/manage/roadmap", f"/manage/roadmap/{it.id}", "/manage/roadmap/new"):
            r = who.get(path)
            assert r.status_code in (303, 403, 404) or "data-fft-page" not in r.text, path
        who.post(f"/manage/roadmap/{it.id}", data={"do": "agree", "seen": 1})
        who.post("/manage/roadmap", data={"title": "Theirs", "section": "next"})
    assert rules.latest_scope(db, it).agreed_at is None and db.scalar(select(FftItem).where(FftItem.title == "Theirs")) is None


def test_a_shipped_item_says_what_it_changed_with_its_numbers(db, admin, api):
    """Brett, Nov 20: "do you write a result after each item is completed? It should include results, such as how much
    performance improved": the first line the headline, a line per result; on its page and in History; a shipped item
    without one is a gap of Claude's (Claude missed)."""
    from app.fft import views

    it = rules.new_idea(db, "claude", "Performance: the whole tool", section="now")
    db.flush()
    api.post(f"/api/fft/roadmap/{it.id}", headers=H, json={"do": "set", "result": "Pages about 74% quicker\nTool corrections 5.8 s → 0.8 s"})
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-result="so-far"' in page and "Tool corrections 5.8 s → 0.8 s" in page
    other = rules.new_idea(db, "claude", "The menu bar")
    rules.ship_item(db, "user:1", other)  # (Brett's own Shipped press: no result yet)
    db.flush()
    assert any(g["kind"] == "no_result" and g["id"] == other.id for g in views.gaps(db))
    assert 'data-result="none"' in admin.get(f"/manage/roadmap/{other.id}").text
    api.post(f"/api/fft/roadmap/{other.id}", headers=H, json={"do": "set", "result": "One bar, one way to show where you are"})
    rules.ship_item(db, "claude", it, result="Pages about 74% quicker\nTool corrections 5.8 s → 0.8 s")
    db.flush()
    assert not any(g["kind"] == "no_result" for g in views.gaps(db))
    hist = admin.get("/manage/roadmap?history=1").text
    assert "Pages about 74% quicker" in hist and "One bar, one way to show where you are" in hist
    assert 'data-result="done"' in admin.get(f"/manage/roadmap/{it.id}").text
