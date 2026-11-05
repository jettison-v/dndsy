"""Character pages: Party, the character page in its modes (Battle, Sheet), what each shows and explains.
D&D Beyond is never called: the characters come from fixtures (tests/table_setup.py)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import characters, ddb
from app.importer import import_bundle
from app.models import ToolCorrection
from tests.table_setup import BUNDLE, COLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_party_page(player, db):
    import_bundle(db, BUNDLE)
    characters.refresh(db, char(db, "Cole"))
    page = player.get("/party").text
    assert 'data-tab="t-glance">At a glance' in page and 'data-tab="t-spells">Spells' in page and 'data-tab="t-items">Items' in page
    assert "Druid 6 / Monk 2" in page and '<span title="Wild Shape">Wild Shape <span class="pips" aria-label="3 of 3 left">' in page  # Cole's card (its whole name on hover)
    assert "Pass. Perc." not in page and '<span class="note">Slots</span> <span class="nowrap">1st' in page
    assert 'data-list="party-spell"' in page and 'data-ls-group="does" data-ls-value="Healing and recovery"' in page  # the shared list
    assert 'data-ls-group="who" data-ls-value="Cole"' in page and "data-ls-search" in page
    assert "Not linked to D&amp;D Beyond yet" in page  # Big C
    assert "Refresh all" not in page  # players can't refresh
    assert f'data-modal-url="/characters/{char(db, "Cole").id}/brief"' in page
    assert "Healing and recovery" in page and "Healing Word" in page  # pooled spells
    assert "Potion of Healing" in page and '<small class="note">×2</small>' in page  # pooled items, Cole's two
    assert player.get("/characters").status_code == 404  # the Party page is the list
    brief = player.get(f"/characters/{char(db, 'Cole').id}/brief").text
    assert "<html" not in brief and "Advantage on saving throws against being charmed" in brief
    assert '<div class="brief-group-title">Advantages</div>' in brief and "Already in the numbers above: +1 to saving throws" in brief
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
                 "Polar Bear", "Wild Shape form", "Focus Points", 'id="live-pill"', "just now",
                 "Bonus actions", "Reactions", "Situational", "Advantage on saving throws against being charmed",
                 "Advantage on Constitution saving throws to maintain Concentration · War Caster",
                 "adv-badge cond", "Training: armor, weapons", "Starry Wisp", "+7"):
        assert text in page, text
    assert "Refresh from D&amp;D Beyond" not in page and "D&amp;D Beyond link" not in page
    assert 'class="pick' not in page  # not this player's character: no stars or reminders


def test_battle_page(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "Wild Shape" in page and "Reminders" in page and "Party" in page
    assert "hasn't pinned anything yet" in page  # Battle shows only what the player pinned
    assert 'id="live-pill"' in page and "See all actions" in page
    panel = player.get(f"/characters/{cole.id}/all/action").text
    assert "<html" not in panel and "Heat Metal" in panel and "Moonbeam" in panel
    one = player.get(f"/characters/{cole.id}/detail", params={"ref": "spell:Moonbeam"}).text
    assert "Moonbeam" in one and "Casting time" in one and "Full description" in one


def test_battle_shows_only_pins_to_players_and_the_usual_options_to_the_dm(player, dm, db):
    from app import picks

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    action = lambda page: page.split('data-econ-col="action"')[1].split('data-econ-col="bonus"')[0]  # noqa: E731
    assert "Pin what you use most" in player.get(f"/characters/{cole.id}/battle").text
    picks.toggle(db, cole, "star", "spell:Heat Metal", "Heat Metal")
    mine = action(player.get(f"/characters/{cole.id}/battle").text)
    assert "Heat Metal" in mine and "Unarmed Strike" not in mine and "See all actions" in mine
    page = dm.get(f"/characters/{cole.id}/battle").text  # the DM can't see pins: the usual options
    theirs = action(page)
    assert "Unarmed Strike" in theirs and "+6" in theirs
    assert "Potion of Healing" in page.split('data-econ-col="bonus"')[1].split('data-econ-col="reaction"')[0]  # a Bonus Action to drink


def test_spell_planner_and_shortlist(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    page = player.get(f"/characters/{cole.id}").text
    assert 'data-list="sheet-spells"' in page and "Prepared 10 of 10" in page and "Cantrips 3 of 3" in page
    assert "Barkskin" in page and "Not prepared" in page and 'data-view="fav"' not in page  # shortlists are on Plan
    assert 'data-ref="spell:Barkskin" data-fav="0"' in player.get(f"/characters/{cole.id}/plan").text  # in All, not shortlisted
    r = player.post(f"/characters/{cole.id}/pick", data={"kind": "fav", "ref": "spell:Barkskin"})
    assert 'class="ico-bookmark"' in r.text and 'aria-pressed="true"' in r.text
    assert 'data-fav="1"' in player.get(f"/characters/{cole.id}").text
    assert 'data-ref="spell:Barkskin" data-fav="1"' in player.get(f"/characters/{cole.id}/plan").text  # now on the Shortlist


def test_inventory_and_feature_sections(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    items = page.split('id="t-items"')[1].split('id="t-features"')[0]
    rows = items.split(' data-ls-row ')[1:]  # Inventory is a list now (roadmap step 11): rows say their group
    keyed = sorted((int(r.split('data-sort-default="')[1].split('"')[0]), r.split('data-group-label="')[1].split('"')[0]) for r in rows)
    groups = [g for _, g in keyed]  # the order the Group sort shows (the page sorts on data-sort-default)
    assert groups.index("Usable in battle") < groups.index("Equipped") < groups.index("Armor")
    demon = next(r for r in rows if "Demon Armor" in r)
    assert 'data-group-label="Armor"' in demon and 'data-views="all"' in demon  # not equipped: only under All
    assert '"kind": "Armor"' in demon and '"attune": "Needs attunement"' in demon  # filter values
    features = page.split('id="t-features"')[1].split('id="t-skills"')[0]
    frows = {r.split("<b>")[1].split("</b>")[0]: r for r in features.split(' data-ls-row ')[1:]}  # a list now (roadmap step 11)
    assert 'data-group-label="Druid"' in frows["Wild Shape"] and '"turn": ["Bonus action"]' in frows["Wild Shape"]
    assert 'data-group-label="Always on, already in your numbers"' in frows["Fleet of Foot"] and '"turn": ["Always on"]' in frows["Fleet of Foot"]
    assert '"uses": "Limited uses"' in frows["Wild Shape"]  # its uses come from the Wild Shape action


def test_situational_folds_what_is_already_counted_and_no_circle_magic(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    situ = player.get(f"/characters/{cole.id}").text.split('id="t-skills"')[1].split('id="situational"')[1]
    assert situ.index("charmed") < situ.index("Already in your numbers") < situ.index("+1 to saving throws")
    page = player.get(f"/characters/{cole.id}").text
    assert "Circle Spell" not in page and "Circle Magic" not in page  # Forgotten Realms rule: not our core books


def test_inspiration_badge_and_core_only_spells(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    assert "Heroic Inspiration" in page and "Heroic Inspiration" in player.get(f"/characters/{cole.id}/battle").text
    assert "Not core: Xanathar" in page  # Absorb Elements is on his sheet, from Xanathar's
    assert "Beast Bond" not in page  # a Xanathar's spell he doesn't have isn't offered
    assert "● proficient" not in page


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
    assert "Underlined in descriptions" in admin.get("/manage/tool-corrections").text
    assert admin.post("/rules/terms/abyssal/underline", data={"value": "on"}).json() == {"on": True}
    assert db.scalar(select(ToolCorrection).where(ToolCorrection.ref == "term:Abyssal")) is None  # back to the default


def test_options_show_what_they_spend():
    from app import character_views as views

    def spends(name, sheet):
        o = next(o for o in views.options(sheet) if o["name"] == name)
        return [(x["label"], x["uses"]["left"], x["uses"]["max"]) for x in o["spends"]]

    cole = ddb.parse_character(COLE)
    assert spends("Flurry of Blows", cole) == [("1 Focus Point", 2, 2)]
    assert spends("Healing Word", cole) == [("1st-level", 4, 4)]
    assert next(o for o in views.options(cole) if o["name"] == "Moonbeam")["tags"] == ["Conc."]  # its "2nd-level slot" chip gives the level
    assert not any(o["name"] == "Wild Shape: Circle Forms" for o in views.options(cole))  # part of Wild Shape, not its own action
    assert spends("Wild Resurgence: Regain Wild Shape", cole) == []  # it gives a use back
    assert spends("Unarmed Strike", cole) == [] and spends("Thorn Whip", cole) == []
    load = lambda n: json.loads((Path(__file__).parent / "fixtures" / "ddb" / f"{n}.json").read_text())["data"]  # noqa: E731
    big_c, no_name = ddb.parse_character(load("big_c")), ddb.parse_character(load("no_name"))
    assert next(o for o in views.options(no_name) if o["name"] == "Hunter's Mark")["tags"][0] == "1st"  # free cast only: level pill stays
    assert spends("Channel Divinity: Divine Sense", big_c) == [("1 use of Channel Divinity", 2, 2)]
    assert spends("Lay On Hands: Purify Poison", big_c) == [("5 HP from the pool", 30, 30)]
    assert spends("Divine Smite", big_c) == [("Free cast", 0, 1), ("or 1st-level", 4, 4)]
    assert not any(o["name"] == "Stunning Strike" for o in views.options(no_name))  # a rider on a hit, under "On a hit"
    assert spends("Tasha's Hideous Laughter", no_name) == [("Pact (1st)", 2, 2)]  # warlock
    assert spends("Hunter's Mark", no_name) == [("Free cast", 1, 1)]  # from a feat, no slot


def test_battle_shows_costs_and_slots_on_their_own_line(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/battle").text
    reactions = player.get(f"/characters/{cole.id}/all/reaction").text
    assert '<span class="spend" title="Uses a 1st-level slot: 4 of 4 left">1st-level <span class="pips"' in reactions  # Absorb Elements
    assert "1 Focus Point" in player.get(f"/characters/{cole.id}/all/bonus").text  # Flurry of Blows, in See all
    assert '<span class="sb-slots" aria-label="Spell slots">' in page and 'class="res-row slots"' not in page  # on the spell bar, once
    resources = page[page.index('<span class="res-label">Resources</span>'):]
    assert resources.index("Luck Points") < resources.index("Focus Points") < resources.index("Uncanny Metabolism")  # most uses first
    assert '<span class="res">Wild Shape' not in page  # its pips are on the Wild Shape row
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": "action:Flurry of Blows"}).text
    assert "Spends" in panel and "1 Focus Point: <b>2 of 2 left</b>" in panel
    spell = player.get(f"/characters/{cole.id}/detail", params={"ref": "spell:Healing Word"}).text
    assert "1st-level: <b>4 of 4 left</b>" in spell and "Can also use a higher slot: 2nd 3/3 · 3rd 3/3" in spell


def test_number_tiles_open_an_explanation(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    battle = player.get(f"/characters/{cole.id}/battle").text
    sheet = player.get(f"/characters/{cole.id}").text
    for kind in ("hp", "ac", "speed", "initiative", "spell", "inspiration"):
        assert f'data-panel-url="/characters/{cole.id}/vital/{kind}"' in battle and f"/vital/{kind}" in sheet
    assert "/vital/proficiency" in sheet and "/vital/perception" in sheet
    ac = player.get(f"/characters/{cole.id}/vital/ac").text
    assert "Unarmored Defense (Wisdom modifier)" in ac and '<tr class="total"><td>Total</td><td class="num">16</td>' in ac
    speed = player.get(f"/characters/{cole.id}/vital/speed").text
    assert "Fleet of Foot (sets your base speed)" in speed and "Unarmored Movement" in speed and "45 ft" in speed
    spell = player.get(f"/characters/{cole.id}/vital/spell").text
    assert "Spell save DC" in spell and "Wisdom modifier" in spell and "+7" in spell
    assert "Stone of Good Luck" in player.get(f"/characters/{cole.id}/vital/initiative").text
    assert "Constitution modifier (+1) × 8 levels" in player.get(f"/characters/{cole.id}/vital/hp").text
    assert player.get(f"/characters/{cole.id}/vital/nope").status_code == 404


def test_skills_tab_groups_by_ability_and_explains(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}").text
    assert '<div class="skill-head"><span>Wisdom</span><button type="button" class="roll-hit" data-roll="check" data-label="Wisdom check" data-mod="+4"' in page
    assert "Passive <span>Insight" in page and 'data-label="Perception check"' in page  # skills and abilities roll
    assert f'data-panel-url="/characters/{cole.id}/vital/skill-sleight-of-hand"' in page
    panel = player.get(f"/characters/{cole.id}/vital/skill-perception").text
    assert "Perception (Wis)" in panel and "Stone of Good Luck" in panel and '<td class="num">+8</td>' in panel


def test_a_spell_key_opens_the_spell_not_a_situational_rule_with_the_same_key():
    from app import character_views as views

    sheet = {"situational": [{"key": "spell:Absorb Elements", "text": "Reaction spell: Absorb Elements"}],
             "spells": [{"key": "spell:Absorb Elements", "name": "Absorb Elements"}]}
    assert views.find(sheet, "spell:Absorb Elements")["section"] == "spells"


def test_pages_have_no_help_lines(player, db):
    """Help lines are gone (Brett, 2026-10-27): the tour and Help explain the pages."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    for page in (player.get(f"/characters/{cole.id}").text, player.get(f"/characters/{cole.id}/battle").text,
                 player.get(f"/characters/{cole.id}/plan").text, player.get("/party").text):
        assert "help-line" not in page and "Got it" not in page
    assert player.post("/help/dismiss", data={"key": "sheet"}).status_code in (404, 405)


