"""File storage (app/files.py, VTT 0.5): keys per campaign named by content, served only through askdnd's routes,
pictures kept only in storage, and the nightly sweep that keeps every
kept backup whole."""

import base64
import hashlib
import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import extraction, files, pictures
from app.gdocs import parse_export
from app.importer import import_bundle
from app.models import Campaign, Entity, EntityPicture, NoteImage, NoteSnapshot, NoteSource, StoredFile
from app.notes_sync import store_export
from tests.test_notes_sync import make_zip
from tests.test_pictures import BUNDLE, entity, people, png  # noqa: F401  (people is a fixture)
from tests.test_suggestions import HX

ROOT = Path(__file__).parent.parent


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def campaign(db) -> Campaign:
    import_bundle(db, BUNDLE)
    return db.scalar(select(Campaign))


def test_keys_are_per_campaign_and_named_by_content(db, file_store):
    c = campaign(db)
    key = files.put(db, c.id, b"GIF89a dragon", "image/gif")
    assert key == f"{c.id}/{hashlib.sha256(b'GIF89a dragon').hexdigest()}.gif" and files.get(key) == b"GIF89a dragon"
    assert files.put(db, c.id, b"GIF89a dragon", "image/gif") == key  # the same bytes are stored once
    assert db.get(StoredFile, key).size == 13 and len(list(file_store.list())) == 1
    other = Campaign(slug="other", name="Other")
    db.add(other)
    db.flush()
    assert files.put(db, other.id, b"GIF89a dragon", "image/gif").startswith(f"{other.id}/")


def test_only_listed_kinds_and_sizes_are_kept(db):
    c = campaign(db)
    for data, kind, message in ((b"<svg onload=alert(1)>", "image/svg+xml", "can't keep"), (b"<p>", "text/html", "can't keep"),
                                (b"", "image/png", "empty"), (b"x" * (files.TYPES["image/png"][1] + 1), "image/png", "over 20 MB")):
        with pytest.raises(files.FileError, match=message):
            files.put(db, c.id, data, kind)
    assert db.scalar(select(StoredFile)) is None


def test_the_local_folder_stays_in_its_folder(tmp_path):
    store = files.LocalFolder(tmp_path / "files")
    for bad in ("../outside.png", "/etc/passwd"):
        with pytest.raises(ValueError):
            store.put(bad, b"x", "image/png")


def test_s3_never_reaches_outside_v2_files(monkeypatch):
    calls = []

    class Fake:
        class exceptions:
            NoSuchKey = KeyError

        def __getattr__(self, name):
            def call(**kw):
                calls.append((name, kw))
                return {"Body": type("B", (), {"read": lambda self: b"x"})()}
            return call

        def get_paginator(self, name):
            return type("P", (), {"paginate": lambda self, **kw: calls.append(("list", kw)) or [{"Contents": [{"Key": "v2/files/1/a.png", "LastModified": datetime.now(UTC)}]}]})()

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Fake())
    s3 = files.S3("askdnd-ai")
    s3.put("1/a.png", b"x", "image/png")
    s3.get("1/a.png")
    s3.delete("1/a.png")
    assert [f.key for f in s3.list()] == ["1/a.png"]
    assert [kw.get("Key") or kw.get("Prefix") for _, kw in calls] == ["v2/files/1/a.png"] * 3 + ["v2/files/"]
    assert calls[0][1]["ServerSideEncryption"] == "AES256"


def test_staging_keeps_its_own_files_and_reads_betas(monkeypatch):
    """Staging (Nov 6): its pictures under v2/staging/files/, never beta's v2/files/ (its key can only read there); a
    picture its copy of beta's data names but it hasn't got is read from beta's."""
    from app import config

    calls = []

    class Fake:
        class exceptions:
            NoSuchKey = KeyError

        def put_object(self, **kw):
            calls.append(("put", kw["Key"]))

        def get_object(self, **kw):
            calls.append(("get", kw["Key"]))
            if kw["Key"].startswith("v2/staging/files/2/"):
                raise KeyError(kw["Key"])
            if kw["Key"].startswith("v2/staging/"):  # (S3's answer when the key may not list the folder)
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
            return {"Body": type("B", (), {"read": lambda self: b"beta's"})()}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Fake())
    monkeypatch.setattr(config, "FILE_STORAGE", "s3-staging")
    monkeypatch.setattr(config, "AWS_S3_BUCKET_NAME", "askdnd-ai")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    s3 = files.from_config()
    s3.put("1/a.png", b"x", "image/png")
    assert s3.get("2/b.png") == b"beta's" and s3.get("3/c.png") == b"beta's"
    assert calls == [("put", "v2/staging/files/1/a.png"), ("get", "v2/staging/files/2/b.png"), ("get", "v2/files/2/b.png"),
                     ("get", "v2/staging/files/3/c.png"), ("get", "v2/files/3/c.png")]


