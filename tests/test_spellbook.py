"""The Spell Book and Concentration (app/spellbook.py): effect groups, averages with upcasting,
the Concentration save, and who can start or end Concentration."""

import json

import pytest

from app import roll_recipes as rr
from app import spellbook as sb
from tests.table_setup import BUNDLE, COLE, char, owned_by
from tests.test_suggestions import HX
from tests.test_wild_shape import cole, cole_sheet

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_effect_groups():
    assert sb.effect_of({"damage": "2d10 radiant", "tags": ["Damage", "Control"]}) == "damage"
    assert sb.effect_of({"healing": "2d4", "tags": ["Healing"]}) == "heal"
    assert sb.effect_of({"tags": ["Control"]}) == "control"
    assert sb.effect_of({"tags": ["Buff"]}) == "support"
    assert sb.effect_of({"casting_time": "Reaction", "damage": "1d6 acid", "tags": ["Damage", "Warding"]}) == "support"  # Absorb Elements
    assert sb.effect_of({"tags": ["Detection"]}) == "utility"


def test_averages_count_upcasting_and_cantrip_tiers():
    moon = rr.spell("Moonbeam")
    assert sb.average(moon, 2, 8)["avg"] == 11.0 and sb.average(moon, 3, 8) == {"avg": 16.5, "dice": "3d10 radiant", "per": "on a failed save"}
    word = rr.spell("Healing Word")
    assert sb.average(word, 3, 8, spell_mod=4)["avg"] == 6 * 2.5 + 4  # 6d4 + Wisdom at a 3rd-level slot
    wisp = rr.spell("Starry Wisp")
    assert sb.average(wisp, 0, 4)["avg"] == 4.5 and sb.average(wisp, 0, 8)["avg"] == 9.0  # 1d8, then 2d8 from level 5
    assert sb.average(None, 3, 8) is None


def test_a_spell_that_adds_to_hits_rolls_nothing_when_cast():
    """Feedback 48 (Tim, Nov 7): Hunter's Mark's 1d6 is added to each hit while it lasts, never rolled on casting; the
    Spell Book says "each hit", Battle's row has nothing to roll, and On a hit lists it while concentrating."""
    from app import character_views as views
    mark = rr.spell("Hunter's Mark")
    assert [e["on"] for e in mark["events"]] == ["rider"]
    assert all(e["on"] == "rider" for n in ("Hex", "Divine Favor") for e in rr.spell(n)["events"])
    assert next(e["on"] for e in rr.spell("Searing Smite")["events"]) == "auto"  # (a smite is cast on the hit: it deals it)
    assert sb.average(mark, 1, 5) == {"avg": 3.5, "dice": "1d6 force", "per": "each hit"}
    assert views.rollable({"recipe": mark})["dice"] == ""
    sheet = {"level": 5, "spells": [{"name": "Hunter's Mark", "roll": mark}]}
    assert sb.riders(sheet, {"spell": "Hunter's Mark", "level": 1}) == [
        {"name": "Hunter's Mark", "when": "Each hit while it lasts", "source": "Concentration",
         "effect": "+1d6 force damage (the spell says which hits count)"}]
    assert sb.riders(sheet, None) == [] and sb.riders(sheet, {"spell": "Bless", "level": 1}) == []


def test_concentration_rules():
    assert sb.concentration_dc(0) == 10 and sb.concentration_dc(31) == 15 and sb.concentration_dc(200) == 30
    assert sb.rounds("Concentration, up to 1 minute") == 10 and sb.rounds("Concentration, up to 10 minutes") == 100
    save = sb.concentration_save(cole_sheet()["saves"])
    assert save["label"] == "+2" and [a["source"] for a in save["adv"]] == ["War Caster"]  # War Caster counts for Concentration
    assert all(not a["when"] for a in save["adv"])  # so it rolls with Advantage


def test_entries_mark_what_works_in_wild_shape():
    sheet = cole_sheet()
    spells = {e["name"]: e for e in sb.entries(sheet, {"Moonbeam", "Starry Wisp"})}
    assert spells["Moonbeam"]["ws"] and not spells["Thorn Whip"]["ws"]
    assert spells["Moonbeam"]["avgs"][3]["avg"] == 16.5 and spells["Moonbeam"]["conc"] and spells["Moonbeam"]["rounds"] == 10


def test_spellbook_and_concentration_for_the_player_only(db, cole, player, dm):
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'data-modal-url="/characters/%d/spellbook"' % cole.id in page and "Spell Book" in page
    book = player.get(f"/characters/{cole.id}/spellbook").text
    assert "data-spellbook" in book and 'data-name="moonbeam"' in book and 'aria-label="Concentrate on Moonbeam"' in book
    assert 'aria-label="Concentrate on' not in dm.get(f"/characters/{cole.id}/spellbook").text  # the DM can look, not act
    assert dm.post(f"/characters/{cole.id}/concentration", data={"key": "spell:Moonbeam", "level": "3"}).status_code == 403
    r = player.post(f"/characters/{cole.id}/concentration", data={"key": "spell:Moonbeam", "level": "3"}, headers=HX)
    assert r.status_code == 200 and "Moonbeam" in r.text and "round 1/10" in r.text
    db.refresh(cole)
    assert cole.concentration == {"spell": "Moonbeam", "key": "spell:Moonbeam", "level": 3, "round": 1, "rounds": 10}
    assert "Con save (Concentration on Moonbeam)" in r.text and 'data-adv="1"' in r.text
    # Brett, 2026-10-29: first in the Status row like a condition, with its color on the page's edge and an emblem;
    # out of the spell bar; and every open window (the Spell Book it was started from) shows it without a reload
    status = r.text.split('class="cond-bar"')[1]
    assert status.index('data-cond="concentration"') < status.index('class="cond-sep"') and "conc-pill" not in r.text.split('id="spell-bar"')[1].split("</div>")[0]
    assert "--edge: var(--cond-concentration)" in r.text
    assert 'data-name="Concentration"' in player.get(f"/characters/{cole.id}/battle").text.split('class="cond-badges"')[1]  # its badge, first
    assert json.loads(r.headers["HX-Trigger"])["characterChanged"] == {"character": cole.id}
    book = player.get(f"/characters/{cole.id}/spellbook").text
    assert "sb-conc-row" in book
    assert "End Concentration on Moonbeam?" in book and ">Switch to " in book  # another spell asks first (Brett, 2026-10-29)
    player.post(f"/characters/{cole.id}/concentration/round", headers=HX)
    db.refresh(cole)
    assert cole.concentration["round"] == 2
    assert player.post(f"/characters/{cole.id}/concentration", data={"key": "spell:Thorn Whip"}).status_code == 400  # not Concentration
    player.post(f"/characters/{cole.id}/concentration/end", headers=HX)
    db.refresh(cole)
    assert cole.concentration is None


