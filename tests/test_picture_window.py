"""The one Picture window's Describe it and the campaign's art style (app/picture_window.py, app/drawing.py; Brett,
2026-11-04, docs/mockups/pictures/): four drawn to pick from in the campaign's style, counted under the monthly limit.
OpenAI is never called: drawing.FETCH stands in for it."""

import base64

import pytest
from sqlalchemy import select

from app import drawing, pictures, spending
from app.importer import import_bundle
from app.models import Campaign, EntityPicture, ExtractionRun
from tests.test_pictures import BUNDLE, entity, people, png  # noqa: F401 (people is a fixture)
from tests.test_suggestions import HX


@pytest.fixture
def openai(monkeypatch):
    """A stand-in for OpenAI's Images API: four pictures, each call noted."""
    calls = []

    def fake(path, fields, files):
        calls.append({"path": path, "fields": fields, "files": files})
        return {"data": [{"b64_json": base64.b64encode(png(64, 64, (10 * i, 80, 120))).decode()} for i in range(fields["n"])]}
    monkeypatch.setattr(drawing, "FETCH", fake)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return calls


def test_describe_it_draws_four_in_the_campaigns_style_and_one_is_kept(people, db, openai):
    """A standing rule (CLAUDE.md: set and respect a monthly spend limit): each drawing is counted on Manage › Usage and
    refused once the limit is reached. Only the words, the style and its pictures are sent."""
    import_bundle(db, BUNDLE)
    dm = people["dm"]
    k = entity(db, "Kieran")
    ref = {"for": f"entity:{k.id}"}
    campaign = db.get(Campaign, k.campaign_id)
    campaign.art_style = {"words": "Ink and muted watercolour", "refs": []}
    db.flush()
    win = dm.get(f"/pictures?for=entity:{k.id}").text
    assert "Kieran: Cole&#39;s father." in win and "Ink and muted watercolour" in win and "head-and-shoulders portrait" in win
    r = dm.post("/pictures/draw", data={**ref, "words": "Kieran, a tired farmer"}, headers=HX)
    assert r.status_code == 200 and r.text.count('name="pick"') == 4
    call, = openai
    assert call["path"] == "generations" and call["fields"]["n"] == 4 and call["fields"]["model"] == drawing.MODEL
    assert "Kieran, a tired farmer" in call["fields"]["prompt"] and "Ink and muted watercolour" in call["fields"]["prompt"]
    assert "head-and-shoulders portrait" in call["fields"]["prompt"] and call["fields"]["size"] == "1024x1024"  # (an NPC: a portrait)
    run = db.scalar(select(ExtractionRun).where(ExtractionRun.source == "picture"))
    assert run.status == "done" and run.cost_usd == pytest.approx(4 * drawing.COST)
    pick = r.text.split('name="pick" value="')[1].split('"')[0]
    r = dm.post("/pictures/use", data={**ref, "pick": pick, "words": "Kieran, a tired farmer", "style": "Ink and muted watercolour"}, headers=HX)
    assert r.status_code == 200 and "Last step: frame it" in r.text  # (then Frame it)
    pic = db.scalar(select(EntityPicture))
    assert (pic.source, pic.words, pic.style) == ("drawn", "Kieran, a tired farmer", "Ink and muted watercolour")
    assert dm.post("/pictures/use", data={**ref, "pick": "1/x.webp|1/y.webp"}, headers=HX).status_code == 409  # (only files askdnd drew)
    spending.set_limit(db, 0.01)
    r = dm.post("/pictures/draw", data={**ref, "words": "again"}, headers=HX)
    assert r.status_code == 409 and "monthly limit" in r.json()["detail"] and len(openai) == 1


