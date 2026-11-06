"""askdnd's file storage: pictures now; maps, handouts, tokens and audio later (VTT 0.5).

Files live in S3 under v2/files/ on beta (the bucket is shared with the legacy app, so nothing here ever reaches
outside that prefix) and in a local folder otherwise (private/files/, or FILE_STORAGE). Each file's key is
"<campaign id>/<sha256 of its bytes>.<ext>": the same bytes in the same campaign are stored once, and what a key
holds never changes, so browsers may keep a copy for good.

    key = files.put(db, campaign_id, data, "image/webp")   # checks type and size, records it in stored_files
    data = files.get(key)
    files.serve(key, content_type)                         # a response for askdnd's own routes

Files are never public links: each feature serves them from its own route, after its own access check, through
serve(). Nothing deletes a file directly. Rows that use one point at stored_files with a foreign key, and every
night, after the backup, sweep() deletes files nothing has used for longer than backups are kept, so restoring any
kept backup finds every file it names (docs/DECISIONS.md, 2026-10-24).
"""

import hashlib
import logging
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import config
from app.db import Base
from app.models import StoredFile

log = logging.getLogger(__name__)

PREFIX = "v2/files/"
STAGING_PREFIX = "v2/staging/files/"  # staging's own (FILE_STORAGE=s3-staging; docs/SETUP_LOG.md › A staging copy)
ROOT = Path(__file__).resolve().parent.parent
# What may be stored, and how big. Add a type here when a feature needs it (audio for 4.2, PDFs for handouts);
# never anything a browser would run (HTML, SVG, scripts): files are served from askdnd's own address.
TYPES = {
    "image/webp": (".webp", 20 * 1024 * 1024),
    "image/png": (".png", 20 * 1024 * 1024),
    "image/jpeg": (".jpg", 20 * 1024 * 1024),
    "image/gif": (".gif", 20 * 1024 * 1024),
}
# Backups are kept 30 days (app/backup.py); a few days more covers a missed night or two.
KEEP_UNUSED_DAYS = 35
CACHE_FOREVER = "private, max-age=31536000, immutable"  # private: Cloudflare never keeps a copy past the access check


class FileError(Exception):
    """A file that can't be stored (wrong type, too big), with a message for the person adding it."""


class StorageNotReady(Exception):
    pass


@dataclass(frozen=True)
class Stored:
    key: str
    modified: datetime


