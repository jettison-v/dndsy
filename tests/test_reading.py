"""Every page, read by someone who mustn't (the outside review's C11, Nov 10: a sweep for reading, to match
tests/test_refusals.py's sweep for changing).

The routes come from the app itself, so a page is asked the day it's added. Each private thing is planted with a mark of
its own, and every page is asked, at its real address about rows that exist, by each person who mustn't see it:

- signed out: every page refuses (or sends to sign-in), but for a short list of public ones, and no mark shows;
- the DM of another campaign: nothing of this campaign's (a role is per campaign);
- a player: no hidden entry (status draft), no DM scene note, no hidden token (CLAUDE.md › Hidden is as if it didn't
  exist; the scene notes are the DM's alone);
- the DM: no player's character note (CLAUDE.md › Visibility: character notes are visible to players but NOT the DM).
"""

import pytest
from fastapi.testclient import TestClient

from app import vtt
from app.db import get_db
from app.main import app
from app.models import Campaign, Entity, EntityKind, Place, PlayerNote, ScenePin, Status, Token
from tests.table_setup import address, char, sign_in, two_campaigns

pytestmark = pytest.mark.usefixtures("no_network")

NOTE = "Notemark Quill"  # Trah's player's note
DRAFT = "Veiled Draftmark"  # a hidden World entry
SCENE = "Scenemark Ledger"  # the DM's scene note
TOKEN = "Tokenmark Lurker"  # a hidden creature on the map
MAIN = "Mainmark Harbor"  # anything of Main's, for the DM of another campaign

# Pages anyone may open signed out: signing in, the health check, Help (askdnd's own words), and what every page asks
# for whoever's there, which answers someone signed out with nothing (a count of 0, no cards, no heals)
PUBLIC = {"/login", "/health", "/auth/google", "/auth/callback", "/dev/login", "/rules/terms.json", "/email/stop",
          "/admin/notes/callback", "/bridge/health", "/help",
          "/heals/waiting", "/manage/counts", "/your-notes/news", "/your-notes/seen"}


def reading_routes() -> list[tuple[str, dict]]:
    return sorted((p, ops["get"]) for p, ops in app.openapi()["paths"].items() if "get" in ops)


@pytest.fixture
def table(db):
    ids = two_campaigns(db)
    trah = char(db, "Trah")
    main = db.get(Campaign, trah.campaign_id)
    main.vtt_pieces = [f.key for f in vtt.FEATURES] + [vtt.LABS]  # (every feature on, askdnd's table too: every page has its say)
    note = PlayerNote(character_id=trah.id, kind="general", campaign_id=main.id, title=NOTE, data={"text": NOTE})
    draft = Entity(campaign_id=main.id, kind=EntityKind.NPC, name=DRAFT, summary=f"{DRAFT} rules the harbor.", status=Status.DRAFT)
    place = Place(campaign_id=main.id, name=f"{MAIN} Docks")
    db.add_all([note, draft, place])
    main.name = MAIN
    db.flush()
    pin = ScenePin(campaign_id=main.id, place_id=place.id, name="The docks", notes={"intro": SCENE})
    token = Token(campaign_id=main.id, place_id=place.id, kind="monster", monster={"name": TOKEN, "source": "SRD"},
                  name=TOKEN, hidden=True)
    db.add_all([pin, token])
    db.flush()
    yield ids | {"note_id": note.id, "place_id": place.id, "scene_id": pin.id, "token_id": token.id}
    app.dependency_overrides.clear()


def read_all(c: TestClient, ids: dict) -> list[tuple[str, int, str]]:
    """Every page, once: (address, status, body)."""
    out = []
    for path, op in reading_routes():
        r = c.get(address(path, op, ids), follow_redirects=False)
        out.append((path, r.status_code, r.text))
    return out


def shows(pages, *marks) -> list[tuple[str, str]]:
    return [(path, m) for path, _, body in pages for m in marks if m in body]


def test_signed_out_every_page_refuses(db, table):
    """A standing rule (CLAUDE.md › Stack: Google sign-in limited to an allowlist): signed out, every page but the
    public ones refuses or sends to sign-in, and none shows anything of the table's."""
    app.dependency_overrides[get_db] = lambda: db
    pages = read_all(TestClient(app), table)
    assert len(pages) > 120  # (every page was asked)
    opened = [(p, s) for p, s, _ in pages if p not in PUBLIC and s < 300]
    assert not opened, opened
    assert not shows(pages, NOTE, DRAFT, SCENE, TOKEN, MAIN)  # (not the characters' names: Help's examples use them)


def test_another_campaigns_dm_reads_nothing_here(db, table, monkeypatch):
    """A role is per campaign (docs/plans/2026-10-21-data-organization.md): the DM of Elsewhere, asking for every page
    of Main's, sees none of it."""
    pages = read_all(sign_in(monkeypatch, db, "elsewhere@example.com"), table)
    assert not shows(pages, NOTE, DRAFT, SCENE, TOKEN, MAIN)


def test_a_player_never_reads_a_hidden_entry_a_scene_note_or_a_hidden_token(db, table, monkeypatch):
    """A standing rule (CLAUDE.md › Hidden is as if it didn't exist; the DM's scene notes are hers alone, Nov 6;
    hidden tokens reach only the DM's page): asked as Cole's player, about Trah and the table, no page shows any."""
    pages = read_all(sign_in(monkeypatch, db, "player@example.com"), table)
    assert not shows(pages, DRAFT, SCENE, TOKEN)
    assert shows(pages, NOTE)  # (a player reads another's character notes: the sweep reached them)


def test_the_dm_never_reads_a_players_character_notes(db, table, monkeypatch):
    """A standing rule (CLAUDE.md › Visibility, Brett 2026-10-17): character notes are visible to players but not the
    DM. Asked as Main's DM, no page shows Trah's note."""
    pages = read_all(sign_in(monkeypatch, db, "dm@example.com"), table)
    assert not shows(pages, NOTE)
    assert shows(pages, SCENE) and shows(pages, DRAFT) and shows(pages, TOKEN) and shows(pages, MAIN)  # (hers to see: the sweep reached them)
