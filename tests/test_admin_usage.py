"""Backstage › Usage (app/admin_usage.py): its windows, top-ups, the monthly limit and the list of calls, each from
its own button (issue 169: the least-tested page code after the review run Test the tests, Nov 25)."""

from datetime import date

import pytest
from sqlalchemy import select

from app import spending
from app.admin_usage import parse_amount
from app.importer import import_bundle
from app.models import Campaign, CreditTopUp, Entity, EntityKind, ExtractionRun, GameSession
from tests.table_setup import BUNDLE, plain_id


@pytest.mark.parametrize(("typed", "want"), [
    ("$20", 20.0), ("20.00", 20.0), ("$1,000.50", 1000.5), (" 20 ", 20.0), ("twenty", None), ("nan", None), ("", None),
], ids=plain_id)
def test_an_amount_is_read_the_way_people_type_it(typed, want):
    assert parse_amount(typed) == want


def test_the_windows_open_from_their_buttons(admin, db):
    limit = admin.get("/manage/usage/limit-window").text
    assert 'data-field="usage-limit"' in limit and 'action="/manage/usage/limit"' in limit
    topup = admin.get("/manage/usage/topup-window").text
    assert 'data-field="topup-amount"' in topup and 'name="added_on"' in topup and 'data-window-size="small"' in topup


def test_a_top_up_is_added_refused_when_it_isnt_an_amount_and_removed(admin, db):
    admin.post("/manage/usage/topups", data={"amount": "$25.50", "added_on": "2026-11-20", "note": " First "})
    t = db.scalar(select(CreditTopUp))
    assert t.amount_usd == 25.5 and t.added_on == date(2026, 11, 20) and t.note == "First"
    for bad in ("lots", "0", "20000"):
        admin.post("/manage/usage/topups", data={"amount": bad, "added_on": "2026-11-21"})
    assert len(list(db.scalars(select(CreditTopUp)))) == 1  # (each refused, said in a card)
    admin.post(f"/manage/usage/topups/{t.id}/delete")
    admin.post("/manage/usage/topups/999999/delete")  # (one already gone: nothing happens)
    assert db.scalar(select(CreditTopUp)) is None


def test_the_monthly_limit_is_set_refused_and_removed(admin, db):
    admin.post("/manage/usage/limit", data={"amount": "$30"})
    assert spending.limit(db) == 30.0
    admin.post("/manage/usage/limit", data={"amount": "loads"})
    assert spending.limit(db) == 30.0  # (refused: the limit stays)
    admin.post("/manage/usage/limit", data={"amount": ""})
    assert spending.limit(db) is None


def test_the_calls_list_names_a_session_an_entry_or_nothing(admin, db):
    import_bundle(db, BUNDLE)
    campaign = db.scalar(select(Campaign))
    s = GameSession(campaign_id=campaign.id, number=1, source="manual")
    e = Entity(campaign_id=campaign.id, name="The Mill", kind=EntityKind.PLACE)
    db.add_all([s, e])
    db.flush()
    for kw in ({"session_id": s.id}, {"entity_id": e.id}, {}):
        db.add(ExtractionRun(source="draft", model="claude-test", input_tokens=10, output_tokens=5, cost_usd=0.01, **kw))
    db.flush()
    page = admin.get("/manage/usage").text
    assert f"/manage/sessions/{s.id}" in page and f"/campaign?open={e.id}" in page


def test_a_player_never_opens_usage(player, db):
    for path in ("/manage/usage", "/manage/usage/limit-window", "/manage/usage/topup-window"):
        assert player.get(path, follow_redirects=False).status_code in (302, 303, 403)
