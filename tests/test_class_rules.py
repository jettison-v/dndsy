"""The class rules table (app/class_rules.py): what each class changes about a turn
in battle, checked against the party's real sheets and made-up characters for the
classes nobody at the table plays."""

import json
from pathlib import Path

from app import character_views as views
from app import class_rules as cr
from app import ddb


def sheet_of(name: str) -> dict:
    raw = json.loads((Path(__file__).parent / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]
    return ddb.parse_character(raw)


def made_up(*classes, features=(), attacks=(), pb=3, mods=None) -> dict:
    """A minimal sheet: classes as (name, level, subclass) tuples."""
    mods = mods or {"Str": 3, "Dex": 3, "Con": 2, "Int": 1, "Wis": 2, "Cha": 0}
    return {"classes": [{"name": n, "level": lv, "subclass": sub} for n, lv, sub in classes],
            "features": [{"name": f, "source": src} for f, src in features], "actions": [],
            "abilities": [{"short": k, "modifier": v} for k, v in mods.items()], "proficiency_bonus": pb,
            "attacks": list(attacks)}


def names(sheet, cost=None):
    return [o["name"] for o in views.options(sheet) if cost is None or o["cost"] == cost]


def test_party_attack_counts():
    assert cr.turn(sheet_of("cole"))["attacks"] == 1  # Monk 2: Extra Attack comes at Monk 5
    assert cr.turn(sheet_of("trah"))["attacks"] == 1  # Fighter 1
    no_name, big_c = cr.turn(sheet_of("no_name")), cr.turn(sheet_of("big_c"))
    assert (no_name["attacks"], no_name["attacks_from"]) == (2, "Extra Attack (Monk)")
    assert (big_c["attacks"], big_c["attacks_from"]) == (2, "Extra Attack (Paladin)")


def test_action_column_says_how_many_attacks():
    cols = views.battle_columns(sheet_of("no_name"), set())
    assert cols["Action"]["sub"] == "One per turn · the Attack action makes 2 attacks"
    assert all("×2 per Attack action" in o["tags"] for o in cols["Action"]["all"] if o["kind"] == "attack")
    assert "sub" not in views.battle_columns(sheet_of("cole"), set())["Action"]


def test_riders_replace_actions_that_are_not_actions():
    no_name = sheet_of("no_name")
    riders = {r["name"]: r for r in cr.turn(no_name)["riders"]}
    assert riders["Stunning Strike"]["cost"] == "1 Focus Point" and "Con save DC 14" in riders["Stunning Strike"]["effect"]
    assert "Savage Attacker" in riders  # origin feat
    assert "Stunning Strike" not in names(no_name)
    big_c = sheet_of("big_c")
    assert not {"Sorcery Points", "Channel Divinity", "Lay On Hands: Healing Pool"} & set(names(big_c))
    assert "Channel Divinity: Divine Sense" in names(big_c)


def test_weapon_masteries_only_when_mastered():
    trah, big_c, no_name = sheet_of("trah"), sheet_of("big_c"), sheet_of("no_name")
    assert not any(cr.is_mastery_action(n) for n in names(trah))  # "Vex (Dart)" isn't an action
    opts = {o["name"]: o for o in views.options(big_c)}
    assert "Mastery: Slow" in opts["Javelin"]["tags"]
    assert "Topple" not in opts["Hammer of Thunderbolts (Maul)"]["meta"]  # Big C hasn't mastered the Maul
    assert not any(t.startswith("Mastery") for o in views.options(no_name) for t in o["tags"])  # Monks don't get Weapon Mastery
    assert "Vex" not in {o["name"]: o for o in views.options(no_name)}["Dart"]["meta"]


def test_everyone_has_an_opportunity_attack():
    for who in ("cole", "trah", "no_name", "big_c"):
        assert "Opportunity Attack" in names(sheet_of(who), "Reaction")


def test_extra_attacks_dont_stack_and_fighters_get_more():
    assert cr.turn(made_up(("Fighter", 11, "")))["attacks"] == 3
    assert cr.turn(made_up(("Fighter", 20, "")))["attacks"] == 4
    assert cr.turn(made_up(("Fighter", 5, ""), ("Monk", 5, "")))["attacks"] == 2
    assert cr.turn(made_up(("Bard", 6, "College of Valor")))["attacks"] == 2
    assert cr.turn(made_up(("Bard", 6, "College of Lore")))["attacks"] == 1
    # a class or book the table doesn't cover still counts if the sheet lists Extra Attack
    assert cr.turn(made_up(("Artificer", 5, "Battle Smith"), features=[("Extra Attack", "Battle Smith")]))["attacks"] == 2


def test_rogue_sneak_attack_scales_and_cunning_action_is_added():
    rogue = made_up(("Rogue", 7, "Thief"))
    riders = {r["name"]: r for r in cr.turn(rogue)["riders"]}
    assert riders["Sneak Attack"]["effect"] == "+4d6"
    assert "save DC 14" in riders["Cunning Strike"]["effect"]  # 8 + Dex 3 + PB 3
    assert {"Cunning Action", "Steady Aim", "Fast Hands"} <= set(names(rogue, "Bonus action"))


def test_choices_only_apply_when_chosen_and_upgrades_replace():
    assert not cr.turn(made_up(("Druid", 7, "Circle of the Moon")))["riders"]
    druid = made_up(("Druid", 15, "Circle of the Moon"), features=[("Elemental Fury: Primal Strike", "Druid")])
    strikes = [r for r in cr.turn(druid)["riders"] if r["name"].startswith("Primal Strike")]
    assert len(strikes) == 1 and strikes[0]["effect"].startswith("+2d8")
    cleric = made_up(("Cleric", 7, "War Domain"), features=[("Divine Strike", "Cleric")])
    assert any(r["name"] == "Divine Strike" for r in cr.turn(cleric)["riders"])
    assert "War Priest" in names(cleric, "Bonus action")


def test_warlock_thirsting_blade_is_for_the_pact_weapon_only():
    lock = made_up(("Warlock", 5, "Fiend Patron"), features=[("Thirsting Blade", "Warlock")])
    t = cr.turn(lock)
    assert t["attacks"] == 1 and t["notes"]["Action"] == ["Attack action: 2 attacks with your pact weapon (Thirsting Blade)"]


def test_light_weapons_give_an_extra_attack_and_nick_moves_it():
    dagger = {"key": "a1", "name": "Dagger", "base": "Dagger", "to_hit": "+5", "damage": "1d4+3", "range": "5 ft", "properties": ["Finesse", "Light", "Nick"]}
    sword = {"key": "a2", "name": "Shortsword", "base": "Shortsword", "to_hit": "+5", "damage": "1d6+3", "range": "5 ft", "properties": ["Finesse", "Light", "Vex"]}
    plain = made_up(("Rogue", 1, ""), attacks=[dagger, sword])
    assert "Light weapon extra attack" in names(plain, "Bonus action")
    nick = made_up(("Fighter", 1, ""), attacks=[dagger, sword], features=[("Dagger (Nick)", "Choice")])
    assert "Light weapon extra attack" in names(nick, "Action")


def test_every_rule_names_a_real_column_and_fills_its_placeholders():
    sheet = made_up(*[(c, 20, None) for c in {r.cls for r in cr.RULES if r.cls != "Feat"}])
    for r in cr.RULES:
        if r.note:
            assert r.note[0] in ("Action", "Bonus action", "Reaction"), r.name
        if r.option:
            assert r.option[0] in ("Action", "Bonus action", "Reaction"), r.name
        for text in (r.note or ("", ""))[1:] + (r.rider or ("", "")) + (r.option or ("", ""))[1:]:
            assert "{" not in cr._fmt(text, cr._values(sheet, 20)), (r.name, text)
