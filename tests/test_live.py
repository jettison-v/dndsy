"""One Character page with Play / Sheet / Plan modes, the menu bar's characters (your character, Party ▾), and
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
    for page, mode in ((play, "Battle"), (sheet, "Sheet"), (plan, "Plan")):
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


def party_menu(page: str, id: str = "party-menu") -> str:
    return page.split(f'id="{id}"')[1].split('class="party-all')[0]


def topbar(page: str) -> str:
    return page.split('class="topbar"')[1].split("</header>")[0]


def test_party_menu_keeps_the_mode(player, db):
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    menu = lambda path: party_menu(player.get(path).text)  # noqa: E731
    assert f'href="/characters/{trah.id}/plan"' in menu(f"/characters/{cole.id}/plan")
    assert f'href="/characters/{trah.id}"' in menu(f"/characters/{cole.id}")
    # Each character with class and level, and HP when known; "You" on your own
    hp = cole.snapshot.summary["hit_points"]
    assert f"You · {cole.snapshot.summary['classes'][0]['name']}" in menu("/party")
    assert f"{hp['current']}/{hp['max']} HP" in menu("/party")
    bar = topbar(player.get("/party").text)
    assert ">Everyone at a glance</a>" in bar and 'href="/party"' in bar
    for label in ("Story", "Campaign"):
        assert f">{label}</a>" in bar
    for gone in ("Recap", "Sessions", "Map", "Previously on…", "Battle"):
        assert f">{gone}</a>" not in bar
    assert 'aria-label="Switch character"' not in bar and 'id="char-menu"' not in bar


def test_your_character_opens_in_the_mode_you_used_last(player, db):
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    owned_by(db, cole, "player@example.com")
    mine = lambda path: topbar(player.get(path).text).split('class="char-btn')[0].rsplit("<a ", 1)[1]  # noqa: E731
    assert f'href="/characters/{cole.id}/battle"' in mine("/party")  # Battle until you've used another mode
    player.get(f"/characters/{trah.id}/plan")
    assert f'href="/characters/{cole.id}/plan"' in mine("/party")  # the mode you used last, on any character
    assert f'href="/characters/{trah.id}/plan"' in party_menu(player.get("/c/main/").text)
    player.get(f"/characters/{cole.id}")
    assert f'href="/characters/{cole.id}"' in mine("/c/main/campaign")
    assert ">Cole</span></a>" in topbar(player.get("/party").text)


def test_the_dm_has_no_character_button(dm, db):
    import_bundle(db, BUNDLE)
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    char(db, "Trah").owner_id = None
    db.flush()
    page = dm.get("/party").text
    assert 'title="Your character"' not in topbar(page) and 'class="bn-char' not in page
    assert 'data-menu="party-menu"' in topbar(page) and ">Cole<" in party_menu(page)
    bottom = page.split('class="bottom-nav"')[1].split("</nav>")[0]
    assert re.findall(r">(Story|Campaign|Party|More)<", bottom) == ["Story", "Campaign", "Party", "More"]


def test_bottom_bar_on_phones(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    page = player.get("/party").text
    bottom = page.split('class="bottom-nav"')[1].split("</nav>")[0]
    assert re.findall(r">(Story|Campaign|Cole|Party|More)<", bottom) == ["Story", "Campaign", "Cole", "Party", "More"]
    assert f'href="/characters/{cole.id}/battle"' in bottom and 'data-menu="party-menu-m"' in bottom
    assert ">Everyone at a glance</a>" in page.split('id="party-menu-m"')[1]
    more = page.split('id="more-menu"')[1].split("</div>")[0]
    assert "/sessions" not in more and "/map" not in more and "Sign out" in more


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
    spells = part(plan, "t-spell-list", "t-form-list")
    assert 'data-list="plan-spells"' in spells and 'data-ls-group="prep"' in spells and "Barkskin" in spells  # the shared list
    assert 'data-list="sheet-spells"' in part(sheet, "t-spells", "t-forms")  # the same rows and filters as Sheet
    assert re.findall(r'data-ls-view="(\w+)"', spells) == ["fav", "all"]  # evaluate (Shortlist) and select (All)
    forms = part(plan, "t-form-list", None)
    assert 'data-list="plan-forms"' in forms and "Polar Bear" in forms and 'class="fm-pic"' in forms  # rows with pictures
    assert re.findall(r'data-ls-view="(\w+)"', forms) == ["fav", "all"]  # evaluate (Shortlist) and select (All you can learn)
    assert 'data-ls-group="cr" data-ls-value="2"' in forms and 'data-ls-group="move" data-ls-value="Swim"' in forms
