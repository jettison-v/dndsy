"""The Inbox digest (app/digest.py; Brett chose B and A, Nov 9, docs/mockups/inbox-email/): once a day past DIGEST_HOUR,
to the campaign's DM (others opt in), only when something new reached the Inbox; counts and a link, never what was
written; a signed one-click stop link."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import config, digest
from app.companion_story import TABLE_TIME
from app.models import Campaign, Entity, EntityKind, Fact, User
from tests.roles import set_role


def _at(hour: int, day: int = 9) -> datetime:
    return datetime(2026, 11, day, hour, 5, tzinfo=TABLE_TIME).astimezone(UTC)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(digest, "SEND", lambda to, mail: out.append((to, mail)) or True)
    monkeypatch.setattr(config, "DIGEST_HOUR", 18)
    return out


@pytest.fixture
def campaign(db):
    dm = set_role(db, "dm@example.com", "dm")
    set_role(db, "other@example.com", "reviewer", name="Rev")
    set_role(db, "player@example.com", "player", name="Pat")
    c = db.scalars(select(Campaign)).first()
    db.add(Entity(campaign_id=c.id, name="The Mill", kind=EntityKind.PLACE))
    db.commit()
    return c, dm


def _suggest(db, c, text="A secret only the table knows.", at=None):
    e = db.scalar(select(Entity).where(Entity.campaign_id == c.id))
    f = Fact(entity_id=e.id, text=text, status="pending")
    db.add(f)
    db.flush()
    if at:
        f.created_at = at
    db.commit()


def test_once_a_day_past_the_hour_to_the_dm_counts_only(db, sent, dm, campaign):  # (dm: the sign-in allowlist)
    """A standing rule (Brett, Nov 9, inbox email: counts and a link only): never a word of what was written, nor who."""
    c, dm = campaign
    _suggest(db, c, at=_at(15) - timedelta(hours=2))
    assert digest.run_day(db, _at(17)) == [] and sent == []  # (before the hour)
    assert digest.run_day(db, _at(18)) == [("dm@example.com", c.name)]
    mail = sent[0][1]
    assert mail["subject"] == f"{c.name}: 1 new thing in the Inbox" and "From the table" in mail["html"] and "/manage/inbox" in mail["html"]
    assert "secret" not in mail["html"] + mail["text"] and "Pat" not in mail["html"] + mail["text"]
    assert "/email/stop?t=" in mail["html"]
    assert digest.run_day(db, _at(21)) == []  # (looked at once today: later arrivals wait for tomorrow)
    _suggest(db, c, at=_at(20))
    assert digest.run_day(db, _at(22)) == [] and len(sent) == 1
    assert digest.run_day(db, _at(18, day=10)) == [("dm@example.com", c.name)]  # (tomorrow: what came after)
    assert digest.run_day(db, _at(18, day=11)) == []  # (nothing new: no email)


def test_reviewers_opt_in_and_the_stop_link_turns_it_off(db, sent, dm, campaign):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)  # (signed out: the email's link needs no sign-in)
    c, dm = campaign
    rev = db.scalar(select(User).where(User.email == "other@example.com"))
    assert not digest.wants(rev, c.id, "reviewer", False) and digest.wants(dm, c.id, "dm", False)
    assert not digest.wants(db.scalar(select(User).where(User.email == "player@example.com")), c.id, "player", False)
    rev.emails = {"inbox": {str(c.id): True}}
    db.commit()
    _suggest(db, c, at=_at(12))
    assert sorted(e for e, _ in digest.run_day(db, _at(18))) == ["dm@example.com", "other@example.com"]
    stop = next(mail["stop"] for to, mail in sent if to == "dm@example.com")  # (the DM's own link: the order they go in isn't fixed)
    page = client.get(stop[len(config.PROD_URL):])
    assert page.status_code == 200 and "No more Inbox emails" in page.text
    db.expire_all()
    assert db.scalar(select(User).where(User.email == "dm@example.com")).emails["inbox"][str(c.id)] is False
    assert client.get("/email/stop?t=nonsense").status_code == 400
    assert client.post(stop[len(config.PROD_URL):]).status_code == 200  # (a mail app's one-click Unsubscribe)


def test_your_account_email_switches_it(db, campaign, dm, player):
    c, _ = campaign
    page = dm.get("/email").text
    assert c.name in page and 'aria-checked="true"' in page
    r = dm.post("/email/inbox", data={"campaign": c.id, "on": ""})
    assert r.status_code == 200 and 'aria-checked="false"' in r.text
    db.expire_all()
    assert db.scalar(select(User).where(User.email == "dm@example.com")).emails["inbox"][str(c.id)] is False
    assert player.post("/email/inbox", data={"campaign": c.id, "on": "1"}).status_code == 403
    assert "Nothing to send you" in player.get("/email").text


def test_no_email_without_a_key_or_on_staging(monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    assert not digest.enabled()
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(config, "STAGING", True)
    assert not digest.enabled()
