"""One address per page (Brett, 2026-10-23): every link askdnd makes goes straight to a page, never through a
redirect, for an admin, the DM and a player. The only addresses kept for outside callers are the home page (/),
Google's two return addresses and the Processor's upload; old addresses are gone (Not found)."""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, characters, config, ddb
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import Character
from tests.roles import set_role
from tests.test_entities import BUNDLE, published_events

COLE = json.loads((Path(__file__).parent / "fixtures" / "ddb" / "cole.json").read_text())["data"]
LINKS = re.compile(r'(?:href|data-panel-url|data-modal-url|hx-get)="([^"]+)"')
SKIP = ("/static/", "/logout", "/auth/", "/dev/", "/view-as", "mailto:", "javascript:", "#", "https://", "http://")
NOT_PAGES = ("/c/main/manage/sessions/doc/images/",)  # pictures, not pages


def client(monkeypatch, db, email):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,dm@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0].title()}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


@pytest.fixture
def world(monkeypatch, db):
    monkeypatch.setattr(ddb, "fetch_character_json", lambda ddb_id: COLE)
    import_bundle(db, {**BUNDLE, "entities": BUNDLE["entities"] + [
        {"kind": "pc", "name": "Cole", "character": {"player_name": "Pat", "ddb_id": "75423618"}},
        {"kind": "quest", "name": "Reach the library", "quest_open": True}]})
    published_events(db)
    characters.refresh(db, db.scalar(select(Character).where(Character.name == "Cole")), fetch=lambda i: COLE)
    set_role(db, "dm@example.com", "dm", name="Dee")
    player = set_role(db, "player@example.com", "player", name="Pat")
    db.scalar(select(Character).where(Character.name == "Cole")).owner_id = player.id
    db.flush()
    yield db
    app.dependency_overrides.clear()


def crawl(c, start=("/",), limit=400) -> dict[str, str]:
    """Every internal link reachable from `start`, opened without following redirects: {link: problem}."""
    seen, queue, problems = set(), list(start), {}
    while queue and len(seen) < limit:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        fragment = url.endswith("#hx")
        path = url.removesuffix("#hx")
        r = c.get(path, follow_redirects=False, headers={"HX-Request": "true"} if fragment else {})
        if url not in start and r.status_code in (301, 302, 303, 307, 308):
            problems[path] = f"redirects to {r.headers.get('location')}"
            continue
        if r.status_code >= 400 and r.status_code != 403:
            problems[path] = f"{r.status_code}"
            continue
        if r.status_code in (301, 302, 303, 307, 308):  # the home page: follow it once
            queue.append(urlsplit(r.headers["location"]).path or "/")
            continue
        for kind, link in ((m.group(0).split("=")[0], m.group(1)) for m in LINKS.finditer(r.text)):
            link = link.replace("&amp;", "&")
            if link.startswith(SKIP) or "{{" in link or link.startswith(NOT_PAGES):
                continue
            full = urljoin(path, link).split("#")[0]
            if not full.startswith("/") or full.startswith(NOT_PAGES):
                continue
            queue.append(full + ("#hx" if kind != "href" else ""))
    return problems


@pytest.mark.parametrize("email", ["admin@example.com", "dm@example.com", "player@example.com"])
def test_every_link_goes_straight_to_its_page(world, monkeypatch, email):
    c = client(monkeypatch, world, email)
    problems = crawl(c)
    assert not problems, f"Links that don't go straight to a page, as {email}: " + json.dumps(problems, indent=1)


def test_old_addresses_are_gone(world, monkeypatch):
    c = client(monkeypatch, world, "admin@example.com")
    for old in ("/faq", "/about", "/sessions", "/map", "/battle", "/character", "/characters", "/suggestions",
                "/admin/sessions", "/admin/people", "/admin/usage", "/admin/history", "/campaign", "/manage/inbox"):
        r = c.get(old, follow_redirects=False)
        assert r.status_code == 404, f"{old} still answers {r.status_code}"
    assert "Not found" in c.get("/faq").text and 'href="/"' in c.get("/faq").text
    # Kept for outside callers: the home page, Google's return addresses, the Processor's upload
    assert c.get("/", follow_redirects=False).status_code in (302, 303, 307)
    assert c.get("/auth/callback", follow_redirects=False).status_code != 404
    assert c.get("/admin/notes/callback", follow_redirects=False).status_code != 404
    assert c.post("/api/transcripts", follow_redirects=False).status_code != 404  # the Processor's upload
