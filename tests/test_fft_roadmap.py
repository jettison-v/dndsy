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


def test_comments_on_a_scope_wait_for_bretts_answer_then_needs_changes_is_claudes_turn(db, admin, api):
    """Issue 54 (Brett, Nov 20: "There is no place for me to say the scope isn't OK or to add additional comments"; his
    picks on docs/mockups/roadmap-scope-review/): a comment on a line or the whole is his own until he answers the
    scope; Needs changes… sends them and it's Claude's turn to answer each one and write the next version."""
    from app.fft import views

    it = _scoped(db)
    db.flush()
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-line="in:0"' in page and 'data-do="changes"' in page and 'data-do="agree"' in page and "data-general" in page
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "in:0", "words": "Sections, or one long list?"})
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "words": "Keep it small."})
    held = list(db.scalars(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.held.is_(True))))
    assert len(held) == 2 and {a.on_line for a in held} == {"in:0", ""} and held[0].on_version == 1
    assert all(a["words"]["quoted"] != "Keep it small." for a in api.get(f"/api/fft/roadmap/{it.id}", headers=H).json()["additions"])  # (not Claude's yet)
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-held="2"' in page and 'data-line="in:0"' in page and 'class="rm-line has"' in page
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "changes", "seen": 1, "words": "And drop players."})
    assert not db.scalar(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.held.is_(True)))
    assert rules.latest_scope(db, it).changes_at is not None
    whole = api.get(f"/api/fft/roadmap/{it.id}", headers=H).json()
    assert whole["stage"] == "revising" and whole["changes_asked"] and {a["on"] for a in whole["additions"]} >= {"in:0", ""}
    rows = [r for g in testing_page.for_you(db, "laptop") for r in g["rows"]]
    assert not any(r["key"] == f"r{it.id}" for r in rows)  # (Claude's turn: off his For you)
    assert any(g["kind"] == "scope_changes" and g["id"] == it.id for g in views.gaps(db))
    assert "data-changes-asked" in admin.get(f"/manage/roadmap/{it.id}").text
    rules.write_scope(db, "claude", it, what="Smaller.", inside=["Items by section"], changed="From your comments")
    db.flush()
    assert not any(g["kind"] == "scope_changes" for g in views.gaps(db)) and 'data-do="changes"' in admin.get(f"/manage/roadmap/{it.id}").text


def test_open_questions_are_answered_in_place_and_go_with_the_ok(db, admin, api):
    """Issue 54: an answer under each open question, Claude's suggestion a press away; a second answer replaces the first,
    an empty one takes it back, and Scope looks right sends it."""
    it = rules.new_idea(db, "claude", "Usage limits", section="now")
    api.post(f"/api/fft/roadmap/{it.id}", headers=H, json={"do": "scope", "what": "Stop before a limit.", "inside": ["A setting"],
                                                           "questions": ["Which limit?", "Pause or stop?"], "suggest": ["85% of the week", ""]})
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-question="1"' in page and 'value="85% of the week"' in page and page.count('data-do="use-suggestion"') == 1
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "q:0", "words": "85% of the week"})
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "q:0", "words": "80% of the week"})
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "q:1", "words": "Pause"})
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "q:1", "words": ""})
    answers = list(db.scalars(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.on_line.like("q:%"))))
    assert [(a.on_line, a.words, a.held) for a in answers] == [("q:0", "80% of the week", True)]
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "agree", "seen": 1})
    assert rules.latest_scope(db, it).agreed_at is not None and not answers[0].held
    got = api.get(f"/api/fft/roadmap/{it.id}", headers=H).json()
    assert got["scopes"][0]["suggested"] == ["85% of the week", ""] and any(a["on"] == "q:0" for a in got["additions"])
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "words": "One more thing."})  # (after his OK: straight to Claude)
    assert not db.scalar(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.held.is_(True)))


def test_needs_changes_says_what_and_a_comment_can_be_taken_back(db, admin):
    it = _scoped(db)
    db.flush()
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "changes", "seen": 1})  # (nothing said: refused)
    assert rules.latest_scope(db, it).changes_at is None
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "what", "words": "Too broad."})
    a = db.scalar(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.on_line == "what"))
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "drop", "addition": a.id})
    assert db.get(FftAddition, a.id) is None
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "comment", "on": "in:9", "words": "No such line."})
    assert not db.scalar(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.on_line == "in:9"))
    rules.write_scope(db, "claude", it, what="v2", inside=["One"])
    db.flush()
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "agree", "seen": 1})  # (read v1 while v2 came: refused, R14)
    assert rules.latest_scope(db, it).agreed_at is None