def test_storage_is_s3_on_beta_once_its_key_is_set(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "FILE_STORAGE", "s3")
    monkeypatch.setattr(config, "AWS_S3_BUCKET_NAME", "askdnd-ai")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    assert files.from_config() is None  # not set up yet
    monkeypatch.setattr(config, "FILE_STORAGE", "private/files")
    assert files.from_config().root == ROOT / "private" / "files"


def test_an_uploaded_picture_is_stored_and_served_through_askdnd(people, db, file_store):  # noqa: F811
    import_bundle(db, BUNDLE)
    dm, player = people["dm"], people["player"]
    k = entity(db, "Kieran")
    dm.post("/pictures/upload", data={"for": f"entity:{k.id}"}, files={"file": ("k.png", png(), "image/png")}, headers=HX)
    pic = db.scalar(select(EntityPicture))
    assert pic.file_key.startswith(f"{k.campaign_id}/") and pic.thumb_key.endswith(".webp")
    assert file_store.get(pic.file_key) and file_store.get(pic.thumb_key)
    url = pictures.urls(db, [k.id])[k.id]
    assert url["full"].endswith(f"v={files.version(pic.file_key)}")  # a new picture is a new address
    got = player.get(url["thumb"])
    assert got.content == file_store.get(pic.thumb_key) and got.headers["cache-control"] == files.CACHE_FOREVER
    assert got.headers["etag"] == f'"{files.version(pic.thumb_key)}"' and got.headers["x-content-type-options"] == "nosniff"
    for key in (pic.file_key, pic.thumb_key):  # what's in storage changes only through the route's own access check
        assert player.get(f"/files/{key}").status_code == 404


def test_pictures_are_read_only_from_storage(people, db, file_store):  # noqa: F811
    import_bundle(db, BUNDLE)
    k = entity(db, "Kieran")
    key = files.put(db, k.campaign_id, b"RIFF full", "image/webp")
    db.add(EntityPicture(entity_id=k.id, file_key=key, thumb_key=key))
    db.flush()
    player = people["player"]
    url = pictures.urls(db, [k.id])[k.id]
    assert player.get(url["full"]).content == b"RIFF full"
    file_store.delete(key)  # storage lost it
    assert player.get(url["full"]).status_code == 404


def test_a_storage_outage_shows_pictures_missing_and_is_reported_once(people, db, file_store, monkeypatch, caplog):  # noqa: F811
    """S3 not answering: each picture is Not found rather than an error page, and the outage is one report, not one per
    picture."""
    import_bundle(db, BUNDLE)
    k = entity(db, "Kieran")
    key = files.put(db, k.campaign_id, b"RIFF full", "image/webp")
    db.add(EntityPicture(entity_id=k.id, file_key=key, thumb_key=key))
    db.flush()
    url = pictures.urls(db, [k.id])[k.id]

    def down(_key):
        raise TimeoutError("S3 didn't answer")
    monkeypatch.setattr(file_store, "get", down)
    monkeypatch.setitem(files._unreachable, "at", None)
    for _ in range(3):
        assert people["player"].get(url["full"]).status_code == 404
    assert [r.levelname for r in caplog.records if "didn't answer" in r.getMessage()] == ["ERROR"]


