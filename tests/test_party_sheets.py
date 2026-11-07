"""Each real character's own features, end to end on the server (Brett, Nov 5: "I really do not want anything
character-specific to break tomorrow"). For Cole, Big C, No Name and Trah, from their saved sheets
(tests/fixtures/ddb): every row askdnd lists for them is in its column's side panel, every resource is on Battle, and
every window their pages offer (Cast, Use one, Shift, an item's use, a row's details) opens with something to press or
the reason it can't. The live test does the same things on the twins on the real D&D Beyond (scripts/real_table.py
`*-twin`, `twin-every`)."""

import html
import json
import re
from pathlib import Path

import pytest

from app import character_views as views
from app import characters, ddb
from tests.table_setup import char

HERE = Path(__file__).parent
PARTY = ["cole", "big_c", "no_name", "trah"]
COSTS = {"Action": "action", "Bonus action": "bonus", "Reaction": "reaction"}


def _as(sheet: dict, name: str, db):
    """Cole's place at the table, holding `name`'s sheet."""
    sheet.clear()
    sheet.update(json.loads((HERE / "fixtures" / "ddb" / f"{name}.json").read_text())["data"])
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    return cole, ddb.parse_character(ddb.sanitize(dict(sheet)))


def _urls(page: str, attr: str) -> list[str]:
    return sorted({html.unescape(u) for u in re.findall(rf'{attr}="([^"]+)"', page)})


@pytest.mark.parametrize("name", PARTY)
def test_every_row_and_resource_is_where_it_belongs(player, db, sheet, name):
    cole, parsed = _as(sheet, name, db)
    battle = player.get(f"/characters/{cole.id}/battle").text
    for r in parsed.get("resources") or []:
        if r.get("max") and r["name"] not in ("Spell slots", "Pact slots"):
            assert html.escape(r["name"], quote=False) in battle, f"{name}: {r['name']} isn't on Battle"
    for cost, slug in COSTS.items():
        panel = html.unescape(player.get(f"/characters/{cole.id}/all/{slug}").text)
        for o in views.options(parsed, set()):
            if o.get("cost") == cost:
                assert o["name"] in panel, f"{name}: {o['name']} isn't under {cost}"
    for path in ("", "/battle", "/plan"):
        assert player.get(f"/characters/{cole.id}{path}").status_code == 200
    classes = " / ".join(f"{c['name']} {c['level']}" for c in parsed["classes"])
    assert classes in player.get("/party").text, f"{name}: Party's card"


@pytest.mark.parametrize("name", PARTY)
def test_sheet_lists_every_bonus_action_and_reaction_battle_does(player, db, sheet, name):
    """Feedback 42 (Mark, Nov 7): Trah's reaction spells were on Battle but missing from Sheet's Actions tab. Everything
    Battle's Bonus Action and Reaction columns hold (their See all panels) is on Sheet too."""
    cole, _ = _as(sheet, name, db)
    page = player.get(f"/characters/{cole.id}").text
    actions = page.split('<div id="t-actions">', 1)[1].split('<div id="t-', 1)[0]  # (the Actions tab alone: Spells repeats them)
    on_sheet = set(re.findall(r'data-ref="([^"]+)"', actions))
    for col in ("bonus", "reaction"):
        on_battle = set(re.findall(r'data-ref="([^"]+)"', player.get(f"/characters/{cole.id}/all/{col}").text))
        assert on_battle and on_battle <= on_sheet, (name, col, sorted(on_battle - on_sheet))


