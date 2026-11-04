"""Rules content as data (app/rules_data.py, VTT 0.6): the SRD 5.2.1 in app/data/srd/, read from the official PDF
(scripts/srd_import.py) and checked against its schema on load, plus a campaign's own creations from the database."""

import copy

import pytest
from pydantic import ValidationError

from app import conditions, rules_data, rules_terms
from app import wild_shape as ws
from app.models import Campaign, CampaignContent


def test_every_srd_file_loads_and_fits_its_schema():
    counts = {kind: len(rules_data.srd(kind)) for kind in rules_data.FILES}  # (a summon is in the books only)
    # as many as the SRD 5.2.1 prints: 330 monsters and animals plus the Figurine of Wondrous Power's Giant Fly
    assert counts == {"monster": 331, "spell": 339, "magic_item": 258, "glossary": 155}
    assert [c["name"] for c in rules_data.conditions()] == [
        "Blinded", "Charmed", "Deafened", "Exhaustion", "Frightened", "Grappled", "Incapacitated", "Invisible",
        "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"]


def test_stat_blocks_read_as_the_book_prints_them():
    red = rules_data.find("monster", "Adult Red Dragon")
    assert (red["size"], red["type"], red["tags"], red["alignment"]) == ("Huge", "Dragon", ["Chromatic"], "Chaotic Evil")
    assert (red["ac"], red["initiative"], red["hp"], red["hit_dice"]) == (19, 12, 256, "19d12 + 133")
    assert red["speed"] == {"walk": 40, "climb": 40, "fly": 80} and red["senses"] == {"blindsight": 60, "darkvision": 120}
    assert (red["cr"], red["cr_label"], red["xp"], red["xp_lair"], red["pb"]) == (17.0, "17", 18000, 20000, 6)
    assert red["immunities"] == ["Fire"] and red["saves"]["dex"] == 6 and red["skills"] == {"Perception": 13, "Stealth": 6}
    assert [a["name"] for a in red["actions"]] == ["Multiattack", "Rend", "Fire Breath (Recharge 5–6)", "Spellcasting"]
    assert red["actions"][1]["text"] == "Melee Attack Roll: +14, reach 10 ft. Hit: 13 (1d10 + 8) Slashing damage plus 5 (2d4) Fire damage."
    assert "- **At Will:** Command (level 2 version), Detect Magic, Scorching Ray" in red["actions"][3]["text"]
    assert len(red["legendary_actions"]) == 3 and red["legendary_uses"].startswith("Legendary Action Uses: 3 (4 in Lair).")
    wolf = rules_data.find("monster", "wolf")
    assert (wolf["cr_label"], wolf["section"], wolf["traits"][0]["name"]) == ("1/4", "Animals", "Pack Tactics")
    swarm = rules_data.find("monster", "Swarm of Rats")
    assert (swarm["size"], swarm["type"], swarm["swarm_of"]) == ("Medium", "Beast", "Tiny")
    werebear = rules_data.find("monster", "Werebear")
    assert werebear["speed"] == {"walk": 30} and werebear["speed_note"] == "40 ft. (bear form only), Climb 30 ft. (bear form only)"
    assert rules_data.find("monster", "Will-o’-Wisp")["key"] == "will-o-wisp"  # either apostrophe finds it
    bear = rules_data.find("monster", "Brown Bear")
    assert bear["actions"][1]["text"].startswith("Melee Attack Roll: +5, reach 5 ft.")


def test_no_entry_text_starts_with_the_names_period():
    """A name's closing period printed as a span of its own once stayed at the start of the text (". Melee…")."""
    stray = [(m["name"], e["name"]) for m in rules_data.srd("monster") for part, rows in m.items()
             if isinstance(rows, list) for e in rows if isinstance(e, dict) and str(e.get("text", "")).startswith((".", ",", ";", ":"))]
    assert stray == []


def test_spells_items_and_the_glossary():
    fb = rules_data.find("spell", "Fireball")
    assert (fb["level"], fb["school"], fb["casting_time"], fb["range"], fb["components"]) == (3, "Evocation", "Action", "150 feet", ["V", "S", "M"])
    assert fb["material"] == "a ball of bat guano and sulfur" and fb["higher_levels"].startswith("The damage increases by 1d6")
    alarm = rules_data.find("spell", "alarm")
    assert alarm["ritual"] and alarm["casting_time"] == "1 minute" and "**Mental Alarm.** You are alerted" in alarm["text"]
    assert rules_data.find("spell", "Acid Splash")["cantrip_upgrade"].startswith("The damage increases by 1d6 when you reach levels 5")
    assert rules_data.find("spell", "Animate Objects")["creatures"][0]["fields"]["HP"] == "10 (Medium or smaller), 20 (Large), 40 (Huge)"
    teleport = rules_data.find("spell", "Teleport")["text"]
    assert "| Viewed once or described | 01–43 | 44–53 | 54–73 | 74–00 |" in teleport  # a wrapped cell and a two-line header
    crab = rules_data.find("magic_item", "Apparatus of the Crab")
    assert "| 2 | Forward window shutter opens. | Forward window shutter closes. |" in crab["text"]  # a table across both columns
    armor = rules_data.find("magic_item", "Armor of Invulnerability")
    assert (armor["category"], armor["base"], armor["rarity"], armor["attunement"]) == ("Armor", "Plate Armor", "Legendary", True)
    assert rules_data.find("magic_item", "Figurine of Wondrous Power")["monsters"] == ["giant-fly"]
    blinded = rules_data.find("glossary", "Blinded")
    assert blinded["tag"] == "Condition" and "**Can't See.** You can't see and automatically fail" in blinded["text"]


