"""The Spell Book and Concentration (app/spellbook.py): effect groups, averages with upcasting,
the Concentration save, and who can start or end Concentration."""

from app import roll_recipes as rr
from app import spellbook as sb
from tests.test_characters import BUNDLE, COLE, admin, char, dm, no_network, owned_by, player  # noqa: F401
from tests.test_suggestions import HX
from tests.test_wild_shape import cole, cole_sheet  # noqa: F401


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
    assert "data-spellbook" in book and 'data-name="moonbeam"' in book and ">Concentrate</button>" in book
    assert ">Concentrate</button>" not in dm.get(f"/characters/{cole.id}/spellbook").text  # the DM can look, not act
    assert dm.post(f"/characters/{cole.id}/concentration", data={"key": "spell:Moonbeam", "level": "3"}).status_code == 403
    r = player.post(f"/characters/{cole.id}/concentration", data={"key": "spell:Moonbeam", "level": "3"}, headers=HX)
    assert r.status_code == 200 and "Moonbeam" in r.text and "round 1/10" in r.text
    db.refresh(cole)
    assert cole.concentration == {"spell": "Moonbeam", "key": "spell:Moonbeam", "level": 3, "round": 1, "rounds": 10}
    assert "Con save (Concentration on Moonbeam)" in r.text and 'data-adv="1"' in r.text
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
    bar = bar[:bar.index("</span>\n</div>")]
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
    assert 'data-views="ready all"' in spells.split('data-ref="spell:Moonbeam"')[1][:400]
    dm_spells = dm.get(f"/characters/{cole.id}").text.split('id="t-spells"')[1].split('id="t-forms"')[0]
    assert "data-ls-view" not in dm_spells and "Barkskin" in dm_spells  # the DM sees All only, no views