def test_battle_column_rules_are_a_chip(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    owned_by(db, cole, "player@example.com")
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert "Circle Forms change your Wild Shape" in battle  # still there, inside the pop-up
    assert 'class="tag rules-chip">Rules (' in battle and "econ-note" not in battle


def test_smites_are_on_battle_and_ammunition_is_a_weapon():
    """Tool corrections built into askdnd (2026-10-23)."""
    from app import character_views as views
    import app.models  # noqa: F401
    from app import ddb

    big_c = json.loads((Path(__file__).parent / "fixtures" / "ddb" / "big_c.json").read_text())["data"]
    sheet = views.apply_overrides(ddb.parse_character(big_c), {})
    smite = next(o for o in views.options(sheet) if o["name"] == "Divine Smite")
    assert smite["common"] and smite["cost"] == "Bonus action"
    cole = views.apply_overrides(ddb.parse_character(COLE), {})
    assert next(i for i in cole["inventory"] if i["name"] == "Arrows")["group"] == "Weapons"


def test_what_anyone_can_do_opens_each_rule_with_its_rolls(player, db):
    """Feedback 8 (Nov 4): Battle's Dash, Dodge, Hide… each open their rule in the side panel, with the checks they roll;
    Attack isn't listed (the attacks are the column's rows)."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    battle = player.get(f"/characters/{cole.id}/battle").text
    assert 'class="basic-act" data-panel-url="/characters/%d/detail?ref=rule%%3Abasic%%3AHide">Hide</button>' % cole.id in battle
    assert ">Attack</button>" not in battle and "Attack, Dash" not in battle
    hide = player.get(f"/characters/{cole.id}/detail?ref=rule:basic:Hide").text
    assert "What anyone can do" in hide and 'data-label="Hide (Stealth)"' in hide and "the Invisible condition, on your D&amp;D Beyond sheet too" in hide
    search = player.get(f"/characters/{cole.id}/detail?ref=rule:basic:Search").text
    assert all(f'data-label="{k} check"' in search for k in ("Insight", "Medicine", "Perception", "Survival"))
    assert "more this turn" in player.get(f"/characters/{cole.id}/detail?ref=rule:basic:Dash").text
    assert player.get(f"/characters/{cole.id}/detail?ref=rule:basic:Attack").status_code == 404


def test_an_unarmed_strike_lists_damage_grapple_and_shove_with_its_dc(player, db):
    """Feedback 5 (Nov 4): its three ways, with the DC worked out (8 + Strength, or Dexterity for a Monk, + Proficiency
    Bonus), in place of D&D Beyond's text, whose numbers aren't filled in."""
    from app import character_views as v

    s = {"abilities": [{"key": "strength", "modifier": 3}, {"key": "dexterity", "modifier": 4}], "proficiency_bonus": 3,
         "attacks": [{"name": "Unarmed Strike", "martial_arts": False}]}
    assert v.unarmed_choices(s, {"name": "Unarmed Strike"})["dc"] == 14
    s["attacks"][0]["martial_arts"] = True
    assert v.unarmed_choices(s, {"name": "Unarmed Strike"})["dc"] == 15 and v.unarmed_choices(s, {"name": "Longsword"}) is None
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    key = next(o["key"] for o in v.options(characters.character_summary(cole), set()) if o["name"] == "Unarmed Strike")
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": key}).text
    assert "Choose one each time" in panel and "<dt>Grapple</dt>" in panel and "<dt>Shove</dt>" in panel and "<b>DC " in panel