@pytest.mark.parametrize("name", PARTY)
def test_every_window_their_pages_offer_opens(player, db, sheet, name):
    cole, parsed = _as(sheet, name, db)
    pages = [player.get(f"/characters/{cole.id}/battle").text, player.get(f"/characters/{cole.id}").text]
    pages += [player.get(f"/characters/{cole.id}/all/{slug}").text for slug in [*COSTS.values(), "action?items=1", "bonus?items=1"]]
    pages.append(player.get(f"/characters/{cole.id}/spellbook").text)
    windows = sorted({u for p in pages for u in _urls(p, "data-use-url")})
    details = sorted({u for p in pages for u in _urls(p, "data-panel-url")})
    assert windows and details, f"{name}: no windows found"
    for url in windows:
        r = player.get(url)
        assert r.status_code == 200, f"{name}: {url} answered {r.status_code}"
        # something to press, or the reason it can't be done (said where it starts, Brett Nov 5)
        assert any(x in r.text for x in ("data-use-go", "<form", 'class="use-said', "rw-note")), f"{name}: {url} offers nothing"
    for url in details:
        assert player.get(url).status_code == 200, f"{name}: {url}"
    if name == "cole":  # Wild Shape: every form's Shift window
        assert sum("wild-shape?form=" in u for u in windows) >= 6
    if name == "no_name":  # Pact Magic, and Shadow Arts' Darkness for a Focus Point
        assert "pact:1" in player.get(f"/characters/{cole.id}/cast?key=spell%3AHunter%27s%20Mark").text
        assert "1 Focus Point · Shadow Arts (6 left)" in player.get(f"/characters/{cole.id}/cast?key=spell%3ADarkness").text


@pytest.mark.parametrize("name, spell, source", [("big_c", "Hellish Rebuke", "Tiefling"), ("big_c", "Darkness", "Tiefling"),
                                                 ("no_name", "Misty Step", "Fey Touched"), ("no_name", "Hunter's Mark", "Fey Touched")])
def test_a_free_cast_from_a_species_or_feat_is_offered_first(player, db, sheet, name, spell, source):
    """Nov 5, found by the pass above: the Cast window never offered a species' or feat's free use (once per Long
    Rest), since the Spell Book's entries dropped it; the unit test built its entry by hand."""
    from urllib.parse import quote

    cole, _ = _as(sheet, name, db)
    window = html.unescape(player.get(f"/characters/{cole.id}/cast?key={quote('spell:' + spell)}").text)
    assert f"Free: {source} (1 left)" in window
    assert re.findall(r"<option[^>]*>([^<]*)", window)[0].startswith(f"Free: {source}")  # first


def test_shadow_arts_darkness_spends_a_focus_point_and_undo_gives_it_back(player, db, sheet):
    """2024 PHB, Warrior of Shadow: Shadow Arts casts Darkness for 1 Focus Point, which D&D Beyond lists with no cost
    (Brett, Nov 5: nothing character-specific may break)."""
    from sqlalchemy import select

    from app.models import BridgeIntent

    cole, _ = _as(sheet, "no_name", db)
    url = f"/characters/{cole.id}/cast?key=spell%3ADarkness"
    r = player.post(url, data={"way": "spend:uses:9414030"}).json()
    assert r["undo"]["spent"] == "spend:uses:9414030" and "Concentrating on Darkness" in r["text"]
    sent = [i.data for i in db.scalars(select(BridgeIntent))]
    assert {"field": "uses:9414030", "delta": 1} in [{k: p.get(k) for k in ("field", "delta")} for p in sent]
    player.post(r["undoUrl"], data=r["undo"])
    sent = [i.data for i in db.scalars(select(BridgeIntent))]
    assert {"field": "uses:9414030", "delta": -1} in [{k: p.get(k) for k in ("field", "delta")} for p in sent]


def test_a_pool_spends_and_gives_back_several_at_once(player, db, sheet):
    """Big C's Lay On Hands (a pool of 30): How many, in one press, and Undo gives the same back (Nov 5)."""
    from sqlalchemy import select

    from app.models import BridgeIntent

    cole, _ = _as(sheet, "big_c", db)
    url = f"/characters/{cole.id}/count?field=uses%3A9414047"
    assert 'name="n"' in player.get(url).text and "How many" in player.get(url).text
    r = player.post(url, data={"to": "use", "n": "7"}).json()
    assert r["text"] == "Lay On Hands: Healing Pool: 23 of 30 left" and r["undo"] == {"to": "back", "n": "7"}
    assert [i.data.get("delta") for i in db.scalars(select(BridgeIntent))] == [7]
    assert player.post(url, data={"to": "use", "n": "99"}).json()["text"].endswith("0 of 30 left")  # never more than is left
    # A small count keeps Use one, a press each
    assert 'name="n"' not in player.get(f"/characters/{cole.id}/count?field=uses%3A9489541").text
