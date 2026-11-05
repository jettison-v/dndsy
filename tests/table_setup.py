"""Shared test setup: the table's characters (Cole, Trah and Big C, from tests/fixtures/ddb), a fake D&D Beyond
(D&D Beyond is never called), and a client signed in as admin, DM or player. The fixtures that use it (admin, dm,
player, no_network) are in tests/conftest.py; a file that refreshes characters turns no_network on with
`pytestmark = pytest.mark.usefixtures("no_network")`."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config, ddb
from app.config import parse_allowlist
from app.db import get_db
from app.main import app
from app.models import Campaign, Character

COLE = json.loads((Path(__file__).parent / "fixtures" / "ddb" / "cole.json").read_text())["data"]

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main", "dm_name": "Mary"},
    "entities": [
        {"kind": "pc", "name": "Cole", "character": {"player_name": "Brett", "ddb_id": "75423618"}},
        {"kind": "pc", "name": "Trah", "character": {"player_name": "Mark", "ddb_id": "135831636"}},
        {"kind": "pc", "name": "Big C", "character": {"player_name": "Jay"}},
    ],
}


def fake_fetch(ddb_id):
    if ddb_id == "75423618":
        return {**COLE, "notes": {"backstory": "Raised by wolves near Womford.", "allies": "PRIVATE ALLY NOTE"},
                "traits": {"personalityTraits": "Slow to trust.", "ideals": "Charity.", "bonds": "", "flaws": "Greed.", "appearance": None}}
    raise ddb.DdbError("D&D Beyond says this character is private.")


def down(ddb_id):
    raise ddb.DdbError("Couldn't reach D&D Beyond. Try again later.")


def char(db, name) -> Character:
    return next(c for c in db.scalars(select(Character)) if c.name == name)


def sign_in(monkeypatch, db, email) -> TestClient:
    """A client signed in as `email` (admin@, dm@ or player@example.com), the app reading the test's database."""
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,dm@example.com,player@example.com,other@example.com,elsewhere@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0]}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


def owned_by(db, character, email, **kw):
    from app.models import User

    u = db.scalar(select(User).where(User.email == email)) or User(email=email, name=email)
    if kw.pop("is_dm", False):  # the DM of the character's campaign (roles are per campaign)
        from tests.roles import set_role

        db.add(u)
        db.flush()
        set_role(db, email, "dm", u.name, db.get(Campaign, character.campaign_id))
    for k, v in kw.items():
        setattr(u, k, v)
    db.add(u)
    db.flush()
    character.owner_id = u.id
    db.flush()
    return u


def card_on(page: str):
    """The corner card a page opens with (base.html data-toast; web.notice): its text, or {"text", "kind"}."""
    import html
    import re

    m = re.search(r"data-toast='([^']*)'", page)
    return json.loads(html.unescape(m.group(1))) if m else None