def test_the_art_style_its_pictures_to_match_and_off(people, db, openai):
    """Manage › Settings › Art style (the DM's): its words, up to four of the campaign's own pictures sent to match, and
    Describe it switched off."""
    import_bundle(db, BUNDLE)
    dm, player = people["dm"], people["player"]
    k, w = entity(db, "Kieran"), entity(db, "Womford")
    for e in (k, w):
        dm.post("/pictures/upload", data={"for": f"entity:{e.id}"}, files={"file": ("p.png", png(), "image/png")}, headers=HX)
    ids = [p.id for p in db.scalars(select(EntityPicture).order_by(EntityPicture.id))]
    assert player.post("/c/main/manage/settings/art-style", data={"words": "x"}, headers=HX).status_code == 404
    page = dm.get("/c/main/manage/settings").text
    assert "Art style" in page and f'name="refs" value="{ids[0]}"' in page
    r = dm.post("/c/main/manage/settings/art-style", data={"words": "  Woodcut,  bold lines ", "refs": [str(ids[0]), "999999"]}, headers=HX)
    assert r.status_code == 204
    campaign = db.get(Campaign, k.campaign_id)
    db.refresh(campaign)
    assert campaign.art_style == {"words": "Woodcut, bold lines", "refs": [ids[0]], "off": False}
    # Brett, Nov 6: matched every time, everyone looked alike. Only when asked: ticked for a place, off for a person
    assert 'name="match" value="1" checked' in dm.get(f"/pictures?for=entity:{w.id}").text
    assert 'name="match" value="1" checked' not in dm.get(f"/pictures?for=entity:{k.id}").text
    dm.post("/pictures/draw", data={"for": f"entity:{k.id}", "words": "A half-elf sailor"}, headers=HX)
    assert openai[-1]["path"] == "generations" and not openai[-1]["files"] and "painting style" not in openai[-1]["fields"]["prompt"]
    dm.post("/pictures/draw", data={"for": f"entity:{w.id}", "words": "A village", "match": "1"}, headers=HX)
    call = openai[-1]
    assert call["path"] == "edits" and len(call["files"]) == 1 and "only for their painting style" in call["fields"]["prompt"]
    assert "A wide view of the place" in call["fields"]["prompt"] and call["fields"]["size"] == "1536x1024"  # (a place: wide)
    dm.post("/c/main/manage/settings/art-style", data={"words": "Woodcut", "off": "1"}, headers=HX)
    assert "switched off" in dm.get(f"/pictures?for=entity:{w.id}").text
    r = dm.post("/pictures/draw", data={"for": f"entity:{w.id}", "words": "A village"}, headers=HX)
    assert r.status_code == 409 and len(openai) == 2


