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


def plain_id(x) -> str:
    """A parametrized test's id in plain letters, digits and dashes: a name with an apostrophe, a colon or brackets
    ("Raulothim's Psychic Lance", "Eldritch Cannon: Flamethrower") can't be handed back to pytest on its command line
    (mutation testing does, foundation F8). Use it for every ids= built from names."""
    import re

    return re.sub(r"[^A-Za-z0-9]+", "-", x if isinstance(x, str) else str(x.get("name") if isinstance(x, dict) else x)).strip("-")


def made_up(*classes, features=(), attacks=(), pb=3, mods=None) -> dict:
    """A minimal sheet: classes as (name, level, subclass) tuples."""
    mods = mods or {"Str": 3, "Dex": 3, "Con": 2, "Int": 1, "Wis": 2, "Cha": 0}
    return {"classes": [{"name": n, "level": lv, "subclass": sub} for n, lv, sub in classes],
            "features": [{"name": f, "source": src} for f, src in features], "actions": [],
            "abilities": [{"short": k, "modifier": v} for k, v in mods.items()], "proficiency_bonus": pb,
            "attacks": list(attacks)}


def two_campaigns(db) -> dict:
    """Main with Cole (player@'s) and Trah (other@'s), a session and a glossary term, dm@ its DM; and Elsewhere, whose
    DM is elsewhere@ (a DM, but not of Main). The ids of Main's rows, by the names routes give them (tests/test_refusals.py
    asks every change of them, tests/test_reading.py every page)."""
    from app.importer import import_bundle
    from app.models import GameSession, GlossaryTerm
    from tests.roles import set_role

    import_bundle(db, {**BUNDLE, "sessions": [{"number": 1}]})
    cole, trah = char(db, "Cole"), char(db, "Trah")
    owned_by(db, cole, "player@example.com")
    owned_by(db, trah, "other@example.com")
    main = db.get(Campaign, cole.campaign_id)
    term = GlossaryTerm(campaign_id=main.id, term="Womford", description="A town.", misheard_as=[])
    db.add(term)
    elsewhere = Campaign(slug="elsewhere", name="Elsewhere")
    db.add(elsewhere)
    db.flush()
    set_role(db, "dm@example.com", "dm", "Dee", main)
    set_role(db, "elsewhere@example.com", "dm", "Elle", elsewhere)
    session = db.query(GameSession).filter_by(campaign_id=main.id).first()
    db.flush()
    return {"character_id": trah.id, "entity_id": trah.entity.id, "term_id": term.id, "session_id": session.id}


def address(path: str, op: dict, ids: dict) -> str:
    """A route's real address: its {ids} filled from `ids` (1 for one not given), under /c/main when it's a campaign's
    page, with its required query parameters."""
    import re

    from app import campaign_paths

    url = re.sub(r"\{(\w+)\}", lambda m: str(ids.get(m.group(1), 1)), path)
    if campaign_paths.in_campaign(path):
        url = f"/c/main{url}"
    query = [f"{p['name']}=1" for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")]
    return url + ("?" + "&".join(query) if query else "")
