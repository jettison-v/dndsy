"""Pictures on campaign pages (app/pictures.py): the DM and reviewers add them; everyone sees them."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import characters, ddb, pictures
from app.importer import import_bundle
from app.main import app
from app.models import Character, Entity, EntityPicture, Status, User
from tests.test_suggestions import HX, client_for

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main"},
    "entities": [{"kind": "npc", "name": "Kieran", "summary": "Cole's father."}, {"kind": "place", "name": "Womford", "summary": "A village."}],
}


def png(w=1600, h=900, color=(200, 40, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def people(monkeypatch, db):
    db.add(User(email="dm@example.com", name="Dee", is_dm=True))
    db.flush()
    yield {"dm": client_for(monkeypatch, db, "dm@example.com"), "player": client_for(monkeypatch, db, "mark@example.com")}
    app.dependency_overrides.clear()


def entity(db, name) -> Entity:
    return db.scalar(select(Entity).where(Entity.name == name))


def test_process_resizes_and_rejects_non_pictures():
    full, thumb = pictures.process(png())
    assert Image.open(io.BytesIO(full)).size == (1200, 675) and Image.open(io.BytesIO(thumb)).size == (320, 320)
    assert Image.open(io.BytesIO(full)).format == "WEBP"
    for bad, message in ((b"", "Choose a picture"), (b"<svg onload=alert(1)>", "isn't a picture"), (b"x" * (pictures.MAX_UPLOAD + 1), "over 15 MB")):
        with pytest.raises(pictures.PictureError, match=message):
            pictures.process(bad)


def test_the_dm_adds_a_picture_everyone_sees_it(people, db):
    import_bundle(db, BUNDLE)
    dm, player = people["dm"], people["player"]
    k = entity(db, "Kieran")
    assert "Add a picture" in dm.get(f"/campaign/{k.id}/edit").text and "Add a picture" not in player.get(f"/campaign/{k.id}/peek").text
    r = player.post(f"/campaign/{k.id}/picture", files={"file": ("k.png", png(), "image/png")}, headers=HX)
    assert "Only the DM and reviewers" in r.headers["HX-Trigger"] and db.scalar(select(EntityPicture)) is None
    r = dm.post(f"/campaign/{k.id}/picture", files={"file": ("k.png", png(), "image/png")}, headers=HX)
    assert "Picture saved" in r.headers["HX-Trigger"] and "Change picture" in r.text
    url = pictures.urls(db, [k.id])[k.id]
    assert url["uploaded"] and url["thumb"].startswith(f"/campaign/{k.id}/picture?size=thumb&v=")
    got = player.get(url["thumb"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp" and "immutable" in got.headers["cache-control"]
    assert url["full"] in player.get(f"/campaign/{k.id}/peek").text
    k.status = Status.PUBLISHED
    db.flush()
    assert url["thumb"].replace("&", "&amp;") in player.get("/campaign").text
    r = dm.post(f"/campaign/{k.id}/picture", files={"file": ("x.txt", b"not a picture", "text/plain")}, headers=HX)
    assert "isn't a picture" in r.headers["HX-Trigger"]
    dm.post(f"/campaign/{k.id}/picture/delete", headers=HX)
    assert db.scalar(select(EntityPicture)) is None and player.get(url["thumb"]).status_code == 404


def test_player_characters_use_their_d_and_d_beyond_portrait(people, db, monkeypatch):
    from tests.test_characters import BUNDLE as CHAR_BUNDLE
    from tests.test_characters import fake_fetch

    monkeypatch.setattr(characters.refresh, "__defaults__", (fake_fetch,))
    import_bundle(db, CHAR_BUNDLE)
    cole = next(c for c in db.scalars(select(Character)) if c.entity.name == "Cole")
    characters.refresh(db, cole)
    portrait = characters.character_summary(cole)["portrait"]
    assert portrait.startswith("https://www.dndbeyond.com/avatars/")
    assert pictures.urls(db, [cole.entity_id])[cole.entity_id] == {"thumb": portrait, "full": pictures.ddb_full(portrait), "uploaded": False}
    player = people["player"]
    assert portrait.replace("&", "&amp;") in player.get(f"/characters/{cole.id}").text
    assert "From D&amp;D Beyond" in player.get(f"/campaign/{cole.entity_id}/peek").text
    assert ddb.parse_character  # parser keeps only dndbeyond.com portraits (see test_ddb)