def test_the_schemas_catch_a_bad_entry():
    wolf = copy.deepcopy(rules_data.find("monster", "Wolf"))
    rules_data.Monster.model_validate(wolf)
    for change in ({"abilities": {"str": 14}}, {"type": "Dinosaur"}, {"cr_label": "1/2"}, {"key": "Not A Key"}, {"hp": "11"},
                   {"speed": {"teleport": 30}}, {"surprise": True}):
        with pytest.raises(ValidationError):
            rules_data.Monster.model_validate({**wolf, **change})
    fb = rules_data.find("spell", "Fireball")
    with pytest.raises(ValidationError):  # a Material component names its material
        rules_data.Spell.model_validate({**fb, "material": ""})
    with pytest.raises(ValidationError):
        rules_data.Spell.model_validate({**fb, "duration": "Concentration, up to 1 minute"})  # but not concentration


def test_wild_shape_reads_the_srd_beasts():
    beasts = ws._catalog()
    assert len(beasts) == 91 and all(b["type"] == "Beast" for b in beasts)
    assert {"Giant Fly", "Swarm of Bats", "Wolf"} <= {b["name"] for b in beasts}
    assert sum(1 for b in beasts if b.get("image")) == 90  # every Beast but the SRD-only Giant Fly has D&D Beyond art
    assert ws.catalog_beast("wolf")["image"].startswith("https://www.dndbeyond.com/avatars/")
    assert ws.senses_text(ws.catalog_beast("Brown Bear")) == "Darkvision 60 ft."


def test_conditions_and_rule_terms_follow_the_srd_list():
    names = rules_data.condition_names()
    assert tuple(conditions.CONDITIONS) == names
    assert set(rules_terms.CONDITION_SUMMARIES) == set(names)  # a summary for each, and none for what isn't one
    assert [t.name for t in rules_terms.TERMS if t.kind == "Condition"] == list(names)
    assert conditions.roll_effects([{"name": "Poisoned"}])["attack"][0]["text"] == "Poisoned: Disadvantage on your attack rolls"


def test_a_campaigns_own_entries_join_the_srd_for_that_campaign_only(db):
    ours, other = Campaign(slug="ours", name="Ours"), Campaign(slug="theirs", name="Theirs")
    db.add_all([ours, other])
    db.flush()
    wolf = rules_data.find("monster", "Wolf")
    shadow = {**wolf, "key": "", "name": "Shadow Wolf", "type": "Monstrosity", "hp": 30, "section": "", "source": ""}
    row = rules_data.save(db, ours.id, "monster", shadow)
    assert (row.key, row.source, "name" in row.data) == ("shadow-wolf", "Homebrew", False)  # key, name and source are columns
    found = rules_data.find("monster", "shadow wolf", db, ours.id)
    assert found["hp"] == 30 and found["source"] == "Homebrew"
    assert rules_data.find("monster", "Shadow Wolf", db, other.id) is None and rules_data.find("monster", "Shadow Wolf") is None
    # one with an SRD key replaces that entry, in this campaign only; the book's title says where it's from
    rules_data.save(db, ours.id, "monster", {**wolf, "hp": 15}, source="Monster Manual (2024)")
    mine = [m for m in rules_data.catalog("monster", db, ours.id) if m["key"] == "wolf"]
    assert len(mine) == 1 and mine[0]["hp"] == 15 and mine[0]["source"] == "Monster Manual (2024)"
    assert rules_data.find("monster", "Wolf", db, other.id)["hp"] == 11
    assert len(rules_data.catalog("monster", db, ours.id)) == 332 and len(rules_data.catalog("monster", db, other.id)) == 331
    names = [m["name"].lower() for m in rules_data.catalog("monster", db, ours.id)]
    assert names == sorted(names)


def test_a_bad_entry_is_refused_on_save_and_skipped_on_read(db):
    camp = Campaign(slug="ours", name="Ours")
    db.add(camp)
    db.flush()
    with pytest.raises(ValueError):
        rules_data.save(db, camp.id, "monster", {"name": "Blob", "hp": 3})
    with pytest.raises(ValueError):
        rules_data.save(db, camp.id, "glossary", {"name": "Flanking", "text": "…"})  # the glossary is the SRD's alone
    db.add(CampaignContent(campaign_id=camp.id, kind="spell", key="old-spell", name="Old Spell", data={"level": 1}))
    db.flush()
    assert rules_data.find("spell", "Old Spell", db, camp.id) is None  # saved before a schema change: left out, no error
    assert len(rules_data.catalog("spell", db, camp.id)) == 339


def test_attribution_is_on_help_about():
    from fastapi.testclient import TestClient

    from app.main import app

    page = TestClient(app).get("/help?tab=about").text
    assert "System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC" in page
    assert "https://creativecommons.org/licenses/by/4.0/legalcode" in page
