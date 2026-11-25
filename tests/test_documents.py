"""Manage › askdnd › Documents (Nov 6, app/documents.py): every page made for askdnd, in one place, for admins only,
opened from the repo's copy in a sealed frame."""

import json
import re
from pathlib import Path
from typing import ClassVar

from app import documents

ROOT = Path(__file__).resolve().parent.parent


def test_a_standing_rule_only_admins_see_the_documents(admin, dm, player):
    """A standing rule (CLAUDE.md, who sees what): askdnd's own admin pages are for admins; the documents describe the
    campaign's people and plans, so neither the DM nor a player opens them."""
    assert admin.get("/manage/documents").status_code == 200
    one = documents.library()[0]["id"]
    for who in (dm, player):
        assert who.get("/manage/documents", follow_redirects=False).status_code in (303, 403)
        assert who.get(f"/manage/documents/{one}", follow_redirects=False).status_code in (303, 403)


def test_every_listed_document_opens(admin):
    """Every entry in docs/library.json has its repo copy, and its page opens; a plan in the page, the rest in the frame,
    whose address serves the page."""
    for e in documents.library():
        assert documents.pages_of(e), f"{e['title']}: {e['source']} has nothing to open"
        page = admin.get(f"/manage/documents/{e['id']}")
        assert page.status_code == 200, e["title"]
        frame = re.search(r'<iframe class="doc-frame" src="([^"]+)"', page.text)
        if frame:
            served = admin.get(frame.group(1).replace("&amp;", "&"))
            assert served.status_code == 200 and "sandbox" in served.headers["content-security-policy"], e["title"]
            assert served.headers["referrer-policy"] == "no-referrer"



def test_a_document_in_for_yous_window_is_itself_and_scrolls(admin):
    """For you's Open (part=1, a window nearly the whole screen): a mockup in its sealed frame; a plan written as text,
    its words in the window's scrolling body, never the whole Documents page inside the window (Brett, Nov 19: the
    lighter-round plan "does not scroll")."""
    plan = next(e for e in documents.library() if e["source"].endswith(".md"))
    window = admin.get(f"/manage/documents/{plan['id']}?part=1").text
    assert 'class="peek-body' in window and 'class="doc-text"' in window and "doc-back" not in window and "<html" not in window
    mockup = next(e for e in documents.library() if e["source"].endswith(".html") and e["source"].startswith("docs/mockups/"))
    window = admin.get(f"/manage/documents/{mockup['id']}?part=1").text
    assert 'class="doc-frame"' in window and "doc-text" not in window

def test_nothing_in_the_repo_is_left_out_of_the_library():
    """Every page in docs/artifacts, docs/mockups and docs/plans is in the library (a new one is added to
    docs/library.json the day it's made), and the library names no two pages the same way."""
    listed = [e["source"].rstrip("/") for e in documents.library()]
    assert len(set(listed)) == len(listed) and len({e["id"] for e in documents.library()}) == len(listed)
    for folder in ("artifacts", "mockups", "plans"):
        for path in sorted((ROOT / "docs" / folder).iterdir()):
            rel = path.relative_to(ROOT).as_posix()
            if path.name == "README.md" or path.name.startswith("."):
                continue
            assert any(rel == s or rel.startswith(s + "/") or s.startswith(rel + "/") for s in listed), f"{rel} isn't in docs/library.json"
    kinds = {k for k, *_ in documents.KINDS}
    assert all(e["kind"] in kinds for e in json.loads(documents.LIBRARY.read_text()))


def test_the_frame_serves_only_its_own_folder_for_an_hour(admin, monkeypatch):
    """The frame's key opens only the folder it was made for, nothing outside docs/, and runs out."""
    url = documents.file_url("artifacts/recording-to-recap.html")
    key = url.split("/")[4]
    assert admin.get(url).status_code == 200
    assert admin.get(f"/manage/documents/f/{key}/plans/2026-11-05-action-widgets.md").status_code == 404  # another folder
    assert admin.get(f"/manage/documents/f/{key}/artifacts/../../CLAUDE.md").status_code in (400, 403, 404)  # (never served)
    assert admin.get("/manage/documents/f/forged/artifacts/recording-to-recap.html").status_code == 403
    monkeypatch.setattr(documents, "KEY_SECONDS", -1)
    assert admin.get(url).status_code == 403