class LocalFolder:
    """For local development and tests."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"Not a file key: {key}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # written whole or not at all

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self) -> Iterator[Stored]:
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.is_file() and not path.name.endswith(".part"):
                    yield Stored(path.relative_to(self.root).as_posix(), datetime.fromtimestamp(path.stat().st_mtime, UTC))


class S3:
    """S3 under v2/files/ only. The app's key can read and write there (not delete); the backup service's can also
    list and delete, for sweep(). Staging keeps its own under v2/staging/files/ and reads beta's from v2/files/ when
    it hasn't one (its key can only read there), so it shows the pictures its copy of beta's data names."""

    def __init__(self, bucket: str, region: str | None = None, prefix: str = PREFIX, read_also: str | None = None):
        import boto3
        from botocore.config import Config

        self.bucket, self.prefix, self.read_also = bucket, prefix, read_also
        # One client for the whole app (it's thread-safe once made). Room for a page of pictures at once, and timeouts
        # so a slow answer from S3 fails in seconds instead of holding a request (2026-10-24: 23 pictures at once,
        # with no timeouts and a client made per first request, held the database's connections until they ran out).
        self.s3 = boto3.client("s3", region_name=region or None,
                               config=Config(max_pool_connections=50, connect_timeout=5, read_timeout=20,
                                             retries={"max_attempts": 3, "mode": "standard"}))

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=content_type,
                           ServerSideEncryption="AES256")

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        for prefix in (self.prefix, self.read_also) if self.read_also else (self.prefix,):
            try:
                return self.s3.get_object(Bucket=self.bucket, Key=prefix + key)["Body"].read()
            except self.s3.exceptions.NoSuchKey:
                continue
            except ClientError as e:  # (staging's key can't list its folder, so S3 says "denied" for a file it hasn't got)
                if not (self.read_also and prefix == self.prefix and e.response.get("Error", {}).get("Code") in ("AccessDenied", "403")):
                    raise
        raise FileNotFoundError(key)

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=self.prefix + key)

    def list(self) -> Iterator[Stored]:
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            for o in page.get("Contents") or []:
                yield Stored(o["Key"].removeprefix(self.prefix), o["LastModified"])


def from_config():
    """FILE_STORAGE: "s3" (the default on beta), "s3-staging" (staging: its own folder in S3, reading beta's too) or a
    folder (the default locally: private/files)."""
    where = config.FILE_STORAGE
    if where not in ("s3", "s3-staging"):
        return LocalFolder(ROOT / where)
    if not (config.AWS_S3_BUCKET_NAME and os.getenv("AWS_ACCESS_KEY_ID")):
        return None
    if where == "s3-staging":
        return S3(config.AWS_S3_BUCKET_NAME, config.AWS_REGION, prefix=STAGING_PREFIX, read_also=PREFIX)
    return S3(config.AWS_S3_BUCKET_NAME, config.AWS_REGION)


_making = threading.Lock()


@cache
def _made():
    return from_config()


def storage():
    """The storage, made once: the first requests can arrive together, and boto3 isn't safe to set up in parallel."""
    with _making:
        return _made()


storage.cache_clear = _made.cache_clear  # (tests reset it)


def _store():
    s = storage()
    if s is None:
        raise StorageNotReady("File storage isn't set up (FILE_STORAGE=s3 needs AWS_S3_BUCKET_NAME and a key).")
    return s


def check(data: bytes, content_type: str) -> None:
    if content_type not in TYPES:
        raise FileError("askdnd can't keep that kind of file.")
    if not data:
        raise FileError("That file is empty.")
    limit = TYPES[content_type][1]
    if len(data) > limit:
        raise FileError(f"That file is over {limit // (1024 * 1024)} MB.")


def key_for(campaign_id: int, data: bytes, content_type: str) -> str:
    return f"{int(campaign_id)}/{hashlib.sha256(data).hexdigest()}{TYPES[content_type][0]}"


def version(key: str | None) -> str:
    """A short, stable part of the key, for ?v= in addresses."""
    return key.rsplit("/", 1)[-1].split(".", 1)[0][:16] if key else ""


def put(db: Session, campaign_id: int, data: bytes, content_type: str) -> str:
    """Store `data` for a campaign and return its key. Storing the same bytes again is harmless.

    The row is written (or marked in use again) before the file, so a nightly sweep running at the same moment
    either sees it in use or has finished deleting before this writes the file back."""
    check(data, content_type)
    store = _store()
    key = key_for(campaign_id, data, content_type)
    db.execute(insert(StoredFile).values(key=key, campaign_id=campaign_id, content_type=content_type, size=len(data))
               .on_conflict_do_update(index_elements=[StoredFile.key], set_={"unused_since": None}))
    store.put(key, data, content_type)
    return key


def get(key: str) -> bytes:
    """The file's bytes; FileNotFoundError if storage doesn't have it."""
    return _store().get(key)


def delete(key: str) -> None:
    """Remove a file from storage. Only sweep() calls this: a kept backup may still name a file nothing uses now."""
    _store().delete(key)


_unreachable: dict = {"at": None}  # when storage last failed to answer, so an outage is reported once, not once per picture


def read(key: str | None) -> bytes | None:
    """The file at `key`, or None if there's no key, storage doesn't have it, or storage doesn't answer (a page of
    pictures then shows them missing instead of failing; the outage is reported at most every 10 minutes)."""
    if not key:
        return None
    try:
        return get(key)
    except FileNotFoundError:
        log.warning("File %s is listed but storage doesn't have it", key)
    except StorageNotReady:
        raise  # (set up wrong: that's for the deploy to show, not a missing picture)
    except Exception:  # noqa: BLE001 - storage unreachable or refusing
        if _unreachable["at"] is None or time.monotonic() - _unreachable["at"] > 600:
            _unreachable["at"] = time.monotonic()
            log.error("File storage didn't answer for %s; pictures show as missing until it does", key, exc_info=True)
    return None


def serve(key: str | None, content_type: str, cache_control: str = CACHE_FOREVER, release: Session | None = None):
    """A response with the file, for a route that has already checked who may see it. Addresses carry the key's
    version (?v=), so the response can be cached for good.

    `release`: the route's database session. Its read-only transaction ends before the download, which hands its
    connection back, so a page of pictures never holds the database's connections while S3 answers."""
    from fastapi import Response

    if release is not None:
        release.commit()  # nothing to save: ending the transaction is what returns the connection
    data = read(key)
    if data is None:
        return Response(status_code=404)
    headers = {"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff", "ETag": f'"{version(key)}"'}
    return Response(data, media_type=content_type, headers=headers)


# --- Nightly: which files are used, deleting old unused ones, checking every listed file is there ---------------


def references():
    """Every column that uses a stored file (a foreign key to stored_files.key)."""
    return [fk.parent for t in Base.metadata.sorted_tables for fk in t.foreign_keys if fk.column.table.name == StoredFile.__tablename__]


def _in_use():
    return or_(*[exists().where(col == StoredFile.key) for col in references()])


def sweep(db: Session, store=None, now: datetime | None = None) -> dict:
    """Run after the night's backup: note which files nothing uses, delete files unused for KEEP_UNUSED_DAYS (no
    kept backup names them), delete leftovers storage has but the database never recorded (an upload whose change
    was rolled back), and report files the database lists that storage doesn't have. Commits as it goes."""
    store = store or _store()
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=KEEP_UNUSED_DAYS)
    db.execute(update(StoredFile).where(StoredFile.unused_since.is_(None), ~_in_use()).values(unused_since=now)
               .execution_options(synchronize_session=False))
    db.execute(update(StoredFile).where(StoredFile.unused_since.is_not(None), _in_use()).values(unused_since=None)
               .execution_options(synchronize_session=False))
    db.commit()
    deleted = 0
    for key in db.scalars(select(StoredFile.key).where(StoredFile.unused_since < cutoff)).all():
        # Locks the row: a change starting to use this file again (put, or a new reference) waits for this one.
        row = db.scalar(select(StoredFile).where(StoredFile.key == key, StoredFile.unused_since < cutoff, ~_in_use())
                        .with_for_update())
        if row is not None:
            store.delete(key)
            db.delete(row)
            deleted += 1
        db.commit()
    listed = set(db.scalars(select(StoredFile.key)))
    present, leftovers = set(), 0
    for f in store.list():
        present.add(f.key)
        if f.key not in listed and f.modified < cutoff and db.get(StoredFile, f.key) is None:
            store.delete(f.key)
            leftovers += 1
    return {"files": len(listed), "deleted": deleted, "leftovers": leftovers, "missing": sorted(listed - present)}
