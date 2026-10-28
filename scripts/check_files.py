"""Check, read-only, that every picture the database still keeps a copy of is in file storage, byte for byte (VTT 0.5,
before the database copies are removed).

    uv run python scripts/check_files.py                                   # the local database and private/files
    railway ssh --service askdnd-v2 -- python scripts/check_files.py      # beta and S3

For every entity picture (full size and thumbnail) and note image: does it have a storage key, does storage have
that file, and are the bytes the same as the database copy (and named by their own sha256, as keys are)? Then every
other file stored_files lists is looked for in storage. Changes nothing: the database is read in a read-only transaction
and storage is only read. Exits with an error if anything is missing or differs.
"""

import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import files  # noqa: E402
from app.models import EntityPicture, NoteImage, StoredFile  # noqa: E402

COPIES = ((EntityPicture, "file_key", "data", "picture"), (EntityPicture, "thumb_key", "thumb", "thumbnail"),
          (NoteImage, "file_key", "data", "note image"))
PROBLEMS = ("no key", "not in storage", "differs")


def check(db: Session, store, say=print) -> dict:
    """{what: Counter(same=…, no key=…, not in storage=…, differs=…)} plus "listed" and "missing" for stored_files."""
    db.execute(text("SET TRANSACTION READ ONLY"))
    out, seen = {}, set()
    for model, key_col, blob_col, what in COPIES:
        counts = out[what] = Counter()
        for row_id, key, content_type in db.execute(select(model.id, getattr(model, key_col), model.content_type)
                                                    .order_by(model.id)).all():
            data = db.scalar(select(getattr(model, blob_col)).where(model.id == row_id))  # one at a time
            if not key:
                counts["no key"] += 1
                say(f"No key: {model.__tablename__} {row_id} {blob_col} ({content_type}, {len(data or b''):,} bytes)")
                continue
            seen.add(key)
            try:
                stored = store.get(key)
            except FileNotFoundError:
                counts["not in storage"] += 1
                say(f"Not in storage: {model.__tablename__} {row_id} {blob_col} ({key})")
                continue
            if stored != data or hashlib.sha256(stored).hexdigest() not in key:
                counts["differs"] += 1
                say(f"Differs: {model.__tablename__} {row_id} {blob_col} ({key})")
                continue
            counts["same"] += 1
    listed = db.scalars(select(StoredFile.key)).all()
    missing = sorted(key for key in set(listed) - seen if not _there(store, key))  # read, not listed: the app's key can't list
    for key in missing:
        say(f"Listed but not in storage: {key}")
    out["listed"], out["missing"] = len(listed), len(missing)
    db.rollback()
    return out


def _there(store, key: str) -> bool:
    try:
        store.get(key)
        return True
    except FileNotFoundError:
        return False


def problems(result: dict) -> int:
    return sum(result[what][p] for _, _, _, what in COPIES for p in PROBLEMS) + result["missing"]


def main() -> None:
    from app.db import SessionLocal

    store = files.storage()
    if store is None:
        sys.exit("File storage isn't set up here (FILE_STORAGE=s3 needs AWS_S3_BUCKET_NAME and a key).")
    with SessionLocal() as db:
        result = check(db, store)
    for _, _, _, what in COPIES:
        c = result[what]
        print(f"{what.capitalize()}s: {sum(c.values()):,} in the database · {c['same']:,} the same in storage"
              + "".join(f" · {p} {c[p]:,}" for p in PROBLEMS if c[p]))
    print(f"Files listed: {result['listed']:,} · missing from storage {result['missing']:,}")
    print(f"Problems: {problems(result):,}")
    if problems(result):
        sys.exit(1)


if __name__ == "__main__":
    main()