def test_without_storage_a_picture_is_refused_not_lost(people, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(files, "storage", lambda: None)
    import_bundle(db, BUNDLE)
    k = entity(db, "Kieran")
    r = people["dm"].post("/pictures/upload", data={"for": f"entity:{k.id}"}, files={"file": ("k.png", png(), "image/png")}, headers=HX)
    assert r.status_code == 409 and "file storage isn't set up" in r.json()["detail"] and db.scalar(select(EntityPicture)) is None


def test_note_images_go_to_storage_and_still_reach_claude(db, file_store):
    c = campaign(db)
    s = NoteSource(campaign_id=c.id, google_doc_id="x" * 30)
    db.add(s)
    db.flush()
    store_export(db, s, parse_export(make_zip()), "Notes")
    img = db.scalar(select(NoteImage))
    assert img.file_key.startswith(f"{c.id}/") and file_store.get(img.file_key) == b"\x89PNG fake"
    file_store.put(img.file_key, b"\x89PNG from storage", "image/png")  # (never happens: just shows where it's read from)
    assert base64.b64decode(extraction._image_block(img, "1")[1]["source"]["data"]) == b"\x89PNG from storage"


def test_the_nightly_sweep_keeps_every_file_a_kept_backup_could_need(db, file_store):
    c = campaign(db)
    k = entity(db, "Kieran")
    used = files.put(db, c.id, b"RIFF used", "image/webp")
    dropped = files.put(db, c.id, b"RIFF dropped", "image/webp")
    db.add(EntityPicture(entity_id=k.id, file_key=used, thumb_key=used))
    db.flush()
    assert {str(col) for col in files.references()} == {"entity_pictures.file_key", "entity_pictures.thumb_key", "note_images.file_key", "feedback.shot_key", "feedback.pasted_key"}
    now = datetime.now(UTC)
    assert files.sweep(db, file_store, now) == {"files": 2, "deleted": 0, "leftovers": 0, "missing": []}
    assert db.get(StoredFile, dropped).unused_since == now and db.get(StoredFile, used).unused_since is None
    # 30 days on, a backup from before it was dropped may still be restored: kept
    assert files.sweep(db, file_store, now + timedelta(days=30))["deleted"] == 0 and file_store.get(dropped)
    # used again before it's deleted: no longer unused
    files.put(db, c.id, b"RIFF dropped", "image/webp")
    assert db.get(StoredFile, dropped).unused_since is None
    db.get(StoredFile, dropped).unused_since = now
    db.flush()
    later = now + timedelta(days=files.KEEP_UNUSED_DAYS + 1)
    file_store.put("9/leftover.png", b"from a change that was rolled back", "image/png")
    old = (later - timedelta(days=files.KEEP_UNUSED_DAYS + 1)).timestamp()
    os.utime(file_store.root / "9" / "leftover.png", (old, old))
    assert files.sweep(db, file_store, later) == {"files": 1, "deleted": 1, "leftovers": 1, "missing": []}
    assert db.get(StoredFile, dropped) is None and {f.key for f in file_store.list()} == {used}
    file_store.delete(used)
    assert files.sweep(db, file_store, later)["missing"] == [used]  # the nightly backup reports it (and fails)


def test_a_note_image_storage_wont_keep_is_left_out(db, file_store):
    c = campaign(db)
    s = NoteSource(campaign_id=c.id, google_doc_id="z" * 30)
    db.add(s)
    db.flush()
    store_export(db, s, parse_export(make_zip(images={"images/a.svg": b"<svg onload=alert(1)>"})), "Notes")
    assert db.scalar(select(NoteSnapshot)) is not None and db.scalar(select(NoteImage)) is None


def test_pull_beta_downloads_only_the_files_it_lacks(tmp_path, file_store):
    fetch = _script("fetch_files").fetch
    source = files.LocalFolder(tmp_path / "s3")
    for key in ("1/a.webp", "1/b.webp"):
        source.put(key, key.encode(), "image/webp")
    file_store.put("1/a.webp", b"1/a.webp", "image/webp")
    assert fetch(["1/a.webp", "1/b.webp"], source, file_store) == 1 and file_store.get("1/b.webp") == b"1/b.webp"


def test_entities_merged_keep_their_picture_file(db, file_store):
    from app import entities

    c = campaign(db)
    k, w = entity(db, "Kieran"), entity(db, "Womford")
    key = files.put(db, c.id, b"RIFF k", "image/webp")
    db.add(EntityPicture(entity_id=k.id, file_key=key, thumb_key=key))
    db.flush()
    entities.merge(db, k, w)
    assert db.scalar(select(EntityPicture)).entity_id == w.id and db.get(Entity, k.id) is None
    assert files.sweep(db, file_store)["files"] == 1 and db.get(StoredFile, key).unused_since is None


def test_the_database_connection_goes_back_before_the_download(monkeypatch):
    """2026-10-24 on beta: a page of 23 pictures held the database's 15 connections while S3 answered, and the last
    ones waited 30 s and failed. The connection must go back before the file is fetched."""
    order = []

    class Session:
        def commit(self):
            order.append("connection back")

    monkeypatch.setattr(files, "read", lambda key: order.append("download") or b"RIFF")
    assert files.serve("1/abc.webp", "image/webp", release=Session()).body == b"RIFF"
    assert order == ["connection back", "download"]


def test_s3_has_timeouts_and_room_for_a_page_of_pictures(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    s3 = files.S3("bucket", "us-east-2").s3
    assert s3.meta.config.max_pool_connections >= 30
    assert s3.meta.config.connect_timeout <= 10 and s3.meta.config.read_timeout <= 30
