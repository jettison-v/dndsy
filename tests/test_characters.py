"""Characters from D&D Beyond: last good copy, refresh permissions, pages.
D&D Beyond is never called: refreshes use a fake fetch built from fixtures."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, characters, config, ddb
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import Character, CharacterNote, CharacterSnapshot, SheetOverride

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
        return {**COLE, "notes": {"backstory": "PRIVATE BACKSTORY"}}
    raise ddb.DdbError("D&D Beyond says this character is private.")


def down(ddb_id):
    raise ddb.DdbError("Couldn't reach D&D Beyond. Try again later.")


def char(db, name) -> Character:
    return next(c for c in db.scalars(select(Character)) if c.entity.name == name)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(ddb, "fetch_character_json", fake_fetch)
    monkeypatch.setattr(characters.refresh, "__defaults__", (fake_fetch,))
    monkeypatch.setattr(characters.refresh_all, "__defaults__", (fake_fetch,))


def client(monkeypatch, db, email):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,dm@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0]}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


@pytest.fixture
def admin(monkeypatch, db):
    yield client(monkeypatch, db, "admin@example.com")
    app.dependency_overrides.clear()


@pytest.fixture
def dm(monkeypatch, db):
    yield client(monkeypatch, db, "dm@example.com")
    app.dependency_overrides.clear()


@pytest.fixture
def player(monkeypatch, db):
    yield client(monkeypatch, db, "player@example.com")
    app.dependency_overrides.clear()


def test_refresh_stores_a_sanitized_copy_and_summary(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    snap = characters.refresh(db, cole)
    assert snap.status == "ok" and snap.error == "" and snap.fetched_at is not None
    assert "notes" not in snap.raw and "PRIVATE BACKSTORY" not in json.dumps(snap.raw)
    summary = characters.character_summary(cole)
    assert summary["name"] == "Cole Lockhard" and summary["armor_class"] == 16


def test_failed_refresh_keeps_the_last_good_copy(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    good = characters.refresh(db, cole)
    fetched_at, raw = good.fetched_at, dict(good.raw)
    bad = characters.refresh(db, cole, fetch=down)
    assert bad.id == good.id and bad.status == "error" and "Couldn't reach" in bad.error
    assert bad.fetched_at == fetched_at and bad.raw == raw and characters.character_summary(cole)["name"] == "Cole Lockhard"
    # a format change (unparseable data) also keeps the old copy
    characters.refresh(db, cole, fetch=lambda _id: {"name": "Cole", "inventory": [None]})
    assert cole.snapshot.status == "error" and "format" in cole.snapshot.error and cole.snapshot.raw == raw
    assert characters.refresh(db, cole).status == "ok"  # and it recovers
    assert db.scalar(select(CharacterSnapshot).where(CharacterSnapshot.character_id == cole.id)).error == ""


def test_never_fetched_or_unlinked(db):
    import_bundle(db, BUNDLE)
    trah = characters.refresh(db, char(db, "Trah"))
    assert trah.status == "error" and "private" in trah.error and trah.raw is None
    assert characters.character_summary(char(db, "Trah")) is None
    assert "No D&D Beyond link" in characters.refresh(db, char(db, "Big C")).error


def test_old_parser_summaries_are_reparsed(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    cole.snapshot.summary = {"parser_version": 0, "name": "stale"}
    assert characters.character_summary(cole)["name"] == "Cole Lockhard"


def test_set_link_accepts_urls_and_clears_old_copy(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    characters.set_ddb_link(db, cole, "https://www.dndbeyond.com/characters/75423618")
    assert cole.snapshot is not None  # same character: keep it
    characters.set_ddb_link(db, cole, "https://www.dndbeyond.com/characters/999")
    assert cole.ddb_id == "999" and cole.snapshot is None
    with pytest.raises(ddb.DdbError):
        characters.set_ddb_link(db, cole, "not a link")


def owned_by(db, character, email, **kw):
    from app.models import User

    u = db.scalar(select(User).where(User.email == email)) or User(email=email, name=email)
    for k, v in kw.items():
        setattr(u, k, v)
    db.add(u)
    db.flush()
    character.owner_id = u.id
    db.flush()
    return u


def test_party_page(player, db):
    import_bundle(db, BUNDLE)
    characters.refresh(db, char(db, "Cole"))
    page = player.get("/party").text
    assert "Party at a glance" in page and "Druid 6 / Monk 2" in page and "Wild Shape 3/3" in page
    assert "Not linked to D&amp;D Beyond yet" in page  # Big C
    assert "Refresh all" not in page  # players can't refresh
    assert f'data-modal-url="/characters/{char(db, "Cole").id}/brief"' in page
    assert "Healing and recovery" in page and "Healing Word" in page  # pooled spells
    assert "Potion of Healing" in page and "Cole ×2" in page  # pooled items
    assert player.get("/characters", follow_redirects=False).headers["location"] == "/party"
    brief = player.get(f"/characters/{char(db, 'Cole').id}/brief").text
    assert "<html" not in brief and "Advantage on saving throws against being charmed" in brief
    # Pooled spells and items (and each carrier) open the side panel, like on Character
    cid = char(db, "Cole").id
    url = f"/characters/{cid}/detail?ref=spell%3AHealing%20Word"
    assert page.count(f'data-panel-url="{url}"') == 2  # the row and Cole's chip
    assert "Healing Word" in player.get(url).text
    assert f'data-panel-url="/characters/{cid}/detail?ref=' in brief


def test_character_page(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    for text in ("Circle of the Moon", "Armor class", "Heat Metal", "Conc.", "Ring of Invisibility", "Attuned",
                 "Polar Bear", "Wild Shape form", "Focus Points", "Last updated from D&amp;D Beyond just now",
                 "Bonus actions", "Reactions", "Situational", "Advantage on saving throws against being charmed",
                 "Adv. to maintain Concentration", "Training: armor, weapons", "Starry Wisp", "+7"):
        assert text in page, text
    assert "Refresh from D&amp;D Beyond" not in page and "D&amp;D Beyond link" not in page
    assert 'class="pick' not in page  # not this player's character: no stars or reminders


def test_battle_page(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "Wild Shape" in page and "Unarmed Strike" in page and "+6" in page and "Absorb Elements" in page
    assert "Use an item: Potion of Healing" in page and "Easy to forget" in page and "Party" in page
    assert 'data-game-mode="' in page and "See all actions" in page
    panel = player.get(f"/characters/{cole.id}/all/action").text
    assert "<html" not in panel and "Heat Metal" in panel and "Moonbeam" in panel
    one = player.get(f"/characters/{cole.id}/detail", params={"ref": "spell:Moonbeam"}).text
    assert "Moonbeam" in one and "Casting time" in one and "Full description" in one


def test_sheet_shows_quiet_note_when_latest_refresh_failed(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    characters.refresh(db, cole, fetch=down)
    page = player.get(f"/characters/{cole.id}").text
    assert "Heat Metal" in page and "last good copy" in page
    assert "showing the copy from" in player.get(f"/characters/{cole.id}/battle").text


def test_only_the_player_stars_and_reminds(player, admin, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert 'class="pick star' in page and 'class="pick remind' in page and "This is your character" in page
    r = player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Heat Metal"})
    assert r.status_code == 200 and "★" in r.text and 'aria-pressed="true"' in r.text
    situ = cole.snapshot.summary["situational"][0]["key"]
    player.post(f"/characters/{cole.id}/pick", data={"kind": "remind", "ref": situ})
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert "Advantage on saving throws against being charmed (Fey Ancestry)" in battle  # Easy to forget
    assert "Heat Metal" in battle.split("Bonus action")[0]  # starred: shown in the Action column
    assert admin.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Moonbeam"}).status_code == 403
    assert 'class="pick star"' not in admin.get(f"/characters/{cole.id}").text  # admins can't change them either
    player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Heat Metal"})  # toggles off
    assert "Heat Metal" not in player.get(f"/characters/{cole.id}/battle").text.split("Bonus action")[0]


def test_dm_never_sees_reminders(dm, db):
    from app.models import CharacterPick

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    db.add(CharacterPick(character_id=cole.id, kind="remind", ref="custom", label="SECRET REMINDER"))
    db.add(CharacterPick(character_id=cole.id, kind="star", ref="spell:Heat Metal"))
    db.flush()
    battle = dm.get(f"/characters/{cole.id}/battle").text
    assert "SECRET REMINDER" not in battle and "aren't shown to the DM" in battle
    assert "★" not in dm.get(f"/characters/{cole.id}/all/action").text


def test_my_battle_and_character_open_my_character(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    assert player.get("/battle", follow_redirects=False).headers["location"] == "/party?pick=battle"
    owned_by(db, cole, "player@example.com")
    assert player.get("/battle", follow_redirects=False).headers["location"] == f"/characters/{cole.id}/battle"
    assert player.get("/character", follow_redirects=False).headers["location"] == f"/characters/{cole.id}"


def test_game_mode_sync_is_throttled(player, db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    calls = []

    def counting(ddb_id):
        calls.append(ddb_id)
        return fake_fetch(ddb_id)

    monkeypatch.setattr(characters.refresh, "__defaults__", (counting,))
    body = player.post(f"/characters/{cole.id}/sync").text
    assert 'id="battle-body"' in body and "<html" not in body and len(calls) == 1
    player.post(f"/characters/{cole.id}/sync")
    assert len(calls) == 1  # a second viewer moments later doesn't fetch again
    player.post(f"/characters/{cole.id}/sync", data={"now": "1"})
    assert len(calls) == 1  # "Refresh now" also waits at least 20 seconds
    from datetime import timedelta

    cole.snapshot.attempted_at -= timedelta(minutes=3)
    player.post(f"/characters/{cole.id}/sync")
    assert len(calls) == 2


def test_no_character_notes_on_character_pages(dm, db):
    """Character notes are hidden from the DM (CLAUDE.md); these pages never show them."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    db.add(CharacterNote(character_id=cole.id, body="SECRET PLAYER NOTE"))
    characters.refresh(db, cole)
    for path in ("/party", f"/characters/{cole.id}", f"/characters/{cole.id}/battle", f"/characters/{cole.id}/brief"):
        page = dm.get(path).text
        assert "SECRET PLAYER NOTE" not in page and "PRIVATE BACKSTORY" not in page


