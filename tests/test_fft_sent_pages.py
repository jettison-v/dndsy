"""Pages Claude sends to askdnd before their repo copy lands (item 39, scope v7, Brett, Nov 24: "pushing transactional,
data-only items without a PR and a merge"; rules.send_page, POST /api/fft/pages, app/documents.py, feedback.py page
send): a page opens in Documents at once, sealed as the repo's pages are; the newer copy is the one shown; only
Claude's key sends one, and only into the page's own folder."""

import base64
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, documents
from app.db import get_db
from app.fft import rules
from app.fft.models import FftEvent
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
CLAUDE = "c" * 40
PAGE = "<title>A sent page</title><main data-mark='sent'>sent, not merged</main>"


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_MINI_KEY", "m" * 40)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _entry(source="docs/mockups/sent-page/index.html", **kw):
    return {"title": "A sent page", "kind": "design", "status": "Your picks", "date": "Nov 24", "what": "Drawn to try sending.",
            "source": source, "link": ""} | kw


def _send(api, entry=None, files=None, key=CLAUDE):
    files = files if files is not None else {"mockups/sent-page/index.html": PAGE.encode()}
    return api.post("/api/fft/pages", headers={"X-Fft-Key": key},
                    json={"entry": entry or _entry(), "files": {k: base64.b64encode(v).decode() for k, v in files.items()}})


def _frame(admin, did):
    page = admin.get(f"/manage/documents/{did}")
    assert page.status_code == 200
    src = re.search(r'<iframe class="doc-frame" src="([^"]+)"', page.text).group(1).replace("&amp;", "&")
    return admin.get(src)


def test_a_sent_page_opens_in_documents_at_once_sealed(api, admin, db):
    """Sent, it's first in Documents and opens in the sealed frame, before any pull request; a question can name it."""
    r = _send(api)
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert documents.library()[0]["id"] == did and documents.library()[0]["sent"]
    assert 'data-copy="sent"' in admin.get(f"/manage/documents/{did}").text  # (the page says it's ahead of its pull request)
    served = _frame(admin, did)
    assert served.status_code == 200 and "data-mark='sent'" in served.text
    assert "sandbox" in served.headers["content-security-policy"] and served.headers["referrer-policy"] == "no-referrer"
    assert "doc-layer.js" in served.text  # (Brett's comment pins and Save my picks, as on the repo's pages)
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which one?", doc_path="docs/mockups/sent-page/index.html")
    assert q.doc_path == "docs/mockups/sent-page/index.html"
    assert db.query(FftEvent).filter_by(kind="page_sent").count() == 1


def test_sending_again_replaces_it_and_a_design_folder_lists_its_boards(api, admin):
    _send(api)
    _send(api, files={"mockups/sent-page/index.html": b"<main>second</main>", "mockups/sent-page/board-2.html": b"<main>b2</main>",
                      "mockups/sent-page/shot.png": b"\x89PNG"})
    entry = documents.find(documents.doc_id("docs/mockups/sent-page/index.html"))
    assert documents.pages_of(entry) == ["mockups/sent-page/index.html"]
    assert "second" in _frame(admin, entry["id"]).text
    folder = _send(api, entry=_entry(source="docs/mockups/sent-page/"), files={"mockups/sent-page/index.html": b"<main>i</main>",
                                                                               "mockups/sent-page/board-3.html": b"<main>b3</main>"}).json()
    boards = documents.pages_of(documents.find(folder["id"]))  # (a send replaces the page whole: board 2 and the picture went)
    assert boards == ["mockups/sent-page/index.html", "mockups/sent-page/board-3.html"]
    assert documents.read(None, "mockups/sent-page/shot.png") is None


