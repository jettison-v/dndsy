"""The Map tab and "Show on map" links to AideDD's Sword Coast atlas (app/atlas.py)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import atlas
from app.importer import import_bundle
from app.main import app
from app.models import Entity, Status
from tests.test_suggestions import client_for

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main"},
    "entities": [
        {"kind": "place", "name": "Star Mounts", "summary": "Peaks in the High Forest."},
        {"kind": "place", "name": "The City of Splendors", "summary": "A big city.", "aliases": ["Waterdeep"]},
        {"kind": "place", "name": "Belliard House", "summary": "A townhouse."},
        {"kind": "npc", "name": "Neverwinter", "summary": "Someone named after a city."},
    ],
}


@pytest.fixture
def player(monkeypatch, db):
    import_bundle(db, BUNDLE)
    for e in db.scalars(select(Entity)):
        e.status = Status.PUBLISHED
    db.flush()
    yield client_for(monkeypatch, db, "mark@example.com")
    app.dependency_overrides.clear()


def page(db, client, name) -> str:
    e = db.scalar(select(Entity).where(Entity.name == name))
    return client.get(f"/campaign/{e.id}/peek").text


def test_markers_match_names_ignoring_case_and_build_links():
    assert atlas.marker_for(["Nowhere", "star mounts"]) == "Star Mounts"
    assert atlas.marker_for(["Nowhere"]) is None
    assert atlas.atlas_url() == "https://www.aidedd.org/atlas/sword-coast"
    assert atlas.atlas_url("Star Mounts") == "https://www.aidedd.org/atlas/sword-coast@Star_Mounts"


def test_places_on_the_map_link_to_it_by_name_or_other_name(player, db):
    assert "/c/main/campaign?tab=map&amp;at=Star%20Mounts" in page(db, player, "Star Mounts")
    assert "/c/main/campaign?tab=map&amp;at=Waterdeep" in page(db, player, "The City of Splendors")
    assert "Show on map" not in page(db, player, "Belliard House")
    assert "Show on map" not in page(db, player, "Neverwinter")  # only places


def test_map_is_a_campaign_tab_that_centers_on_real_markers_only(player):
    r = player.get("/c/main/campaign?tab=map&at=Star%20Mounts")
    assert r.status_code == 200 and 'src="https://www.aidedd.org/atlas/sword-coast@Star_Mounts"' in r.text
    assert 'data-tab="t-map"' in r.text and "Mike Schley" in r.text
    r = player.get("/c/main/campaign?tab=map&at=https://evil.example")
    assert 'src="https://www.aidedd.org/atlas/sword-coast"' in r.text
    # On another tab the frame waits until Map is opened
    assert 'data-src="https://www.aidedd.org/atlas/sword-coast"' in player.get("/c/main/campaign").text
    # The old Map address opens the tab, still centered
    r = player.get("/map?at=Star%20Mounts", follow_redirects=False)
    r = player.get(r.headers["location"], follow_redirects=False)
    assert r.headers["location"] == "/c/main/campaign?tab=map&at=Star%20Mounts"
    assert player.get("/c/main/map", follow_redirects=False).headers["location"] == "/c/main/campaign?tab=map"
    assert TestClient(app).get("/map", follow_redirects=False).headers["location"] == "/login"


def test_places_in_the_campaign_reader_link_to_the_map(player, db):
    mounts = db.scalar(select(Entity).where(Entity.name == "Star Mounts"))
    assert 'href="/c/main/campaign?tab=map&amp;at=Star%20Mounts"' in player.get(f"/campaign?open={mounts.id}").text