def test_only_reviewers_can_refresh_or_link(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/refresh", follow_redirects=False).status_code == 403
    assert player.post("/characters/refresh", follow_redirects=False).status_code == 403
    assert player.post(f"/characters/{cole.id}/link", data={"ddb_link": "1"}, follow_redirects=False).status_code == 403
    assert cole.snapshot is None


def test_dm_refreshes_one_and_all(dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    r = dm.post(f"/characters/{cole.id}/refresh", follow_redirects=False)
    assert r.status_code == 303 and cole.snapshot.status == "ok"
    page = dm.get(f"/characters/{cole.id}").text
    assert "Updated from D&amp;D Beyond" in page and "Refresh from D&amp;D Beyond" in page
    page = dm.post("/characters/refresh").text  # follows the redirect back to /party
    assert char(db, "Trah").snapshot.status == "error"
    assert "Updated 1 from D&amp;D Beyond; couldn&#39;t update Trah" in page


def test_admin_links_a_character(admin, db):
    import_bundle(db, BUNDLE)
    big_c = char(db, "Big C")
    admin.post(f"/characters/{big_c.id}/link", data={"ddb_link": "https://www.dndbeyond.com/characters/75423618"})
    assert big_c.ddb_id == "75423618" and big_c.snapshot.status == "ok"
    page = admin.post(f"/characters/{big_c.id}/link", data={"ddb_link": "nope"}).text  # back on Manage › Characters
    assert "Paste the character" in page and big_c.ddb_id == "75423618"


def test_refresh_buttons_show_that_they_are_working(dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    page = dm.get("/party").text
    assert 'data-busy="Refreshing from D&amp;D Beyond…"' in page and 'id="refresh-note" hidden' in page
    assert 'data-busy="Refreshing…"' in dm.get(f"/characters/{cole.id}").text


def test_my_character_comes_first_and_reminders_can_be_removed(player, db):
    import_bundle(db, BUNDLE)
    trah, cole = char(db, "Trah"), char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, trah, "player@example.com")
    page = player.get(f"/characters/{cole.id}/battle").text
    pills = page.split('class="char-nav"')[1].split("</div>")[0]
    assert pills.index(">Trah<") < pills.index(">Big C<") < pills.index(">Cole<")  # mine, then by name
    owned_by(db, cole, "player@example.com")
    trah.owner_id = None
    situ = cole.snapshot.summary["situational"][0]["key"]
    player.post(f"/characters/{cole.id}/pick", data={"kind": "remind", "ref": situ})
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert 'class="forget-x"' in battle and 'hx-swap="delete"' in battle
    assert "#t-situ" not in battle  # links never jump to a tab


def test_drag_and_drop_order_is_saved_for_the_player_only(player, admin, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'data-sort-column="Action"' in page and "sortablejs@1.15.2" in page
    keys = ["spell:Thorn Whip", "attack:unarmed", "spell:Starry Wisp"]
    r = player.post(f"/characters/{cole.id}/order", data={"column": "Action", "keys": keys})
    assert r.status_code == 204
    action = player.get(f"/characters/{cole.id}/battle").text.split("Bonus action")[0]
    assert action.index("Thorn Whip") < action.index("Unarmed Strike") < action.index("Starry Wisp")
    assert admin.post(f"/characters/{cole.id}/order", data={"column": "Action", "keys": keys}).status_code == 403
    assert "data-sort-column" not in admin.get(f"/characters/{cole.id}/battle").text


def test_spell_planner_and_shortlist(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert "data-planner" in page and "Prepared 10 of 10" in page and "Cantrips 3 of 3" in page
    assert "Barkskin" in page and "Not prepared" in page and 'data-view="fav"' in page
    r = player.post(f"/characters/{cole.id}/pick", data={"kind": "fav", "ref": "spell:Barkskin"})
    assert "♥" in r.text
    assert 'data-fav="1"' in player.get(f"/characters/{cole.id}").text


def test_inventory_and_feature_sections(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    items = page.split('id="t-items"')[1].split('id="t-features"')[0]
    assert items.index("Usable in battle") < items.index("Equipped") < items.index("Everything else")
    assert "Demon Armor" in items.split("Everything else")[1]  # not equipped: folded, under Armor
    features = page.split('id="t-features"')[1].split('id="t-situ"')[0]
    assert features.index("Wild Shape") < features.index("Always on, already in your numbers") < features.index("Fleet of Foot")


def test_side_panel_for_everything_and_admin_regrouping(player, admin, db):
    from app.models import SheetOverride

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert "data-panel-url=\"/characters/%d/detail?ref=" % cole.id in page and "<details class=\"opt" not in page
    for ref in ("spell:Barkskin", "feature:Druid:Wild Shape", "action:Wild Shape", "attack:unarmed",
                cole.snapshot.summary["inventory"][0]["key"], cole.snapshot.summary["situational"][0]["key"], "form:Polar Bear"):
        r = player.get(f"/characters/{cole.id}/detail", params={"ref": ref})
        assert r.status_code == 200 and "<html" not in r.text and 'class="mech"' in r.text, ref
    wild = player.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    assert "for 3 hours" in wild  # D&D Beyond's formula {{(classlevel/2)@rounddown}} filled in
    assert "regroup for every character" not in wild
    assert player.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "x", "field": "battle", "value": "hide"}).status_code == 403
    admin.post(f"/characters/{cole.id}/override", data={"ref": "feature:Wood Elf:Fleet of Foot", "oref": "feature:Fleet of Foot",
                                                        "field": "feature_group", "value": "use"})
    features = player.get(f"/characters/{cole.id}").text.split('id="t-features"')[1].split('id="t-situ"')[0]
    assert features.index("Fleet of Foot") < features.index("Always on, already in your numbers")
    assert "regroup for every character" in admin.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    admin.post(f"/characters/{cole.id}/override", data={"ref": "attack:unarmed", "oref": "attack:Unarmed Strike", "field": "battle", "value": "hide"})
    assert "Unarmed Strike" not in player.get(f"/characters/{cole.id}/battle").text.split("Bonus action")[0]
    assert db.scalar(select(SheetOverride).where(SheetOverride.ref == "attack:Unarmed Strike")).set_by == "admin@example.com"


def test_situational_folds_what_is_already_counted_and_no_circle_magic(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    situ = player.get(f"/characters/{cole.id}").text.split('id="t-situ"')[1].split('id="t-skills"')[0]
    assert situ.index("charmed") < situ.index("Already in your numbers") < situ.index("+1 to saving throws")
    page = player.get(f"/characters/{cole.id}").text
    assert "Circle Spell" not in page and "Circle Magic" not in page  # Forgotten Realms rule: not our core books


def test_universal_regrouping_and_admin_characters_page(player, admin, db):
    from app.models import SheetOverride

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    panel = admin.get(f"/characters/{cole.id}/detail", params={"ref": cole.snapshot.summary["inventory"][-1]["key"]}).text
    assert "Show in askdnd" in panel and "Inventory group" in panel  # gear is clickable and can be regrouped
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "item:Bag of Holding", "field": "item_group", "value": "Gear"})
    items = player.get(f"/characters/{cole.id}").text.split('id="t-items"')[1].split('id="t-features"')[0]
    assert items.index("Everything else") < items.index("Bag of Holding")  # no longer under Equipped
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "spell:Heat Metal", "field": "hide", "value": "hide"})
    assert "Heat Metal" not in player.get(f"/characters/{cole.id}").text
    admin.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": "spell:Healing Word", "field": "cost", "value": "Action"})
    page = admin.get("/admin/characters").text
    assert "Bag of Holding" in page and "Heat Metal" in page and "Undo" in page and "D&amp;D Beyond links" in page
    o = db.scalar(select(SheetOverride).where(SheetOverride.ref == "spell:Heat Metal"))
    admin.post(f"/admin/characters/overrides/{o.id}/delete")
    assert "Heat Metal" in player.get(f"/characters/{cole.id}").text
    assert player.get("/admin/characters").status_code == 403
    assert player.post(f"/characters/{cole.id}/link", data={"ddb_link": "1"}).status_code == 403