def test_a_sent_copy_is_shown_while_it_differs_and_goes_once_a_deploy_carries_it(api, admin, db):
    """A page already in the repo: the sent copy is shown while it differs, even after a deploy that doesn't carry it (a
    deploy of other work mustn't bring back the older page); once a deploy carries the same page and entry, the sent
    copy is removed in its first minute, so the repo's copy, and any later change to it, is shown."""
    source = "docs/mockups/work-board/index.html"
    repo = documents.find(documents.doc_id(source))
    _send(api, entry=_entry(source=source, title="The Work Board, round 2"), files={"mockups/work-board/index.html": b"<main>round 2</main>"})
    e = documents.find(documents.doc_id(source))
    assert e["title"] == "The Work Board, round 2" and "round 2" in _frame(admin, e["id"]).text
    assert rules.prune_landed_pages(db) == []  # (a deploy of other work: still waiting, still shown)
    assert "round 2" in _frame(admin, e["id"]).text
    on_disk = (ROOT / "docs" / "mockups" / "work-board" / "index.html").read_bytes()
    _send(api, entry={k: repo[k] for k in documents.ENTRY_KEYS} | {"source": source}, files={"mockups/work-board/index.html": on_disk})
    assert rules.prune_landed_pages(db) == [source]  # (the deploy that carries it)
    assert db.query(FftEvent).filter_by(kind="page_landed").count() == 1
    e = documents.find(documents.doc_id(source))
    assert not e.get("sent") and 'data-copy="repo"' in admin.get(f"/manage/documents/{e['id']}").text


def test_a_deploy_prunes_what_landed_and_never_stops_for_it(monkeypatch):
    """The deploy's first minute removes landed pages; a failure there is reported and askdnd carries on."""
    from app import main

    monkeypatch.setattr(rules, "release_live", lambda *a, **k: {})
    monkeypatch.setattr(rules, "prune_landed_pages", lambda db: ["docs/x.html"])
    assert main.release_now() == {"pages_landed": ["docs/x.html"]}


@pytest.mark.parametrize(("entry", "files", "said"), [
    (_entry(), {"mockups/other-page/index.html": b"x"}, "own folder"),
    (_entry(), {"mockups/sent-page/../../library.json": b"[]"}, "own folder"),
    (_entry(), {"mockups/sent-page/run.py": b"print(1)"}, "own folder"),
    (_entry(source="docs/stack.html"), {"stack.html": b"x", "library.json": b"[]"}, "own folder"),
    (_entry(source="docs/../app/main.py"), {"x.html": b"x"}, "source"),
    (_entry(kind="secret"), None, "kind"),
    (_entry(link="https://example.com/x"), None, "link"),
    (_entry(), {"mockups/sent-page/index.html": b"x" * (rules.PAGE_FILE_MAX + 1)}, "MB"),
], ids=["another-folder", "climbs-out", "not-a-page-file", "shared-folder", "source-outside", "kind", "link", "too-big"])
def test_a_page_goes_only_into_its_own_folder_as_a_page(api, db, entry, files, said):
    r = _send(api, entry=entry, files=files)
    assert r.status_code == 400 and said in r.text
    assert db.query(FftEvent).filter_by(kind="page_sent").count() == 0


def test_a_standing_rule_only_claudes_key_sends_a_page(api, db):
    """A standing rule (Brett, Nov 19, T6: a key per actor, each allowed only what it does): no key, or the Mac Mini's,
    sends nothing; what's sent is only ever opened sealed (above)."""
    assert _send(api, key="").status_code == 404
    assert _send(api, key="m" * 40).status_code == 403
    assert db.query(FftEvent).filter_by(kind="page_sent").count() == 0


def test_feedback_py_sends_what_askdnd_keeps():
    """feedback.py page send gathers the files askdnd accepts: a mockup's folder, or a shared folder's page alone."""
    spec = importlib.util.spec_from_file_location("feedback", ROOT / "scripts" / "feedback.py")
    fb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fb)
    assert fb.PAGE_FILES == rules.PAGE_FILES
    for source in ("docs/mockups/work-board/index.html", "docs/stack.html", "docs/artifacts/work-flow.html"):
        home = rules.page_home(source)
        sent = fb.page_files(source)
        assert sent and all((p.startswith(home) if home.endswith("/") else p == home) for p in sent), source
