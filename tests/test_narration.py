"""Listen to the recap (a Labs feature, app/narration.py; Brett, Nov 6): the published recap read aloud, made once and
kept, counted on Usage, over the place each paragraph is in with the people it names in front."""

import pytest
from sqlalchemy import select

from app import narration
from app.importer import import_bundle
from app.models import Campaign, Entity, EntityAlias, EntityKind, ExtractionRun, GameSession, Recap, Status
from tests.table_setup import BUNDLE

pytestmark = pytest.mark.usefixtures("file_store")

BODY = ("The party reached **Star Mount** at dusk, and Cole led them up the old path past the captain's camp.\n\n"
        "Trah lit the way with a flicker of fire; nobody spoke of the bard.\n\n"
        "At the top, an empty shrine waited.")


@pytest.fixture
def told(db, monkeypatch):
    """Main with a published recap, Labs and Listen switched on, a place (Star Mount) and a captain known only as "the
    captain" too, and OpenAI stood in for (counting each call)."""
    import_bundle(db, BUNDLE)
    campaign = db.scalar(select(Campaign))
    campaign.vtt_pieces = ["labs", "recap_listen"]
    mount = Entity(campaign_id=campaign.id, kind=EntityKind.PLACE, name="Star Mount", status=Status.PUBLISHED, summary="", summary_by="")
    captain = Entity(campaign_id=campaign.id, kind=EntityKind.NPC, name="Captain Captain", status=Status.PUBLISHED, summary="", summary_by="")
    captain.aliases.append(EntityAlias(alias="the captain"))
    db.add_all([mount, captain])
    s = GameSession(campaign_id=campaign.id, number=19, title="Journey to Star Mount", source="notes")
    db.add(s)
    db.flush()
    db.add(Recap(session_id=s.id, version=1, body=BODY, author="ai", status=Status.PUBLISHED))
    db.flush()
    calls = []
    monkeypatch.setattr(narration, "FETCH", lambda text: calls.append(text) or b"ID3" + bytes([len(calls)]) * 64)
    monkeypatch.setattr(narration.pictures, "urls", lambda db, ids: {i: {"full": f"/pic/{i}", "pos": "50% 20%"} for i in ids})
    return s, calls


def ids(db, *names):
    return [f"/pic/{db.scalar(select(Entity).where(Entity.name == n)).id}" for n in names]


def test_listen_reads_the_recap_once_and_keeps_it(player, db, told):
    s, calls = told
    assert f'data-listen="/c/main/sessions/{s.id}"' in player.get("/c/main/").text  # (▶ Listen on Previously on…)
    tale = player.get(f"/c/main/sessions/{s.id}/tale").json()
    assert tale["audio"] == "" and tale["title"] == "Journey to Star Mount" and tale["intro"] == "Previously, on Main…"
    assert not tale["can_redo"]  # (Read it again is an admin's)
    words = [x["text"] for x in tale["slides"]]
    assert words[1].startswith("The party reached Star Mount") and "**" not in words[1]  # (plain words, read and shown)
    first = player.post(f"/c/main/sessions/{s.id}/narrate").json()
    assert first["audio"].startswith(f"/c/main/sessions/{s.id}/narration?v=") and len(calls) == 1
    assert calls[0].startswith("Previously, on Main…") and "Star Mount" in calls[0]
    run = db.scalar(select(ExtractionRun).where(ExtractionRun.source == "narration"))
    assert run.status == "done" and run.cost_usd > 0  # (counted on Manage › Usage, under the monthly limit)
    assert player.post(f"/c/main/sessions/{s.id}/narrate").json() == first and len(calls) == 1  # (kept: made once)
    got = player.get(f"/c/main/sessions/{s.id}/narration")
    assert got.status_code == 200 and got.headers["content-type"] == "audio/mpeg" and got.content.startswith(b"ID3")
    assert "Drafting" not in player.get("/c/main/").text


def test_the_place_is_the_backdrop_and_the_people_it_names_are_in_front(player, db, told):
    """Brett, Nov 6: the place behind, the people in front; a description ("the captain") names no one, so Captain
    Captain isn't on every captain's paragraph; a paragraph naming no one shows just its place."""
    s, _ = told
    slides = player.get(f"/c/main/sessions/{s.id}/tale").json()["slides"]
    mount = ids(db, "Star Mount")[0]
    assert [x["place"]["src"] for x in slides] == [mount] * 4  # (named in the first paragraph, it stays the backdrop)
    assert [p["src"] for p in slides[1]["people"]] == ids(db, "Cole") and slides[1]["people"][0]["name"] == "Cole"
    assert [p["src"] for p in slides[2]["people"]] == ids(db, "Trah")
    assert slides[3]["people"] == [] and slides[0]["intro"] and slides[0]["people"] == []


def test_an_admin_has_it_read_again(admin, player, db, told):
    s, calls = told
    player.post(f"/c/main/sessions/{s.id}/narrate")
    assert player.post(f"/c/main/sessions/{s.id}/narrate?again=1").status_code == 403 and len(calls) == 1
    assert admin.get(f"/c/main/sessions/{s.id}/tale").json()["can_redo"]
    before = db.scalar(select(Recap)).narration_key
    again = admin.post(f"/c/main/sessions/{s.id}/narrate?again=1").json()
    db.expire_all()
    assert len(calls) == 2 and db.scalar(select(Recap)).narration_key != before and again["audio"].endswith(db.scalar(select(Recap)).narration_key.rsplit("/", 1)[-1][:16])


def test_listen_is_a_labs_feature(player, db, told):
    s, calls = told
    db.scalar(select(Campaign)).vtt_pieces = []
    db.flush()
    assert "data-listen" not in player.get("/c/main/").text
    assert player.get(f"/c/main/sessions/{s.id}/tale").status_code == 404
    assert player.post(f"/c/main/sessions/{s.id}/narrate").status_code == 404 and calls == []


def test_the_spending_limit_stops_it(player, db, told, monkeypatch):
    s, calls = told
    monkeypatch.setattr(narration.spending, "reached", lambda db: "This month's limit is reached.")
    r = player.post(f"/c/main/sessions/{s.id}/narrate")
    assert r.status_code == 503 and "limit" in r.json()["error"] and calls == []


def test_a_long_recap_is_read_in_parts_openai_takes_in_order():
    lines = ["x" * 3000, "y" * 3000, "z. " * 1600]
    parts = narration._parts(lines)
    assert all(len(p) <= narration.CHUNK for p in parts) and "".join(parts).replace("\n", "").replace(" ", "") == "".join(lines).replace(" ", "")


def test_a_description_is_not_a_name():
    from app import mentions

    assert mentions.proper("Lillippi") and mentions.proper("Pirate Captain") and mentions.proper("the Lich Queen")
    assert not mentions.proper("the captain") and not mentions.proper("a bard") and not mentions.proper("Al")
    find = mentions.finder([("Captain Captain", 1), ("the captain", 1), ("Captain Trager Grill", 2), ("Trah", 3)])
    assert find("Trah met Captain Trager Grill, then the captain.") == [3, 2]  # (the longer name claims its words)
