"""A pause isn't a nuclear option (issue 110, Brett, Nov 23: "I would want inflight work to finish, not stop"): main's
commit merged before the pause finishes going live; anything after it waits. The public answer never says when the
pause began (only whether a given commit goes)."""

from datetime import timedelta

from app.fft import rules


def test_a_merge_before_the_pause_goes_and_one_after_waits(admin, db):
    assert admin.get("/api/fft/freeze", params={"merged": "2026-11-23T11:29:00-08:00"}).json() == {"frozen": False, "goes": True}
    rules.set_freeze(db, "user:1", True, why="Game night")
    db.flush()
    since = rules.freeze_state(db)["since"]
    when = rules.now()
    before, after = (when - timedelta(minutes=1)).isoformat(), (when + timedelta(minutes=1)).isoformat()
    assert admin.get("/api/fft/freeze", params={"merged": before}).json() == {"frozen": True, "goes": True}
    assert admin.get("/api/fft/freeze", params={"merged": after}).json() == {"frozen": True, "goes": False}
    assert admin.get("/api/fft/freeze", params={"merged": "not a time"}).json() == {"frozen": True, "goes": False}
    stamp = str(int((when - timedelta(minutes=1)).timestamp()))  # (GitHub's push time: epoch seconds)
    assert admin.get("/api/fft/freeze", params={"merged": stamp}).json() == {"frozen": True, "goes": True}
    assert admin.get("/api/fft/freeze", params={"merged": str(int((when + timedelta(minutes=1)).timestamp()))}).json()["goes"] is False
    naive = (when - timedelta(minutes=1)).replace(tzinfo=None).isoformat()  # (no offset: waits, never a 500)
    r = admin.get("/api/fft/freeze", params={"merged": naive})
    assert r.status_code == 200 and r.json()["goes"] is False
    assert admin.get("/api/fft/freeze", params={"merged": "9" * 30}).json()["goes"] is False
    assert admin.get("/api/fft/freeze").json() == {"frozen": True}  # (no commit: only whether it's on)
    assert since not in admin.get("/api/fft/freeze", params={"merged": before}).text  # (never when it began)
