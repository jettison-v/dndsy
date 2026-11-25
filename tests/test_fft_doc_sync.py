"""Comments and picks in either place, merged (item 39, 6 of 6; Brett, Nov 24: "I would like to be able to make updates
in either place and have them merge", his pick A on docs/mockups/pages-and-comments/): what Brett made on claude.ai
comes into askdnd when Claude checks in (rules.comments_in, rules.picks_in, POST /api/fft/docs/in, feedback.py sync), and
askdnd's go out for the page's own store (rules.doc_out); each copy keeps where it was made, so nothing comes in twice;
picked in both places, the newest wins."""

from datetime import UTC, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules
from app.fft.models import FftDocComment, FftEvent
from app.main import app

CLAUDE = "c" * 40
DOC = "docs/mockups/fft-round-2/index.html"


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_MINI_KEY", "m" * 40)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _in(api, comments=(), picks=None, key=CLAUDE, doc=DOC):
    return api.post("/api/fft/docs/in", headers={"X-Fft-Key": key}, json={"doc": doc, "comments": list(comments), "picks": picks})


C1 = {"ext_id": "t1:1", "near": "Split into 3", "words": "Call it Approve.", "at": "2026-11-24T15:38:00Z"}
PICKS = {"picks": [{"name": "queue", "value": "quiet", "label": "1 A"}], "notes": "Looks right.", "at": "2026-11-24T15:47:00Z"}


def test_claude_ai_comments_come_in_once_and_go_with_the_picks_made_there(api, admin, db):
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    assert _in(api, [C1]).json()["comments"] == 1
    assert _in(api, [C1]).json()["comments"] == 0  # (claude.ai's mark: brought in once)
    c = db.scalar(select(FftDocComment))
    assert (c.origin, c.near, c.sent_at, c.user_id) == ("claude.ai", "Split into 3", None, None)
    rail = admin.get(f"/manage/testing/comments?doc={DOC}").text
    assert 'data-origin="claude.ai"' in rail and "data-comment-drop" not in rail  # (his, made elsewhere: shown, not taken back here)
    assert _in(api, picks=PICKS).json()["picks"] == "answered"
    db.refresh(q)
    db.refresh(c)
    assert q.answered_at.astimezone(UTC).isoformat()[:16] == "2026-11-24T15:47" and q.picks == PICKS["picks"]  # (when he made them)
    assert "(on claude.ai)" in q.answer_text and "Looks right." in q.answer_text and "Call it Approve." in q.answer_text
    assert c.sent_at is not None and c.question_id == q.id


def test_picks_in_askdnd_take_claude_ai_comments_along(admin, api, db):
    """Comments brought in from claude.ai wait with his own, and his Save my picks in askdnd sends them all."""
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    _in(api, [C1])
    admin.post("/manage/testing/comments", json={"doc": DOC, "x": 0.4, "y": 120, "near": "Round 2", "words": "Mine, in askdnd."})
    r = admin.post("/manage/testing/picks", json={"doc": DOC, "picks": PICKS["picks"], "notes": ""})
    assert r.json()["comments"] == 2
    db.refresh(q)
    assert "Pin 1 (on claude.ai) (near “Split into 3”): Call it Approve." in q.answer_text and "Mine, in askdnd." in q.answer_text


def test_picked_in_both_places_the_newest_wins(api, db):
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    rules.answer(db, "user:1", q, choice=None, text="Picks: 1 A", picks=PICKS["picks"])
    db.flush()
    changed = {"picks": [{"name": "queue", "value": "loud", "label": "1 B"}], "notes": "", "at": (rules.now() + timedelta(minutes=5)).isoformat()}
    older = changed | {"picks": [{"name": "queue", "value": "older", "label": "1 C"}], "at": (rules.now() - timedelta(days=1)).isoformat()}
    assert _in(api, picks=older).json()["picks"] == "older"
    assert _in(api, picks=PICKS | {"at": changed["at"]}).json()["picks"] == "same"
    assert _in(api, picks=changed).json()["picks"] == "changed"
    db.refresh(q)
    assert q.picks[0]["value"] == "loud" and "changed on claude.ai" in q.answer_text and "Before: Picks: 1 A" in q.answer_text
    assert db.query(FftEvent).filter_by(kind="picks_changed").count() == 1


def test_askdnds_side_goes_out_for_claude_ai_and_only_its_own_comments(api, admin, db):
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    _in(api, [C1])
    admin.post("/manage/testing/comments", json={"doc": DOC, "x": 0.4, "y": 120, "near": "Round 2", "words": "Mine, in askdnd."})
    admin.post("/manage/testing/picks", json={"doc": DOC, "picks": PICKS["picks"], "notes": "A note."})
    out = api.get(f"/api/fft/docs/out?doc={DOC}", headers={"X-Fft-Key": CLAUDE}).json()
    assert [c["words"] for c in out["comments"]] == ["Mine, in askdnd."]  # (claude.ai's own stay there)
    assert out["picks"]["picks"] == PICKS["picks"] and out["picks"]["notes"] == "A note." and out["picks"]["at"]
    q.answer_text = "Picks: 1 A\n\nComments on the mockup:\nPin 1: x"
    db.flush()
    assert api.get(f"/api/fft/docs/out?doc={DOC}", headers={"X-Fft-Key": CLAUDE}).json()["picks"]["notes"] == ""  # (no notes: none)
    db.refresh(q)
    checked = api.get("/api/fft/docs/check", headers={"X-Fft-Key": CLAUDE}).json()["docs"]
    assert [d["doc"] for d in checked] == [DOC] and checked[0]["link"].startswith("https://claude.ai/")


