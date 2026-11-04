"""Pictures on campaign pages (app/pictures.py), added in the one Picture window (app/picture_window.py): the DM and
reviewers add them; everyone sees them."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import characters, ddb, pictures
from app.importer import import_bundle
from app.main import app
from app.models import Character, Entity, EntityPicture, Status, User
from tests.test_suggestions import HX, client_for
from tests.roles import set_role

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
    set_role(db, "dm@example.com")
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


def test_the_dm_adds_a_picture_in_the_picture_window_everyone_sees_it(people, db):
    import_bundle(db, BUNDLE)
    dm, player = people["dm"], people["player"]
    k = entity(db, "Kieran")
    ref = {"for": f"entity:{k.id}"}
    assert f'data-modal-url="/pictures?for=entity:{k.id}"' in dm.get(f"/campaign/{k.id}/edit").text
    assert "Add a picture" not in player.get(f"/campaign/{k.id}/peek").text
    assert "Describe it" in dm.get(f"/pictures?for=entity:{k.id}").text and player.get(f"/pictures?for=entity:{k.id}").status_code == 404
    r = player.post("/pictures/upload", data=ref, files={"file": ("k.png", png(), "image/png")}, headers=HX)
    assert r.status_code == 404 and db.scalar(select(EntityPicture)) is None
    r = dm.post("/pictures/upload", data=ref, files={"file": ("k.png", png(), "image/png")}, headers=HX)
    assert r.status_code == 204 and "Picture saved" in r.headers["HX-Trigger"] and r.headers["HX-Refresh"] == "true"
    url = pictures.urls(db, [k.id])[k.id]
    assert url["uploaded"] and url["source"] == "upload" and url["thumb"].startswith(f"/campaign/{k.id}/picture?size=thumb&v=")
    got = player.get(url["thumb"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp" and "immutable" in got.headers["cache-control"]
    assert url["full"] in player.get(f"/campaign/{k.id}/peek").text
    k.status = Status.PUBLISHED
    db.flush()
    assert url["full"].replace("&", "&amp;") in player.get(f"/c/main/campaign?open={k.id}").text  # in the Campaign page's Reader
    r = dm.post("/pictures/upload", data=ref, files={"file": ("x.txt", b"not a picture", "text/plain")}, headers=HX)
    assert r.status_code == 409 and "isn't a picture" in r.json()["detail"]
    assert "Remove picture" in dm.get(f"/pictures?for=entity:{k.id}").text
    dm.post("/pictures/remove", data=ref, headers=HX)
    assert db.scalar(select(EntityPicture)) is None and player.get(url["thumb"]).status_code == 404


def test_player_characters_use_their_d_and_d_beyond_portrait(people, db, monkeypatch):
    from tests.table_setup import BUNDLE as CHAR_BUNDLE
    from tests.table_setup import fake_fetch

    monkeypatch.setattr(characters, "FETCH", fake_fetch)
    import_bundle(db, CHAR_BUNDLE)
    cole = next(c for c in db.scalars(select(Character)) if c.name == "Cole")
    characters.refresh(db, cole)
    portrait = characters.character_summary(cole)["portrait"]
    assert portrait.startswith("https://www.dndbeyond.com/avatars/")
    assert pictures.urls(db, [cole.entity.id])[cole.entity.id] == {"thumb": portrait, "full": pictures.ddb_full(portrait), "uploaded": False}
    player = people["player"]
    assert portrait.replace("&", "&amp;") in player.get(f"/characters/{cole.id}").text
    assert "From D&amp;D Beyond" in player.get(f"/campaign/{cole.entity.id}/peek").text
    assert ddb.parse_character  # parser keeps only dndbeyond.com portraits (see test_ddb)