def test_the_roadmaps_tags_all_close():
    """Nov 9: one missing </div> in a step nested every step after it, and the published roadmap's columns overlapped."""
    from html.parser import HTMLParser

    class Tags(HTMLParser):
        VOID: ClassVar[set] = {"br", "img", "input", "meta", "link", "hr", "col", "source", "wbr"}

        def __init__(self):
            super().__init__()
            self.open, self.wrong = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in self.VOID:
                self.open.append((tag, self.getpos()[0]))

        def handle_endtag(self, tag):
            if tag in self.VOID:
                return
            if self.open and self.open[-1][0] == tag:
                self.open.pop()
            else:
                self.wrong.append((tag, self.getpos()[0], self.open[-1] if self.open else None))

    p = Tags()
    p.feed((ROOT / "docs" / "roadmap.html").read_text())
    assert p.wrong == [] and p.open == [], (p.wrong[:3], p.open[-3:])


def test_every_document_has_its_state_and_one_plain_line():
    """Brett's picks S2 and D3 (docs/mockups/backstage-design-review/, Nov 24): a document's state is a fixed key, its
    colour and word come from it, and it says what it is in one plain line (no item numbers or paths)."""
    for e in documents.repo_library():
        assert e.get("state") in documents.STATES, f"{e['title']}: state {e.get('state')!r}"
        line = e.get("line") or ""
        assert line and len(line) <= 90, f"{e['title']}: its line is missing or longer than one line"
        assert not re.search(r"\b(PR|item) ?#?\d|docs/|app/|\.py\b|\bR\d+\b", line), f"{e['title']}: {line}"


def test_the_list_starts_on_what_waits_on_you_newest_first_and_moves_what_was_replaced(admin, monkeypatch):
    """Brett's picks D1 and D2: Waiting on you · Current · All, starting on what waits on him; newest first in each
    group; a superseded page under Earlier whatever its kind; a row opens its document in the large window."""
    rows = [{"title": "Old guide", "kind": "guide", "state": "earlier", "date": "Nov 2", "source": "docs/a.html", "id": "a"},
            {"title": "New plan", "kind": "plan", "state": "building", "date": "Nov 20", "source": "docs/b.html", "id": "b"},
            {"title": "Older plan", "kind": "plan", "state": "done", "date": "Oct 28", "source": "docs/c.html", "id": "c"},
            {"title": "Picks", "kind": "design", "state": "waiting", "date": "Nov 24", "source": "docs/d.html", "id": "d"}]
    assert documents.date_rank("Jan 3") > documents.date_rank("Dec 30") > documents.date_rank("Oct 28") > documents.date_rank("") == 0
    got = documents.rows_for(rows)
    assert [r["e"]["title"] for r in got] == ["New plan", "Older plan", "Picks", "Old guide"]
    assert got[-1]["group"] == "Earlier and superseded" and got[0]["views"] == "current all" and got[1]["views"] == "all"
    assert got[2]["views"] == "waiting all" and got[2]["tone"] == "draft" and got[2]["word"] == "Yours"  # (one word in a pill: AU7)
    monkeypatch.setattr(documents, "library", lambda: tuple(rows))
    page = admin.get("/manage/documents").text
    assert 'data-ls-start="waiting"' in page and 'data-ls-view="waiting"' in page
    assert 'data-modal-url="/manage/documents/d?part=1" data-modal-size="full"' in page and 'href="/manage/documents/d"' in page  # (a row opens the window; its title links to the page: AU1)
    monkeypatch.setattr(documents, "library", lambda: tuple(r for r in rows if r["state"] != "waiting"))
    assert 'data-ls-start="current"' in admin.get("/manage/documents").text  # (nothing waits: it starts on Current)
