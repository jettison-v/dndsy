from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config
from app.admin_usage import usage_summary
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import CreditTopUp, ExtractionRun, GameSession


def runs(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 29}]})
    sid = db.scalar(select(GameSession)).id
    now = datetime.now(UTC)
    db.add_all([
        ExtractionRun(session_id=sid, source="notes", status="done", cost_usd=0.12, created_at=now),
        ExtractionRun(session_id=sid, source="notes", status="done", cost_usd=0.10, created_at=now - timedelta(days=40)),
        ExtractionRun(session_id=sid, source="notes", status="error", cost_usd=0.0, created_at=now),
    ])
    db.flush()


def test_summary_totals_and_balance(db):
    runs(db)
    u = usage_summary(db)
    assert round(u["total"], 2) == 0.22 and round(u["today"], 2) == 0.12 and u["drafts"] == 2
    assert u["balance"] is None  # no top-ups yet
    db.add(CreditTopUp(amount_usd=20.0, added_on=datetime.now(UTC).date()))
    db.flush()
    assert round(usage_summary(db)["balance"], 2) == 19.78


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def test_usage_page_and_topups(client, db):
    runs(db)
    page = client.post("/admin/usage/topups", data={"amount": "$20.00", "added_on": "2026-10-15", "note": "first"}).text
    assert "$19.78" in page and "of $20.00 bought" in page
    t = db.scalar(select(CreditTopUp))
    client.post(f"/admin/usage/topups/{t.id}/delete")
    assert db.scalar(select(CreditTopUp)) is None


def test_parse_amount():
    from app.admin_usage import parse_amount

    assert parse_amount("$20") == 20.0
    assert parse_amount(" $1,000.50 ") == 1000.5
    assert parse_amount("20.00") == 20.0
    assert parse_amount("twenty") is None
    assert parse_amount("nan") is None
