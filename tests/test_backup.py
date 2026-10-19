"""Whole-database backups (app/backup.py): a dump can be loaded back exactly, and
old-backup cleanup never reaches outside v2/backups/."""

from datetime import date

from sqlalchemy import select, text

from app import backup
from app.importer import import_bundle
from app.models import Entity, EntityPicture, Revision


def test_a_backup_restores_every_row(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "entities": [{"kind": "place", "name": "Oakhurst", "summary": "A town."}]})
    oak = db.scalar(select(Entity))
    db.add(EntityPicture(entity_id=oak.id, data=b"\x00\x01png", thumb=b"t"))
    oak.summary = "Myna's hometown."
    db.flush()
    conn = db.connection()
    data = backup.from_bytes(backup.to_bytes(backup.dump(conn)))
    assert data["tables"]["entities"][0]["summary"] == "Myna's hometown."
    for t in reversed(backup.tables()):  # empty the database, then restore
        conn.execute(t.delete())
    counts = backup.load(conn, data)
    assert counts["entities"] == 1 and counts["revisions"] >= 1
    db.expire_all()
    restored = db.scalar(select(Entity))
    assert restored.summary == "Myna's hometown." and db.scalar(select(EntityPicture)).data == b"\x00\x01png"
    assert db.scalar(select(Revision)).new == "Myna's hometown."
    assert conn.execute(text("select nextval(pg_get_serial_sequence('entities', 'id'))")).scalar() > restored.id


def test_cleanup_only_touches_old_backups_in_v2():
    keys = ["v2/backups/askdnd-2026-08-01.json.gz", "v2/backups/askdnd-2026-10-18.json.gz",
            "pdfs/players-handbook.pdf", "backups/askdnd-2026-01-01.json.gz", "v2/backups/notes.txt"]
    assert backup.old_keys(keys, date(2026, 10, 19)) == ["v2/backups/askdnd-2026-08-01.json.gz"]
    assert backup.key_for(date(2026, 10, 19)) == "v2/backups/askdnd-2026-10-19.json.gz"


def test_overview_flags_missing_failed_and_overdue_backups(db):
    from datetime import UTC, datetime, timedelta

    from app.manage import backup_status
    from app.models import JobRun

    assert backup_status(db)["attention"] and backup_status(db)["text"] == "No backup recorded yet"
    now = datetime.now(UTC)
    db.add(JobRun(name="backup", status="ok", detail="v2/backups/x", started_at=now, finished_at=now - timedelta(hours=3)))
    db.flush()
    st = backup_status(db)
    assert not st["attention"] and st["text"] == "Last backup 3 hours ago"
    db.add(JobRun(name="backup", status="ok", detail="", started_at=now, finished_at=now - timedelta(hours=40)))
    db.flush()  # newest by id is now the 40-hour-old one: a missed night
    assert backup_status(db)["attention"] and "(overdue)" in backup_status(db)["text"]
    db.add(JobRun(name="backup", status="error", detail="AccessDenied", started_at=now, finished_at=now))
    db.flush()
    assert backup_status(db)["text"].startswith("Last backup failed")
