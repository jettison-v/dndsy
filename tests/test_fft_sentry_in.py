"""Errors at the table, filed (app/fft/sentry_in.py; Roadmap item 42, Brett's pick 4A on Talking both ways, Nov 24): once
a day askdnd asks Sentry for new unresolved errors and files each as an issue in Behind the scenes › Errors, once each,
reporting its run on Development › Scheduled; Sentry not answering is a failed run, never a crash."""

from datetime import timedelta

from sqlalchemy import select

from app.fft import rules, sentry_in, work_page
from app.fft.models import FftIssue, FftLine

ERR = {"id": "501", "title": "KeyError: 'hp'", "culprit": "app/hit_points.py in window", "count": "7", "userCount": 2,
       "firstSeen": "2026-11-24T18:02:11Z", "permalink": "https://sentry.example/issues/501/"}


def test_new_errors_are_filed_once_each_and_the_run_reports(db, monkeypatch):
    monkeypatch.setattr(sentry_in, "FETCH", lambda: [ERR])
    made = sentry_in.run(db)
    i = db.get(FftIssue, made[0])
    assert i.title == "Error: KeyError: 'hp'" and i.feature == "errors"
    line = db.scalar(select(FftLine).where(FftLine.issue_id == i.id))
    assert "7 times, 2 people" in line.text and ERR["permalink"] in line.text and line.to == "claude"  # (Claude's to answer)
    assert sentry_in.run(db) == []  # (once a day)
    assert sentry_in.run(db, now=rules.now() + timedelta(days=1)) == []  # (the same error isn't filed twice)
    job = next(j for j in work_page.jobs(db) if j["key"] == "sentry")
    assert job["result"] == "ok"


def test_sentry_not_answering_is_a_failed_run(db, monkeypatch):
    def down():
        raise TimeoutError

    monkeypatch.setattr(sentry_in, "FETCH", down)
    assert sentry_in.run(db) == [] and db.scalar(select(FftIssue)) is None
    job = next(j for j in work_page.jobs(db) if j["key"] == "sentry")
    assert job["result"] == "failed" and "didn't answer" in job["words"]


def test_off_without_its_key(monkeypatch):
    for k in ("SENTRY_READ_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    assert not sentry_in.enabled()
