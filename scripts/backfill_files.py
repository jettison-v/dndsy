"""Copy the pictures kept in the database into file storage (VTT 0.5, step 3 of "add before remove").

    uv run python scripts/backfill_files.py              # the local database, into private/files
    uv run python scripts/backfill_files.py --dry-run    # only count what it would copy
    railway ssh --service askdnd-v2 -- python scripts/backfill_files.py   # beta, into S3 (only when Brett says so)

Every entity picture (full size and thumbnail) and note image without a storage key is stored with app/files.py,
read back and compared byte for byte, and only then given its key. Afterwards every picture that has a key is
checked against its database copy the same way. Running it again is safe: finished ones are skipped. It never
changes or removes the database copies; a later migration removes them, once this run is checked on beta.
Exits with an error if anything didn't copy or doesn't match.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import files  # noqa: E402
from app.models import Entity, EntityPicture, NoteImage, NoteSnapshot, NoteSource  # noqa: E402

BATCH = 25


def _copies(db: Session):
    """(row, key column, blob column, campaign id) for every database copy of a picture."""
    pics = db.execute(select(EntityPicture, Entity.campaign_id).join(Entity, Entity.id == EntityPicture.entity_id)
                      .order_by(EntityPicture.id)).all()  # the bytes load one picture at a time (deferred)
    for pic, campaign_id in pics:
        yield pic, "file_key", "data", campaign_id
        yield pic, "thumb_key", "thumb", campaign_id
    images = db.execute(select(NoteImage, NoteSource.campaign_id).join(NoteSnapshot, NoteSnapshot.id == NoteImage.snapshot_id)
                        .join(NoteSource, NoteSource.id == NoteSnapshot.source_id).order_by(NoteImage.id)).all()
    for img, campaign_id in images:
        yield img, "file_key", "data", campaign_id


def backfill(db: Session, dry_run: bool = False, say=print) -> dict:
    if not files.ready():
        raise SystemExit("File storage isn't set up here (FILE_STORAGE=s3 needs AWS_S3_BUCKET_NAME and a key).")
    counts = {"copied": 0, "already": 0, "skipped": 0, "checked": 0, "problems": 0}
    pending = 0
    for row, key_col, blob_col, campaign_id in _copies(db):
        what = f"{type(row).__tablename__} {row.id} {blob_col}"
        if getattr(row, key_col):
            counts["already"] += 1
            continue
        data = getattr(row, blob_col)
        db.expire(row, [blob_col])  # let the bytes go once this one is done
        try:
            files.check(data, row.content_type)
        except files.FileError as e:
            say(f"Skipped {what} ({row.content_type}): {e}")
            counts["skipped"] += 1
            continue
        if dry_run:
            counts["copied"] += 1
            continue
        key = files.put(db, campaign_id, data, row.content_type)
        if files.get(key) != data:
            say(f"PROBLEM: {what} didn't read back the same from storage ({key})")
            counts["problems"] += 1
            continue
        setattr(row, key_col, key)
        counts["copied"] += 1
        pending += 1
        if pending >= BATCH:
            db.commit()
            pending = 0
    if not dry_run:
        db.commit()
        for row, key_col, blob_col, _ in _copies(db):
            key = getattr(row, key_col)
            if key:
                counts["checked"] += 1
                try:
                    same = files.get(key) == getattr(row, blob_col)
                except FileNotFoundError:
                    same = False
                if not same:
                    say(f"PROBLEM: {type(row).__tablename__} {row.id} {blob_col} differs from {key} in storage")
                    counts["problems"] += 1
                db.expire(row, [blob_col])
    return counts


def main() -> None:
    from app.db import SessionLocal

    dry_run = "--dry-run" in sys.argv
    with SessionLocal() as db:
        counts = backfill(db, dry_run=dry_run)
    verb = "Would copy" if dry_run else "Copied"
    print(f"{verb} {counts['copied']} · already in storage {counts['already']} · skipped {counts['skipped']}"
          + ("" if dry_run else f" · checked {counts['checked']} against the database · problems {counts['problems']}"))
    if counts["problems"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
