"""Manage › askdnd › Documents (Nov 6, app/documents.py): every page made for askdnd, in one place, for admins only,
opened from the repo's copy in a sealed frame."""

import json
import re
from pathlib import Path

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


def test_the_roadmaps_table_is_written_from_the_library():
    """The roadmap's table of documents and Manage › askdnd › Documents are one list (docs/library.json): run
    scripts/library.py after changing it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("library", ROOT / "scripts" / "library.py")
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    page = (ROOT / "docs" / "roadmap.html").read_text()
    assert lib.written(page) == page, "docs/roadmap.html's table differs from docs/library.json: run scripts/library.py"


def test_the_roadmaps_tags_all_close():
    """Nov 9: one missing </div> in a step nested every step after it, and the published roadmap's columns overlapped."""
    from html.parser import HTMLParser

    class Tags(HTMLParser):
        VOID = {"br", "img", "input", "meta", "link", "hr", "col", "source", "wbr"}

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