def test_inspiration_badge_and_core_only_spells(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    assert "Heroic Inspiration" in page and "Heroic Inspiration" in player.get(f"/characters/{cole.id}/battle").text
    assert "Not core: Xanathar" in page  # Absorb Elements is on his sheet, from Xanathar's
    assert "Beast Bond" not in page  # a Xanathar's spell he doesn't have isn't offered
    assert "● proficient" not in page


def test_saving_a_regrouping_returns_only_that_setting(admin, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    r = admin.post(f"/characters/{cole.id}/override", data={"ref": "feature:Druid:Wild Shape", "oref": "feature:Wild Shape",
                                                            "field": "feature_group", "value": "passive"})
    assert r.status_code == 200 and r.text.strip().startswith('<div class="ov-field">') and "peek-head" not in r.text
    assert "✓ Saved" in r.text and 'class="ov-opt on" aria-pressed="true"' in r.text and "Saved for every character" in r.headers["HX-Trigger"]
    panel = admin.get(f"/characters/{cole.id}/detail", params={"ref": "feature:Druid:Wild Shape"}).text
    assert panel.count('class="ov-field"') == 2  # Show in askdnd + Features group, each saved on its own


def test_descriptions_underline_rule_terms_with_definitions(admin, player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    armor = next(x for x in characters.character_summary(cole)["inventory"] if "you know Abyssal" in (x.get("text") or ""))
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": armor["key"]}).text
    assert 'data-term="abyssal">Abyssal</span>' in panel and 'data-term="unarmed-strike">Unarmed Strikes</span>' in panel
    assert panel.count('data-term="unarmed-strike"') == 1
    data = player.get("/rules/terms.json").json()
    assert data["terms"]["abyssal"]["kind"] == "Rare language" and data["admin"] is False and "abyssal" in data["on"]
    assert player.post("/rules/terms/abyssal/underline", data={"value": "off"}).status_code == 403

    assert admin.post("/rules/terms/abyssal/underline", data={"value": "off"}).json() == {"on": False}
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": armor["key"]}).text
    assert 'data-term="abyssal"' not in panel and 'data-term="unarmed-strike"' in panel
    assert "Underlined in descriptions" in admin.get("/admin/characters").text
    assert admin.post("/rules/terms/abyssal/underline", data={"value": "on"}).json() == {"on": True}
    assert db.scalar(select(SheetOverride).where(SheetOverride.ref == "term:Abyssal")) is None  # back to the default


def test_item_notes_are_stored_apart_and_everyone_sees_them(player, dm, db):
    from app.models import CharacterItemNote

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    flask = next(i for i in COLE["inventory"] if i["definition"]["name"] == "Flask")
    with_note = {**COLE, "characterValues": COLE["characterValues"] + [{"typeId": 9, "valueId": str(flask["id"]), "value": "Blessed by Myna"}]}
    characters.refresh(db, cole, fetch=lambda _id: with_note)
    assert "Blessed by Myna" not in json.dumps(cole.snapshot.raw) and "Blessed by Myna" not in json.dumps(cole.snapshot.summary)
    assert db.scalar(select(CharacterItemNote)).note == "Blessed by Myna"
    for who in (player, dm):  # the DM sees item notes too
        panel = who.get(f"/characters/{cole.id}/detail", params={"ref": f"item:{flask['id']}"}).text
        assert "Player's note" in panel and "Blessed by Myna" in panel
    characters.refresh(db, cole, fetch=lambda _id: COLE)  # note deleted on D&D Beyond
    assert db.scalar(select(CharacterItemNote)) is None
