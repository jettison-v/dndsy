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
    assert r.status_code == 204
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
    dm.post("/pictures/draw", data={"for": f"entity:{w.id}", "words": "A village"}, headers=HX)
    call = openai[-1]
    assert call["path"] == "edits" and len(call["files"]) == 1 and "Match the style" in call["fields"]["prompt"]
    assert "A wide view of the place" in call["fields"]["prompt"] and call["fields"]["size"] == "1536x1024"  # (a place: wide)
    dm.post("/c/main/manage/settings/art-style", data={"words": "Woodcut", "off": "1"}, headers=HX)
    assert "switched off" in dm.get(f"/pictures?for=entity:{w.id}").text
    r = dm.post("/pictures/draw", data={"for": f"entity:{w.id}", "words": "A village"}, headers=HX)
    assert r.status_code == 409 and len(openai) == 1


def test_without_a_key_describe_it_says_so(people, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import_bundle(db, BUNDLE)
    k = entity(db, "Kieran")
    assert "isn&#39;t set up yet" in people["dm"].get(f"/pictures?for=entity:{k.id}").text
    assert pictures.PictureError  # (the draw route refuses with the same words)
