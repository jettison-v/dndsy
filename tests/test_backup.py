"""Whole-database backups (app/backup.py): a dump can be loaded back exactly, and
old-backup cleanup never reaches outside v2/backups/."""

from datetime import date

from sqlalchemy import select, text

from app import backup, files
from app.importer import import_bundle
from app.models import Entity, EntityPicture, Revision


def test_a_backup_restores_every_row(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "entities": [{"kind": "place", "name": "Oakhurst", "summary": "A town."}]})
    oak = db.scalar(select(Entity))
    key = files.put(db, oak.campaign_id, b"RIFF oak", "image/webp")
    db.add(EntityPicture(entity_id=oak.id, file_key=key, thumb_key=key))
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
    assert restored.summary == "Myna's hometown." and db.scalar(select(EntityPicture)).file_key == key
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
    assert backup_status(db)["attention"] and backup_status(db)["text"] == "No backup for 1 night"  # (Brett's pick BK1: the nights missed)
    db.add(JobRun(name="backup", status="error", detail="AccessDenied", started_at=now, finished_at=now))
    db.flush()
    assert backup_status(db)["text"].startswith("Last backup failed")


def test_a_backup_rows_numbers_survive_a_night_that_swept_files():
    """The end-of-day review (Nov 25): a night that also deleted unused files adds ", 3 deleted unused" after its count,
    and the Files column went blank."""
    from types import SimpleNamespace

    from app.admin import backup_row

    run = SimpleNamespace(status="ok", detail="v2/backups/x.json.gz · 4.8 MB · 10,682 rows · 236 files, 3 deleted unused, 1 leftovers deleted")
    row = backup_row(run)
    assert (row["size"], row["rows"], row["files"]) == ("4.8 MB", "10,682", "236")