def test_a_standing_rule_only_claudes_key_brings_things_in(api, db):
    """A standing rule (T6, a key per actor): no key, or the Mac Mini's, brings nothing in; a page not in Documents is
    turned away."""
    assert _in(api, [C1], key="").status_code == 404
    assert _in(api, [C1], key="m" * 40).status_code == 403
    assert _in(api, [C1], doc="docs/nowhere.html").status_code == 400
    assert db.scalar(select(FftDocComment)) is None


def _script(monkeypatch, tmp_path, looked_ago: float | None):
    import importlib.util
    import os
    import time
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("feedback", Path(__file__).resolve().parent.parent / "scripts" / "feedback.py")
    fb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fb)
    monkeypatch.setattr(fb, "CHECKED", tmp_path / ".claude-ai-checked")
    if looked_ago is not None:
        fb.CHECKED.touch()
        os.utime(fb.CHECKED, (time.time() - looked_ago,) * 2)
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)
    return fb


def _args(**kw):
    return type("A", (), {"hours": 8, "wake": 10, "base": "", "listener": "", "every": 30, **kw})()


def test_the_listener_wakes_claude_to_check_claude_ai(monkeypatch, capsys, tmp_path):
    """claude.ai can't wake Claude for a plain comment, so the listener ends once --wake minutes (10 by default) have
    passed since Claude last looked there (`sync list`)."""
    fb = _script(monkeypatch, tmp_path, looked_ago=0)
    clock = iter([0.0, 0.0, 601.0, 601.0])
    monkeypatch.setattr(fb.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(fb, "_peek", lambda base, listener: {"items": []})
    fb.wait(_args())
    assert "claude.ai is due a look" in capsys.readouterr().out


def test_busy_askdnd_never_puts_off_the_look_at_claude_ai(monkeypatch, capsys, tmp_path):
    """Issue 132 (Nov 25): Brett's notes came every few minutes, each ending a wait before its 10 minutes, so his
    claude.ai comment waited an afternoon. The look is counted from the last one: overdue, a wait says so at once, and a
    wait that ends with news says it's due too."""
    fb = _script(monkeypatch, tmp_path, looked_ago=3600)
    monkeypatch.setattr(fb, "_peek", lambda base, listener: {"items": []})
    fb.wait(_args())
    assert "claude.ai is due a look" in capsys.readouterr().out
    monkeypatch.setattr(fb, "_event", lambda e: "  a note")
    now = [1_000_000.0]

    def news(base, listener):  # (a note arrives two minutes into the wait)
        now[0] += 120
        return {"items": [{"at": "2026-11-25T17:38:00Z"}]}

    monkeypatch.setattr(fb, "_peek", news)
    monkeypatch.setattr(fb.time, "time", lambda: now[0])
    monkeypatch.setattr(fb, "_checked_at", lambda: 1_000_000.0 - 9 * 60)  # (looked 9 minutes before the wait began)
    fb.wait(_args())
    out = capsys.readouterr().out
    assert "new in askdnd" in out and "claude.ai is due a look" in out
    monkeypatch.setattr(fb, "_checked_at", lambda: 1_000_000.0)  # (looked as the wait began: news alone)
    fb.wait(_args())
    assert "due a look" not in capsys.readouterr().out


def test_your_picks_show_beside_the_scope_you_ok(api, admin, db):
    """Brett, Nov 24: "I cannot even see my answers during the final approval": a Roadmap item that points to a mockup
    shows your latest picks on it, in its window from For you and on its page's scope, saying where you saved them."""
    it = rules.new_item(db, "claude", "Our Work", section="now")
    db.flush()
    rules.set_item(db, "claude", it, why_from=f"From your picks on {DOC}")
    rules.write_scope(db, "claude", it, what="w", inside=["i"])
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    _in(api, picks=PICKS | {"notes": "Looks right."})
    window = admin.get(f"/manage/item/r{it.id}").text
    assert f'data-page-answer="{q.id}"' in window and "1 A" in window and "on claude.ai" in window and "Looks right." in window
    page = admin.get(f"/manage/roadmap/{it.id}?tab=scope").text
    assert f'data-page-answer="{q.id}"' in page


def test_a_question_with_a_mockup_says_its_picks_are_the_answer(admin, db):
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=DOC)
    db.flush()
    window = admin.get(f"/manage/item/q{q.id}").text
    assert "data-picks-answer" in window and "Nothing to type" in window
