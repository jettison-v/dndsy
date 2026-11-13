"""Every route that changes something, asked by someone who mustn't (Brett, 2026-11-05: test the negative cases too).

The routes come from the app itself (170 of them on Nov 5), so a new route is tried the day it's added, whether or not
anyone wrote a test for it. Each is asked with a body that gets past its own form checks (built from the route's declared
fields), at its real address (a campaign page under /c/<campaign>), about rows that exist. Whatever it answers, the
database must be exactly as it was: a fingerprint of every table before and after each request.

The people who mustn't: someone signed out; a player, about another player's character and the DM's pages; and the
DM of another campaign, about this one's rows (a role is per campaign, so a check that asks only "is a DM?" lets them in).
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import campaign_paths
from app.db import Base, get_db
from app.importer import import_bundle
from app.main import app
from app.models import Campaign, GameSession, GlossaryTerm
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by, sign_in

pytestmark = pytest.mark.usefixtures("no_network")

# Routes anyone may call, each checking something of its own instead of who's signed in (a key, a signature, nothing kept)
OPEN = {
    ("POST", "/errors/page"),  # a page's JavaScript error, sent on to Sentry; nothing is kept
    ("POST", "/logout"),  # signing out
}


def changing_routes() -> list[tuple[str, str, dict]]:
    """(method, path, operation) for every route that changes something, from the app's own list."""
    return sorted((m.upper(), p, op) for p, ops in app.openapi()["paths"].items() for m, op in ops.items() if m in ("post", "put", "delete", "patch"))


def body_for(op: dict) -> dict:
    """A form that passes the route's declared fields: every field given (an id where it wants a number)."""
    schemas = app.openapi()["components"]["schemas"]
    content = (op.get("requestBody") or {}).get("content") or {}
    ref = next((c["schema"].get("$ref") for c in content.values() if "$ref" in c.get("schema", {})), None)
    props = schemas[ref.split("/")[-1]].get("properties", {}) if ref else {}
    out = {}
    for name, p in props.items():
        kind = p.get("type") or next((x.get("type") for x in p.get("anyOf", []) if x.get("type") != "null"), "string")
        out[name] = "1" if kind in ("integer", "number") else "true" if kind == "boolean" else "x"
    return out


def address(path: str, op: dict, ids: dict) -> str:
    url = re.sub(r"\{(\w+)\}", lambda m: str(ids.get(m.group(1), 1)), path)
    if campaign_paths.in_campaign(path):
        url = f"/c/main{url}"
    query = [f"{p['name']}=1" for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")]
    return url + ("?" + "&".join(query) if query else "")


# What any page visit keeps about the person visiting: the campaign they're in now (app/campaign_paths.py) and when
# they were last seen. Never a change to anything of anyone else's.
BOOKKEEPING = {"users": ("current_campaign_id", "last_seen_at", "updated_at")}
# Whole tables of bookkeeping: what was done, counted for Admin › Features (app/usage.py), not a change to anything
BOOKKEEPING_TABLES = {"usage_events"}
# The asker's own settings, which every signed-in person may change for themself
OWN = {("POST", "/dice")}  # (Your dice)


def fingerprint(db) -> dict[str, str]:
    db.flush()
    out = {}
    for t in Base.metadata.sorted_tables:
        if t.name in BOOKKEEPING_TABLES:
            continue
        row = "to_jsonb(x)" + "".join(f" - '{c}'" for c in BOOKKEEPING.get(t.name, ()))
        out[t.name] = db.execute(text(f'SELECT md5(coalesce(string_agg(({row})::text, \'|\' ORDER BY ({row})::text), \'\')) FROM "{t.name}" x')).scalar()  # noqa: S608
    return out


def ask_all(c: TestClient, db, ids: dict, skip=frozenset()) -> tuple[list, dict]:
    """Asks every changing route once. ([(method, path, status, tables changed)], {status: how many})."""
    changed, statuses = [], {}
    for method, path, op in changing_routes():
        if (method, path) in OPEN | skip:
            continue
        before = fingerprint(db)
        files = {"file": ("x.png", b"\x89PNG\r\n", "image/png")} if "multipart/form-data" in (op.get("requestBody") or {}).get("content", {}) else None
        r = c.request(method, address(path, op, ids), data=body_for(op), files=files, follow_redirects=False)
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
        diff = [k for k, v in fingerprint(db).items() if before[k] != v]
        if diff:
            changed.append((method, path, r.status_code, diff))
    return changed, statuses


@pytest.fixture
def table(db, monkeypatch):
    """Main with Cole (player@'s) and Trah (other@'s), a session and a glossary term; and Elsewhere, whose DM is
    elsewhere@ (a DM, but not of Main)."""
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
    yield {"character_id": trah.id, "entity_id": trah.entity.id, "term_id": term.id, "session_id": session.id}
    app.dependency_overrides.clear()


def test_signed_out_nothing_changes(db, table):
    """A standing rule (CLAUDE.md › Stack: Google sign-in limited to an allowlist): signed out, no route changes anything."""
    app.dependency_overrides[get_db] = lambda: db
    changed, statuses = ask_all(TestClient(app), db, table)
    assert not changed, changed
    assert sum(statuses.values()) > 150  # (every route was asked)


def test_a_player_changes_nothing_of_another_players_character_nor_the_dms_pages(db, table, monkeypatch):
    """A standing rule (CLAUDE.md › Privacy, and Manage is the DM's): a player changes only their own character and
    what's theirs. Asked about Trah (other@'s) and every Manage page, as Cole's player."""
    c = sign_in(monkeypatch, db, "player@example.com")
    for_others = lambda path: path.startswith(("/characters/{character_id}", "/manage"))
    changed, _ = ask_all(c, db, table, skip=frozenset((m, p) for m, p, _ in changing_routes() if not for_others(p)))
    assert not changed, changed


def test_another_campaigns_dm_changes_nothing_here(db, table, monkeypatch):
    """A role is per campaign (docs/plans/2026-10-21-data-organization.md): the DM of Elsewhere, asking about Main's
    character, entry, session and glossary term, changes nothing of Main's."""
    c = sign_in(monkeypatch, db, "elsewhere@example.com")
    changed, _ = ask_all(c, db, table, skip=frozenset(OWN))
    assert not changed, changed