def test_discuss_with_claude_opens_a_new_session_about_the_item(db, admin, api, monkeypatch):
    """Issue 54 (Brett's pick 4): a new Claude Code session with a message about the item filled in, on this Mac
    (claude://code/new, in the project's folder) or on claude.ai/code with its repo; it writes back as a discussion."""
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setattr(config, "DISCUSS_FOLDER", "/Users/someone/Code/project")
    it = _scoped(db)
    db.flush()
    assert 'data-do="discuss"' in admin.get(f"/manage/roadmap/{it.id}").text
    win = admin.get(f"/manage/roadmap/{it.id}/discuss").text
    import html
    mac = html.unescape(win.split('data-open="mac"')[0].rsplit('href="', 1)[1].split('"')[0])
    web = html.unescape(win.split('data-open="web"')[0].rsplit('href="', 1)[1].split('"')[0])
    q = parse_qs(urlparse(mac).query)
    assert mac.startswith("claude://code/new?") and q["folder"] == ["/Users/someone/Code/project"] and f"roadmap {it.id}" in q["q"][0]
    assert "--where discussion" in q["q"][0] and "Never say the scope looks right" in q["q"][0]
    w = parse_qs(urlparse(web).query)
    assert web.startswith("https://claude.ai/code/new?") and w["repo"] == [config.DISCUSS_REPO] and w["q"] == q["q"]
    api.post(f"/api/fft/roadmap/{it.id}", headers=H, json={"do": "add", "words": "Sections, not a list.", "where": "discussion"})
    assert db.scalar(select(FftAddition.where).where(FftAddition.item_id == it.id).order_by(FftAddition.id.desc())) == "discussion"


def test_a_roadmap_row_in_for_you_says_why_it_is_yours_and_opens_the_item(db, admin):
    """Brett, Nov 20: "I don't understand why roadmap items that have confirmed scope remain in For You table and what the
    actual next steps are. The navigation is also circular and you never actually get to the roadmap item." Its window
    says where it stands and why the step is his, and its links go to the item on the Roadmap, never back to For you."""
    it = _scoped(db)
    rules.agree_scope(db, "user:1", it)
    rules.add_step(db, "claude", it, "Audit the roll card", whose="brett")
    db.flush()
    win = admin.get(f"/manage/item/r{it.id}?from=foryou").text
    assert 'data-stage-word="agreed"' in win and 'data-sec="steps"' in win and 'data-do="open-page"' in win
    assert f'href="/manage/roadmap/{it.id}"' in win and "/manage/for-you?open=" not in win


def test_scope_it_puts_an_unscoped_item_first_in_claudes_queue_until_its_scope_is_written(db, admin, api):
    """Scope it (issue 60, Brett's pick Nov 21): an item with no scope offers it; one press puts the item first in Claude's
    queue and in Claude's hands, Not now takes it back, and its first version ends it."""
    from app.fft import views

    it = rules.new_idea(db, "claude", "Homebrew items", "Easier builder.", where="chat")
    db.flush()
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-scope-none' in page and 'data-do="scope-it"' in page and 'data-stage-word="idea"' in page
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "scope_it"})
    db.refresh(it)
    assert it.scope_asked_at is not None
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert 'data-scope-asked' in page and 'data-stage-word="asked"' in page and 'data-do="not-now"' in page
    assert rules.pick_next(db).item.id == it.id
    assert any(g["kind"] == "scope_asked" and g["id"] == it.id for g in views.gaps(db))
    assert api.get(f"/api/fft/roadmap/{it.id}", headers=H).json()["scope_asked"] is True
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "not_now"})
    db.refresh(it)
    assert it.scope_asked_at is None and not any(g["kind"] == "scope_asked" for g in views.gaps(db))
    admin.post(f"/manage/roadmap/{it.id}", data={"do": "scope_it"})
    rules.write_scope(db, "claude", it, what="An easier builder.", inside=["Start from a weapon"])
    db.flush()
    assert not any(g["kind"] == "scope_asked" for g in views.gaps(db))
    assert rules.pick_next(db).item is None or rules.pick_next(db).item.id != it.id
    r = admin.post(f"/manage/roadmap/{it.id}", data={"do": "scope_it"}, follow_redirects=False)  # (it has one: refused)
    assert r.status_code == 303 and 'data-do="scope-it"' not in admin.get(f"/manage/roadmap/{it.id}").text


def test_an_items_why_is_a_line_then_points_with_the_decisions_behind_it(db, admin, api):
    """The why (Brett's pick Nov 21): its first line the headline, each line after it a point, the decisions behind it in
    a quiet line; the facts a labelled strip that says Next once."""
    it = rules.new_idea(db, "claude", "Homebrew items", where="chat")
    db.flush()
    api.post(f"/api/fft/roadmap/{it.id}", json={"do": "set", "why": "Make homebrew items easy.\n- Start from a weapon\n- Give one to a character",
                                                "why_from": "From your picks on Item Builder.", "size": "M"}, headers=H)
    page = admin.get(f"/manage/roadmap/{it.id}").text
    why = page[page.index("data-why "):page.index("</section>", page.index("data-why "))]
    assert why.count("<li>") == 2 and "homebrew items easy" in why.split("<li>")[0] and "data-why-from" in why
    assert page.count("<dt>") == 4 and 'data-next="claude"' in page  # (Section, Size, Stage, Next step)
    assert 'role="tablist"' in page and 'id="t-steps"' in page


