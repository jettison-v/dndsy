"""Which features get used (app/usage.py; Brett chose A and A, Nov 9, docs/mockups/feature-use/): every action route is
counted as a feature or is askdnd's own bookkeeping; a use is tagged with the page it was done on; the table's uses
count, not admins', test accounts' or a test campaign's."""

import time

from sqlalchemy import select

from app import usage
from app.main import app
from app.models import Campaign, UsageEvent


def test_every_action_route_is_a_feature_or_bookkeeping():
    """A new route is counted the day it's added: give it a feature in usage.FEATURES, or list it in IGNORED."""
    paths = app.openapi()["paths"]
    missing = [p for p, ops in paths.items() if any(m in ("post", "put", "patch", "delete") for m in ops) and usage.feature_of(p) is None]
    assert missing == [], missing
    assert usage.feature_of("/rolls") == "Rolls" and usage.feature_of("/characters/{character_id}/cast") == "Cast"
    assert usage.feature_of("/bridge/hello") == "" and usage.feature_of("/live/sync") == ""


def test_the_page_comes_from_the_address():
    assert usage.page_of("https://askdnd.ai/characters/3/battle?creature=9") == "Battle"
    assert usage.page_of("https://askdnd.ai/characters/3") == "Sheet" and usage.page_of("https://askdnd.ai/characters/3/plan") == "Plan"
    assert usage.page_of("https://askdnd.ai/c/main/table") == "askdnd's table" and usage.page_of("https://askdnd.ai/c/main/") == "Campaign"
    assert usage.page_of("https://askdnd.ai/party") == "Party" and usage.page_of("") == ""


def _events(db, n, seconds=5):
    for _ in range(seconds * 10):
        db.expire_all()
        rows = list(db.scalars(select(UsageEvent).order_by(UsageEvent.id)))
        if len(rows) >= n:
            return rows
        time.sleep(0.1)
    return list(db.scalars(select(UsageEvent)))


def test_a_players_roll_is_counted_with_its_page_and_an_admins_is_not(player, admin, db, sheet):
    from tests.table_setup import char

    cole = char(db, "Cole")
    before = len(_events(db, 0, 0))
    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Stealth check", "mod": "+2"},
                    headers={"referer": f"https://askdnd.ai/characters/{cole.id}/battle"})
    assert r.status_code == 200
    rows = _events(db, before + 1)
    e = rows[-1]
    assert (e.feature, e.page, e.campaign_id) == ("Rolls: checks", "Battle", cole.campaign_id)
    player.post("/rolls", data={"character": cole.id, "kind": "attack", "label": "Shortsword", "mod": "+5", "via": "card"},
                headers={"referer": f"https://askdnd.ai/characters/{cole.id}/battle"})
    assert _events(db, before + 2)[-1].feature == "Roll card: attacks"
    admin.post("/dice", data={"set": "classic"})
    rows = _events(db, before + 3)
    admin_ids = {x.user_id for x in rows if x.feature == "Your dice"}
    counted = usage.counted(db, cole.campaign_id)
    assert all(x.user_id not in admin_ids for x in counted) and any(x.feature == "Rolls: checks" for x in counted)
    db.get(Campaign, cole.campaign_id).is_test = True  # (a test campaign's uses don't count either)
    db.commit()
    assert usage.counted(db, cole.campaign_id) == []


def test_the_features_page_is_the_admins(admin, dm, db, sheet):
    page = admin.get("/manage/features?days=7")
    assert page.status_code == 200 and "Every use, by day" in page.text and "Never touched" in page.text
    assert dm.get("/manage/features").status_code == 403


def test_manage_and_admin_pages_count_as_backstage_and_keep_their_history(player, db, sheet):
    """Menu Bar Doors (Brett, Nov 20): Manage and the Admin gear became Backstage. A use is kept with the page's name as
    it was recorded, so the Features page shows the old and the new under one name and a day's counts never split."""
    from tests.table_setup import char

    cole = char(db, "Cole")
    who = db.scalar(select(UsageEvent.user_id).limit(1))
    if who is None:
        player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Stealth check", "mod": "+2"},
                    headers={"referer": f"https://askdnd.ai/characters/{cole.id}/battle"})
        who = db.scalar(select(UsageEvent.user_id).limit(1))
    for page in ("Manage", "Manage", "Admin"):
        db.add(UsageEvent(campaign_id=cole.campaign_id, user_id=who, feature="Inbox", page=page))
    db.commit()
    pages = {p["page"]: p["uses"] for p in usage.summary(db, cole.campaign_id, 7)["pages"]}
    assert pages.get("Backstage") == 2 and pages.get("Backstage › Global") == 1 and "Manage" not in pages and "Admin" not in pages
    assert usage.page_of("https://askdnd.ai/c/main/manage/inbox") == "Manage"  # (recorded as before)


def test_a_feature_row_opens_who_and_which_days(player, admin, dm, db, sheet):
    """Brett's picks FE1 and FE2 (docs/mockups/backstage-round-4/, Nov 25): Feature use, under General, a row opening its
    window: who used it and on which days; the legend says only what the chart draws."""
    from tests.table_setup import char

    cole = char(db, "Cole")
    before = len(_events(db, 0, 0))
    player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Stealth check", "mod": "+2"},
                headers={"referer": f"https://askdnd.ai/characters/{cole.id}/battle"})
    _events(db, before + 1)
    page = admin.get(f"/manage/features?days=7&campaign={cole.campaign_id}").text
    assert "<h1>Feature use</h1>" in page and "data-feature-row" in page and "/manage/features/detail?feature=Rolls%3A%20checks" in page
    assert ("Dashed lines" in page) == ('class="ft-release"' in page)
    window = admin.get(f"/manage/features/detail?feature=Rolls%3A%20checks&days=7&campaign={cole.campaign_id}").text
    assert "Rolls: checks" in window and "1 use by 1 person" in window and "Which days" in window
    assert dm.get("/manage/features/detail?feature=Rolls%3A%20checks").status_code == 403