def test_without_a_key_describe_it_says_so(people, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import_bundle(db, BUNDLE)
    k = entity(db, "Kieran")
    assert "isn&#39;t set up yet" in people["dm"].get(f"/pictures?for=entity:{k.id}").text
    assert pictures.PictureError  # (the draw route refuses with the same words)


def test_a_characters_d_and_d_beyond_portrait_can_be_a_picture_to_match(people, db, openai, monkeypatch):
    """Feedback 16 (Brett, Nov 5): the characters' D&D Beyond portraits are offered too. One picked is read from D&D
    Beyond's image server when something is drawn, and never kept; another site's address is never offered or read."""
    from app import characters
    from tests.table_setup import COLE

    import_bundle(db, {**BUNDLE, "entities": BUNDLE["entities"] + [{"kind": "pc", "name": "Cole", "character": {"ddb_id": "75423618"}}]})
    cole = db.scalar(select(characters.Character).where(characters.Character.name == "Cole"))
    face = "https://www.dndbeyond.com/avatars/1/2/cole.jpeg"
    characters.refresh(db, cole, fetch=lambda i: {**COLE, "decorations": {"avatarUrl": face}})
    read = []
    monkeypatch.setattr(drawing, "READ_PORTRAIT", lambda url: read.append(url) or png(64, 64))
    dm = people["dm"]
    page = dm.get("/c/main/manage/settings").text
    assert f'value="portrait:{cole.id}"' in page and f'src="{face}"' in page and "Cole, from D&amp;D Beyond" in page
    dm.post("/c/main/manage/settings/art-style", data={"words": "Oil", "refs": [f"portrait:{cole.id}", "portrait:999"]}, headers=HX)
    campaign = db.get(Campaign, cole.campaign_id)
    db.refresh(campaign)
    assert campaign.art_style["refs"] == [f"portrait:{cole.id}"]  # (not a character of this campaign: dropped)
    dm.post("/pictures/draw", data={"for": f"entity:{entity(db, 'Womford').id}", "words": "A village", "match": "1"}, headers=HX)
    assert read == [face] and len(openai[-1]["files"]) == 1 and openai[-1]["path"] == "edits"
    assert not db.scalars(select(EntityPicture).where(EntityPicture.character_id == cole.id)).all()  # (never kept)

    characters.refresh(db, cole, fetch=lambda i: {**COLE, "decorations": {"avatarUrl": "https://evil.example/x.jpg"}})
    assert "portrait:" not in dm.get("/c/main/manage/settings").text.split('id="art-style"')[1].split("</section>")[0]


def test_describe_it_goes_by_a_relatives_picture_and_one_named_with_at(people, db, openai):
    """Feedback 34 and 36 (Brett, Nov 7): Describe it offers a relative's picture (unticked) so family looks related, and
    an entry named with @ that has a picture (ticked); only the ticked ones go to OpenAI, each said for what it is, and
    never one the person may not see or another campaign's."""
    from app import relations
    from app.models import Status

    import_bundle(db, {**BUNDLE, "entities": BUNDLE["entities"] + [{"kind": "npc", "name": "Mira"}, {"kind": "npc", "name": "Sorrow"}]})
    dm = people["dm"]
    k, w, mira, sorrow = (entity(db, n) for n in ("Kieran", "Womford", "Mira", "Sorrow"))
    for e in (k, w, sorrow):
        dm.post("/pictures/upload", data={"for": f"entity:{e.id}"}, files={"file": ("p.png", png(), "image/png")}, headers=HX)
    relations.add(db, k, "parent_of", mira)  # (Mira's father Kieran has a picture: hers can look like him)
    relations.add(db, sorrow, "sibling_of", mira)
    sorrow.status = Status.DRAFT  # (a hidden entry is still the DM's to go by; a player never sees it offered)
    db.flush()
    win = dm.get(f"/pictures?for=entity:{mira.id}").text
    assert 'name="like" value="%d"' % k.id in win and "Parent" in win and 'name="like" value="%d" checked' % k.id not in win
    assert 'name="like" value="%d"' % sorrow.id in win
    # @Womford: its picture joins, ticked; a name without a picture, or the entry itself, doesn't
    row = dm.get(f"/pictures/ref?for=entity:{mira.id}&name=Womford")
    assert row.status_code == 200 and f'name="ref" value="{w.id}" checked' in row.text
    assert dm.get(f"/pictures/ref?for=entity:{mira.id}&name=Mira").status_code == 204
    assert dm.get(f"/pictures/ref?for=entity:{mira.id}&name=Nobody").status_code == 204
    dm.post("/pictures/draw", data={"for": f"entity:{mira.id}", "words": "Mira, a young sailor", "like": [str(k.id)], "ref": [str(w.id), "999999"]}, headers=HX)
    call = openai[-1]
    assert call["path"] == "edits" and len(call["files"]) == 2
    assert "Picture 1 shows Kieran, family of this subject" in call["fields"]["prompt"]
    assert "Picture 2 shows Womford as it looks in this campaign" in call["fields"]["prompt"] and "painting style" not in call["fields"]["prompt"]
    # Unticked, nothing is sent
    dm.post("/pictures/draw", data={"for": f"entity:{mira.id}", "words": "Mira"}, headers=HX)
    assert openai[-1]["path"] == "generations" and not openai[-1]["files"]


def test_a_player_draws_their_own_characters_picture_and_no_one_elses(player, dm, db, openai):
    """Brett, Nov 9: players draw pictures of their own characters (and already of their familiars); never of another
    player's character or anyone else in the World, which stay the DM's."""
    from app.models import Entity, EntityKind
    from tests.table_setup import BUNDLE as TABLE
    from tests.table_setup import char, owned_by

    import_bundle(db, TABLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    owned_by(db, cole, "player@example.com")
    owned_by(db, trah, "other@example.com")
    db.flush()
    mine = next(m.entity for m in cole.memberships if m.left_on is None)
    theirs = next(m.entity for m in trah.memberships if m.left_on is None)
    npc = Entity(campaign_id=mine.campaign_id, kind=EntityKind.NPC, name="Kieran", summary="Cole's father.")
    db.add(npc)
    db.flush()
    assert mine.kind == EntityKind.PC
    assert player.get(f"/pictures?for=entity:{mine.id}").status_code == 200
    r = player.post("/pictures/draw", data={"for": f"entity:{mine.id}", "words": "Cole, a wood elf druid"}, headers=HX)
    assert r.status_code == 200 and r.text.count('name="pick"') == 4 and len(openai) == 1
    for other in (theirs, npc):
        assert player.get(f"/pictures?for=entity:{other.id}").status_code in (403, 404)
        assert player.post("/pictures/draw", data={"for": f"entity:{other.id}", "words": "x"}, headers=HX).status_code in (403, 404)
    assert len(openai) == 1
    assert dm.get(f"/pictures?for=entity:{theirs.id}").status_code == 200  # (the DM's, as before)
    page = player.get(f"/c/main/campaign?open={mine.id}").text
    assert f"/pictures?for=entity:{mine.id}" in page