def test_an_items_pages_open_in_askdnd_from_its_window_and_page(db, admin):
    """Issue 105 (Brett's note, Nov 23: "This scope does not allow me to open the mockup where I need to ask questions in
    order for you to set the scope"): the pages an item points to, by a claude.ai link or a docs/ path in its scope or
    steps, open inside askdnd from its window in For you and from its page; a link Documents doesn't list is left out."""
    from app import documents

    entry = next(e for e in documents.library() if e.get("link"))
    other = next(e for e in documents.library() if e["id"] != entry["id"])
    it = _scoped(db)
    rules.write_scope(db, "claude", it, what="One page for you to read.", inside=[f"The page: {entry['link']}", f"Built from {other['source']}",
                                                                            "And https://claude.ai/artifact/NotInTheLibrary"])
    db.flush()
    want = [f'href="/manage/documents/{entry["id"]}"', f'href="/manage/documents/{other["id"]}"']
    window = admin.get(f"/manage/item/r{it.id}").text
    assert all(w in window for w in want) and 'data-sec="pages"' in window and "NotInTheLibrary" not in window.split('data-sec="pages"')[1].split("</section>")[0]
    page = admin.get(f"/manage/roadmap/{it.id}").text
    assert all(w in page for w in want) and "data-pages" in page
    stepped = _scoped(db, "A step names it")  # (item 38's page was named only in Brett's step)
    rules.add_step(db, "claude", stepped, f"Read the comparison: {entry['link']}", whose="brett")
    db.flush()
    assert want[0] in admin.get(f"/manage/item/r{stepped.id}").text
    added = _scoped(db, "An addition names it")  # (a page Brett pastes into an addition; the review of #475)
    rules.add_to_item(db, "user:1", added, f"Also read {other['source']}", user_id=None)
    db.flush()
    assert want[1] in admin.get(f"/manage/item/r{added.id}").text
    bare = _scoped(db, "No pages")
    assert 'data-sec="pages"' not in admin.get(f"/manage/item/r{bare.id}").text and "data-pages" not in admin.get(f"/manage/roadmap/{bare.id}").text


def test_an_item_ships_only_once_every_step_is_ticked_or_removed(db):
    """Brett, Nov 24: R42 sat in History at 5 of 7, its next step Claude's. A step left open is ticked or removed before
    the item ships; Not doing still closes an item whatever its steps."""
    it = rules.new_idea(db, "claude", "A small build", section="now")
    db.flush()
    done, later = rules.add_step(db, "claude", it, "Build it"), rules.add_step(db, "claude", it, "Look again next month")
    rules.tick_step(db, "claude", done)
    with pytest.raises(rules.RuleError, match="1 step still open"):
        rules.ship_item(db, "claude", it, result="Built")
    assert it.section == "now"
    rules.remove_step(db, "claude", later)
    rules.ship_item(db, "claude", it, result="Built")
    assert it.section == "shipped"
    other = rules.new_idea(db, "claude", "Not now")
    db.flush()
    rules.add_step(db, "claude", other, "Something")
    rules.ship_item(db, "claude", other, not_doing=True, result="Not needed")
    assert other.section == "not_doing"


def test_an_ideas_sender_hears_when_it_joins_the_roadmap_and_when_it_ships(db, admin):
    """R10's slice 5 (Brett's OK on its scope, Nov 27): a note taken up as an idea says so on Notes you sent when it
    joins a Roadmap item (a word of its own, so its marker changes and the note shows as new) and when that item ships
    (or isn't done after all), in words written for its sender (R2: never the item's own words)."""
    from app.fft import views

    note = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="idea", text="Could the dice make a sound?")
    db.flush()
    before = views.marker(db, note, None)
    admin.post(f"/manage/feedback/notes/{note.id}", data={"do": "idea"})
    db.refresh(note)
    joined = views.sender_says(db, note, None)
    assert joined["word"] == "On the Roadmap" and views.marker(db, note, None) != before
    it = db.get(FftItem, db.get(FftIdea, note.idea_id).item_id)
    rules.ship_item(db, "claude", it, result="Dice make a sound\\nOne setting turns it off")
    db.flush()
    built = views.sender_says(db, note, None)
    assert built["word"] == "Built" and "Dice make a sound" not in built["sentence"]
    other = rules.send_note(db, user_id=None, first_name="Cole", role="player", kind="idea", text="A tray for the dice?")
    db.flush()
    admin.post(f"/manage/feedback/notes/{other.id}", data={"do": "idea"})
    db.refresh(other)
    rules.ship_item(db, "claude", db.get(FftItem, db.get(FftIdea, other.idea_id).item_id), not_doing=True, result="Not now")
    db.flush()
    assert "won't be built" in views.sender_says(db, other, None)["sentence"]
