"""One Character page with Play / Sheet / Plan modes, the menu bar's character switcher, and
the Live control (Game Mode and refreshing). D&D Beyond is never called (fake fetch)."""

import json
import re

from app import characters, live
from app.importer import import_bundle
from tests.test_characters import BUNDLE, admin, char, dm, down, no_network, owned_by, player  # noqa: F401


def modes_nav(page: str) -> str:
    return re.sub(r' aria-current="page"', "", page.split('<nav class="modes"')[1].split("</nav>")[0])


def test_three_modes_share_one_header(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    url = f"/characters/{cole.id}"
    play, sheet, plan = (player.get(url + m).text for m in ("/battle", "", "/plan"))
    assert 'id="battle-body"' in play and 'class="econ-tabs"' in play and 'role="tablist"' in play  # phones: tabs
    assert 'data-tab="t-spells"' in sheet and 'id="battle-body"' not in sheet
    assert '<table class="party">' not in play and "Full party" not in play  # the party is on Party, not Play
    plan_tabs = re.findall(r'data-tab="t-[a-z-]+"[^>]*>([^<]+)', plan)
    assert [t.strip() for t in plan_tabs] == ["Combos", "Leveling", "Quests", "Notes", "Reminders", "Spells", "Wild Shapes"]
    for page, mode in ((play, "Play"), (sheet, "Sheet"), (plan, "Plan")):
        assert f"Cole · {mode} · askdnd" in page and re.search(rf'aria-current="page">{mode}</a>', page)
    assert modes_nav(play) == modes_nav(sheet) == modes_nav(plan)  # the same switch in every mode
    tabs = re.findall(r'data-tab="t-[a-z]+">([^<]+)', sheet)
    assert tabs == ["Actions", "Spells", "Wild Shape", "Inventory", "Features", "Skills &amp; situational", "Background"]


def test_plan_is_never_shown_to_the_dm(dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    r = dm.get(f"/characters/{cole.id}/plan", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/characters/{cole.id}"
    assert f"/characters/{cole.id}/plan" not in dm.get(f"/characters/{cole.id}/battle").text  # no Plan in the switch


def test_character_switcher_keeps_the_mode(player, db):
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    owned_by(db, cole, "player@example.com")
    menu = lambda path: player.get(path).text.split('id="char-menu"')[1].split("</div>")[0]  # noqa: E731
    assert f'href="/characters/{trah.id}/plan"' in menu(f"/characters/{cole.id}/plan")
    assert f'href="/characters/{trah.id}"' in menu(f"/characters/{cole.id}")
    assert f'href="/characters/{trah.id}/battle"' in menu("/party")  # from elsewhere it opens Play
    bar = player.get("/party").text.split('class="topbar"')[1].split("</header>")[0]
    assert re.search(r">\s*Cole ▾", bar)  # your character, named in the menu bar
    for label in ("Recap", "Sessions", "Campaign", "Map", "Party"):
        assert f">{label}</a>" in bar
    assert ">Battle</a>" not in bar and ">Previously on…</a>" not in bar


def test_bottom_bar_on_phones(player, db):
    import_bundle(db, BUNDLE)
    page = player.get("/party").text
    bottom = page.split('class="bottom-nav"')[1].split("</nav>")[0]
    assert re.findall(r">(Recap|Campaign|Play|Party|More)<", bottom) == ["Recap", "Campaign", "Play", "Party", "More"]
    more = page.split('id="more-menu"')[1].split("</div>")[0]
    assert 'href="/sessions"' in more and 'href="/map"' in more and "Sign out" in more


def test_live_pill_replaces_game_mode_and_refresh_buttons(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    for path in ("/party", f"/characters/{cole.id}", f"/characters/{cole.id}/battle"):
        page = player.get(path).text
        assert 'id="live-pill"' in page and "gm-banner" not in page and "data-game-mode" not in page
        assert "Refresh all from" not in page and "Refresh from D&amp;D Beyond" not in page and "gm-now" not in page
    characters.refresh(db, cole, fetch=down)
    pill = player.get(f"/characters/{cole.id}").text.split('id="live-pill"')[1].split("</button>")[0]
    assert 'live-pill warn' in player.get(f"/characters/{cole.id}").text and "Couldn't refresh Cole" in pill


def test_live_popover_lists_each_copy_and_who_can_refresh(player, dm, db):
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    characters.refresh(db, cole)
    characters.refresh(db, trah)  # private on D&D Beyond: fails
    panel = player.get("/live", params={"c": cole.id}).text
    assert "data-game-mode" in panel and "Refresh Cole now" in panel and "Refresh everyone" not in panel
    assert "couldn&#39;t refresh" in panel and "not linked" in panel  # Trah failed; Big C has no link
    assert 'hx-swap-oob="true"' in panel  # opening it updates the pill too
    assert "Refresh everyone" in dm.get("/live", params={"c": cole.id}).text


def test_refresh_now_is_for_anyone_and_throttled(player, db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    calls = []
    real = characters.refresh

    def counting(db_, ch, *a, **kw):
        calls.append(ch.id)
        return real(db_, ch, *a, **kw)

    monkeypatch.setattr(live.chars, "refresh", counting)
    r = player.post(f"/live/refresh/{cole.id}")
    assert r.status_code == 200 and cole.snapshot.status == "ok" and calls == [cole.id]
    trigger = json.loads(r.headers["HX-Trigger"])
    assert trigger["toast"] == "Updated Cole from D&D Beyond" and trigger["liveRefreshed"] == {"ids": [cole.id]}
    r = player.post(f"/live/refresh/{cole.id}")  # again within 20 seconds: no second fetch
    assert len(calls) == 1 and "a moment ago" in json.loads(r.headers["HX-Trigger"])["toast"]
    assert player.post(f"/live/refresh/{char(db, 'Big C').id}").status_code == 404  # not linked


def test_refresh_everyone_is_for_reviewers_only(player, dm, db):
    import_bundle(db, BUNDLE)
    assert player.post("/live/refresh-all").status_code == 403
    assert char(db, "Cole").snapshot is None
    r = dm.post("/live/refresh-all")
    assert r.status_code == 200 and char(db, "Cole").snapshot.status == "ok" and char(db, "Trah").snapshot.status == "error"
    assert json.loads(r.headers["HX-Trigger"])["toast"] == "Updated 1 from D&D Beyond; couldn't update Trah"
    assert dm.get("/live").status_code == 200


def test_live_needs_sign_in(db):
    from fastapi.testclient import TestClient

    from app.main import app

    anon = TestClient(app)
    assert anon.get("/live").status_code == 401 and anon.post("/live/sync").status_code == 401
    assert anon.post("/live/refresh/1").status_code == 401


def test_game_mode_away_from_play_keeps_the_copy_fresh(player, dm, db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    calls = []
    real = characters.refresh

    def counting(db_, ch, *a, **kw):
        calls.append(ch.entity.name)
        return real(db_, ch, *a, **kw)

    monkeypatch.setattr(live.chars, "refresh", counting)
    pill = player.post("/live/sync").text  # no character on screen: your own
    assert calls == ["Cole"] and 'id="live-pill"' in pill and "just now" in pill and "<html" not in pill
    player.post("/live/sync")
    assert calls == ["Cole"]  # throttled
    dm.post("/live/sync")  # the DM plays no character: everyone linked
    assert sorted(calls) == ["Cole", "Trah"]


def test_game_mode_on_play_swaps_the_body_and_the_pill(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    body = player.post(f"/characters/{cole.id}/sync").text
    assert 'id="battle-body"' in body and 'id="live-pill"' in body and 'hx-swap-oob="true"' in body and "<html" not in body


def test_plan_shortlists_filter_like_sheet(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    url = f"/characters/{cole.id}"
    for ref in ("spell:Barkskin", "form:Polar Bear"):
        player.post(f"{url}/pick", data={"kind": "fav", "ref": ref})
    sheet, plan = player.get(url).text, player.get(f"{url}/plan").text
    part = lambda page, start, end: page.split(f'id="{start}"')[1].split(f'id="{end}"')[0] if end else page.split(f'id="{start}"')[1]  # noqa: E731
    filters = lambda html: re.findall(r'data-filter="([^"]+)"', html)  # noqa: E731
    spells = part(plan, "t-spell-list", "t-form-list")
    assert "data-planner" in plan.split('id="t-spell-list"')[1][:40] and "data-search" in spells and "Barkskin" in spells
    assert filters(spells) == filters(part(sheet, "t-spells", "t-forms"))  # the same spell filters as Sheet
    assert re.findall(r'data-view="(\w+)"', spells) == ["all", "ready"]  # the whole shortlist first
    forms = part(plan, "t-form-list", None)
    assert "data-card-sort" in forms and "data-sortable-cards" in forms and "Polar Bear" in forms
    assert [f for f in filters(forms) if f.startswith("level:")] == ["level:2"]  # CR filters: only what's shortlisted
    assert [f for f in filters(forms) if f.startswith("tag:")][:4] == ["tag:swim", "tag:climb", "tag:burrow", "tag:fly"]
