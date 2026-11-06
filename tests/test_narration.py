"""Listen to the recap (a Labs feature, app/narration.py; Brett, Nov 6): the published recap read aloud, made once and
kept, counted on Usage, over the pictures of who each paragraph names."""

import pytest
from sqlalchemy import select

from app import narration
from app.importer import import_bundle
from app.models import Campaign, Entity, ExtractionRun, GameSession, Recap, Status
from tests.table_setup import BUNDLE

pytestmark = pytest.mark.usefixtures("file_store")

BODY = ("The party reached **Star Mount** at dusk, and Cole led them up the old path.\n\n"
        "Trah lit the way with a flicker of fire; nobody spoke of the bard.\n\n"
        "At the top, an empty shrine waited.")


@pytest.fixture
def told(db, monkeypatch):
    """Main with a published recap, Labs and Listen switched on, and OpenAI stood in for (counting each call)."""
    import_bundle(db, BUNDLE)
    campaign = db.scalar(select(Campaign))
    campaign.vtt_pieces = ["labs", "recap_listen"]
    s = GameSession(campaign_id=campaign.id, number=19, title="Journey to Star Mount", source="notes")
    db.add(s)
    db.flush()
    db.add(Recap(session_id=s.id, version=1, body=BODY, author="ai", status=Status.PUBLISHED))
    db.flush()
    calls = []
    monkeypatch.setattr(narration, "FETCH", lambda text: calls.append(text) or b"ID3" + b"\x00" * 64)
    monkeypatch.setattr(narration.pictures, "urls", lambda db, ids: {i: {"full": f"/pic/{i}", "pos": "50% 20%"} for i in ids})
    return s, calls


def test_listen_reads_the_recap_once_and_keeps_it(player, db, told):
    s, calls = told
    assert f'data-listen="/c/main/sessions/{s.id}"' in player.get("/c/main/").text  # (▶ Listen on Previously on…)
    tale = player.get(f"/c/main/sessions/{s.id}/tale").json()
    assert tale["audio"] == "" and tale["title"] == "Journey to Star Mount" and tale["intro"] == "Previously, on Main…"
    words = [x["text"] for x in tale["slides"]]
    assert words[1].startswith("The party reached Star Mount") and "**" not in words[1]  # (plain words, read and shown)
    cole = db.scalar(select(Entity).where(Entity.name == "Cole")).id
    trah = db.scalar(select(Entity).where(Entity.name == "Trah")).id
    assert [p["src"] for p in tale["slides"][1]["pictures"]] == [f"/pic/{cole}"]  # (who each paragraph names)
    assert [p["src"] for p in tale["slides"][2]["pictures"]] == [f"/pic/{trah}"]
    assert tale["slides"][3]["pictures"] == tale["slides"][2]["pictures"]  # (names no one: the last pictures carry on)
    first = player.post(f"/c/main/sessions/{s.id}/narrate").json()
    assert first["audio"].startswith(f"/c/main/sessions/{s.id}/narration?v=") and len(calls) == 1
    assert calls[0].startswith("Previously, on Main…") and "Star Mount" in calls[0]
    run = db.scalar(select(ExtractionRun).where(ExtractionRun.source == "narration"))
    assert run.status == "done" and run.cost_usd > 0  # (counted on Manage › Usage, under the monthly limit)
    assert player.post(f"/c/main/sessions/{s.id}/narrate").json() == first and len(calls) == 1  # (kept: made once)
    got = player.get(f"/c/main/sessions/{s.id}/narration")
    assert got.status_code == 200 and got.headers["content-type"] == "audio/mpeg" and got.content.startswith(b"ID3")
    assert "Drafting" not in player.get("/c/main/").text


def test_listen_is_a_labs_feature(player, db, told):
    s, calls = told
    db.scalar(select(Campaign)).vtt_pieces = []
    db.flush()
    assert "data-listen" not in player.get("/c/main/").text
    assert player.get(f"/c/main/sessions/{s.id}/tale").status_code == 404
    assert player.post(f"/c/main/sessions/{s.id}/narrate").status_code == 404 and calls == []


def test_the_spending_limit_stops_it(player, db, told, monkeypatch):
    s, calls = told
    monkeypatch.setattr(narration.spending, "reached", lambda db: "This month's limit is reached.")
    r = player.post(f"/c/main/sessions/{s.id}/narrate")
    assert r.status_code == 503 and "limit" in r.json()["error"] and calls == []


def test_a_long_recap_is_read_in_parts_openai_takes():
    lines = ["x" * 3000, "y" * 3000, "z. " * 1600]
    parts = narration._parts(lines)
    assert all(len(p) <= narration.CHUNK for p in parts) and "".join(parts).replace("\n", "").replace(" ", "") == "".join(lines).replace(" ", "")