def test_spell_bar_shows_the_four_most_recently_used_starred_spells(db, cole, player):
    from app import web
    from app.models import TableRoll

    names = ["Cure Wounds", "Faerie Fire", "Healing Word", "Moonbeam", "Starry Wisp", "Thorn Whip"]
    for n in names:
        player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": f"spell:{n}"}, headers=HX)
    camp = web.campaign(db)
    for n in ("Thorn Whip", "Starry Wisp"):  # Starry Wisp is the latest
        db.add(TableRoll(campaign_id=camp.id, character_id=cole.id, label=n, kind="attack", formula="d20+7", dice=[12], total=19))
        db.flush()
    page = player.get(f"/characters/{cole.id}/battle").text
    bar = page[page.index('class="sb-starred"'):]
    bar = bar[:bar.index("</div>")]
    shown = [n for n in names if f">{n}</button>" in bar]
    assert len(shown) == 4 and bar.index(">Starry Wisp<") < bar.index(">Thorn Whip<") < bar.index(">Cure Wounds<")
    assert ">+2</button>" in bar  # the other two are in the Spell Book


def test_filter_values_say_what_a_successful_save_does():
    by = {e["name"]: e for e in sb.entries(cole_sheet(level=6))}
    assert by["Moonbeam"]["f"]["on_save"] == "Half damage" and by["Moonbeam"]["f"]["area"] == "Area"
    assert by["Moonbeam"]["f"]["roll"] == "Con save" and by["Moonbeam"]["f"]["dmg"] == ["Radiant"]
    assert by["Starry Wisp"]["f"]["roll"] == "Attack roll" and by["Starry Wisp"]["f"]["on_save"] == ""
    groups = sb.filter_groups(list(by.values()))
    assert [g["key"] for g in groups if not g.get("more")] == ["level", "effect", "time", "conc"]  # always visible
    assert all(g["values"] for g in groups if g.get("more"))  # More filters only list values that occur


def test_spell_book_uses_the_shared_list_with_notes(db, cole, player):
    from app import picks

    picks.set_note(db, cole, "spell:Moonbeam", "Opener vs. groups")
    book = player.get(f"/characters/{cole.id}/spellbook").text
    assert 'data-list="spellbook"' in book and 'data-ls-group="level"' in book and "More filters" in book
    assert "✎ Opener vs. groups" in book and "Half on a save" in book
    assert 'data-panel-url="/characters/%d/detail?ref=spell%%3AMoonbeam"' % cole.id in book  # a row opens its side panel


def test_sheet_spells_list_every_spell_with_views(db, cole, player, dm):
    from app import picks

    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    picks.toggle(db, cole, "fav", "spell:Barkskin")
    sheet = player.get(f"/characters/{cole.id}").text
    spells = sheet.split('id="t-spells"')[1].split('id="t-forms"')[0]
    assert 'data-list="sheet-spells"' in spells and 'data-ls-view="fav"' in spells
    row = spells.split('data-ref="spell:Barkskin"')[1][:400]
    assert 'data-views="fav all"' in row  # not prepared, but on the Shortlist
    assert '"prep": "Not prepared"' in row and 'sh-status off wanted' in spells.split('data-ref="spell:Barkskin"')[1][:2500]
    assert 'data-views="ready all"' in spells.split('data-ref="spell:Moonbeam"')[1][:400]
    dm_spells = dm.get(f"/characters/{cole.id}").text.split('id="t-spells"')[1].split('id="t-forms"')[0]
    assert "data-ls-view" not in dm_spells and "Barkskin" in dm_spells  # the DM sees All only, no views


def test_spell_bar_offers_add_when_nothing_is_pinned_and_the_book_pins(db, cole, player, dm):
    bar = player.get(f"/characters/{cole.id}/battle").text
    assert 'class="spell-chip more sb-add"' in bar  # nothing pinned: + Add opens the Spell Book
    assert "sb-add" not in dm.get(f"/characters/{cole.id}/battle").text  # the DM can't pin
    book = player.get(f"/characters/{cole.id}/spellbook").text
    assert '"ref": "spell:Moonbeam"' in book and 'class="pick star"' in book  # each row's pin toggle
    assert 'hx-post="/characters/%d/pick"' % cole.id not in dm.get(f"/characters/{cole.id}/spellbook").text
    player.post(f"/characters/{cole.id}/pick", data={"kind": "star", "ref": "spell:Moonbeam"}, headers=HX)
    bar = player.get(f"/characters/{cole.id}/battle").text
    assert "sb-add" not in bar and ">Moonbeam</button>" in bar
    assert 'class="pick star on static"' in dm.get(f"/characters/{cole.id}/spellbook").text  # the DM sees the pin
