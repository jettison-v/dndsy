import json
import time

import pytest
from fastapi.testclient import TestClient

from transcript_filter import web
from transcript_filter.segments import Segment

RAW = [
    {"speaker": "A", "text": "How was work today?", "timestamp": "00:01.000-00:02.000"},
    {"speaker": "B", "text": "Busy, lots of meetings.", "timestamp": "00:03.000-00:04.000"},
    {"text": "Busy, lots of meetings.", "timestamp": "00:03.100-00:04.000"},
    {"speaker": "DM", "text": "You enter the brig.", "timestamp": "00:10.000-00:12.000"},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "RAW", tmp_path / "raw")
    monkeypatch.setattr(web, "WORK", tmp_path / "work")
    monkeypatch.setattr(web, "ollama_status", lambda: {"running": True, "model_ready": True})
    web.jobs.clear()

    def fake_run(raw_path, model, out_dir, context_path, progress, *a, **k):
        from transcript_filter.dedup import remove_echo
        from transcript_filter.segments import load_macwhisper

        segs = load_macwhisper(raw_path)
        remove_echo(segs)
        progress(1, 1)
        for s in segs:
            if s.kept and "brig" not in s.text:
                s.removed_by, s.reason = "off_topic", "table talk"
        return segs, {"pct_echo": 10.0, "model": "fake"}

    monkeypatch.setattr(web, "run", fake_run)
    return TestClient(web.app)


def add_session(client, data=RAW, day="2026-08-29", **extra):
    return client.post(
        "/upload",
        data={"played_on": day, **extra},
        files={"file": ("export.json", json.dumps(data).encode(), "application/json")},
        follow_redirects=False,
    )


def wait_for_job(client, stem):
    for _ in range(100):
        if client.get(f"/sessions/{stem}/progress").json()["status"] != "running":
            return
        time.sleep(0.02)


def test_upload_rejects_non_macwhisper(client):
    r = add_session(client, data={"not": "a list"})
    assert "MacWhisper" in r.headers["location"]


def test_upload_refuses_overwrite_unless_asked(client):
    assert add_session(client).headers["location"] == "/sessions/2026-08-29"
    assert "already" in add_session(client).headers["location"]
    assert add_session(client, replace="1").headers["location"] == "/sessions/2026-08-29"


def test_full_flow_filter_review_keep_save(client, tmp_path):
    add_session(client)
    client.post("/sessions/2026-08-29/filter")
    wait_for_job(client, "2026-08-29")
    page = client.get("/sessions/2026-08-29").text
    assert "Step 2: Review the cuts" in page
    assert "How was work today?" in page  # shown inside the cut stretch

    client.post("/sessions/2026-08-29/save")
    final = json.loads((tmp_path / "work/2026-08-29/final.json").read_text())
    assert [x["text"] for x in final] == ["You enter the brig."]

    state = json.loads((tmp_path / "work/2026-08-29/state.json").read_text())
    first_cut = next(r["i"] for r in state if r["removed_by"] == "off_topic")
    client.post(f"/sessions/2026-08-29/stretches/{first_cut}", data={"keep": "1"})
    assert not (tmp_path / "work/2026-08-29/final.json").exists()  # saved copy is now stale
    client.post("/sessions/2026-08-29/save")
    final = json.loads((tmp_path / "work/2026-08-29/final.json").read_text())
    texts = [x["text"] for x in final]
    assert texts == ["How was work today?", "Busy, lots of meetings.", "You enter the brig."]  # echo copy still gone


def test_other_websites_cannot_post(client):
    r = client.post("/quit", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_bad_session_names_rejected(client):
    with pytest.raises(ValueError):
        web.paths("../../etc")
