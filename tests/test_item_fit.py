"""What an item would mean for a character (app/item_fit.py; Brett's feedback note 1, docs/mockups/item-for-you/): the item
browser's For <character> section and each row's icon. Items in the catalog's shape (app/giving.py `_item`), made up where
a book's words would be."""

from app import item_fit
from app.ddb_sheet import parse_character
from tests.table_setup import COLE

SHEET = parse_character(COLE)  # (Cole: Druid 6 / Monk 2, Strength 8, Dexterity 15, Wisdom 19, AC 16 by Unarmored Defense)


def item(name, **kw):
    return {"name": name, "attune": False, "attune_note": "", "mods": [], "props": {}, "armor_type": None, "weapon_cat": None, **kw}


def say(f):
    return " | ".join(t for _, t in f["lines"])


def test_a_weapon_says_proficiency_and_the_attack():
    rapier = item("Rapier", weapon_cat=2, attack_type=1, base_name="Rapier", dice="1d8", damage_type="Piercing", props={"Finesse": "", "Vex": ""})
    f = item_fit.fit(SHEET, rapier, "Cole")
    assert f["icon"] == "warn" and f["why"] == "Not proficient: martial weapons"
    assert "Attack +2 to hit (Dexterity +2, Finesse), 1d8 + 2 Piercing." in say(f) and "needs the Weapon Mastery feature" in say(f)
    longsword = item("Longsword, +1", weapon_cat=2, attack_type=1, base_name="Longsword", dice="1d8", damage_type="Slashing",
                     props={"Versatile": "1d10"}, mods=[{"type": "bonus", "sub": "magic", "value": 1, "attuned": False}])
    f = item_fit.fit(SHEET, longsword, "Cole")
    assert f["icon"] == "ok" and "Attack +3 to hit (Strength −1, Proficiency +3, magic +1), 1d8 Slashing; with two hands 1d10." in say(f)


def test_armor_says_training_ac_strength_speed_and_stealth():
    chain = item("Chain Mail", armor_type=3, ac=16, str_req=13, stealth_dis=True)
    f = item_fit.fit(SHEET, chain, "Cole")
    assert f["icon"] == "warn" and f["why"] == "Not trained: Heavy Armor"
    assert "no spellcasting" in say(f) and "AC 16 → 16: Chain Mail's 16, replacing Unarmored Defense" in say(f)
    assert "Needs Strength 13; Cole has 8: Speed −10 ft." in say(f) and "Speed 45 → 25 ft" in say(f) and "Stealth" in say(f)
    leather = item("Leather Armor", armor_type=1, ac=11)
    f = item_fit.fit(SHEET, leather, "Cole")
    assert f["icon"] == "ok" and "AC 16 → 13: Leather Armor's 11 + Dexterity +2" in say(f)


def test_a_shield_ends_a_monks_unarmored_defense():
    f = item_fit.fit(SHEET, item("Shield", armor_type=4, ac=2), "Cole")
    assert f["icon"] == "ok" and "AC 16 → 14: Unarmored Defense (Wisdom modifier) doesn't work with a Shield." in say(f)


def test_attunement_counts_and_what_a_magic_item_grants():
    cloak = item("Cloak of Protection", attune=True, mods=[{"type": "bonus", "sub": "armor-class", "value": 1, "attuned": True},
                                                            {"type": "bonus", "sub": "saving-throws", "value": 1, "attuned": True}])
    f = item_fit.fit(SHEET, cloak, "Cole")
    assert f["icon"] == "ok" and "Attunement 2 → 3 of 3" in say(f) and "AC 16 → 17 while attuned." in say(f) and "+1 to every saving throw" in say(f)
    gauntlets = item("Gauntlets of Ogre Power", attune=True, mods=[{"type": "set", "sub": "strength-score", "value": 19, "attuned": True}])
    assert "Strength 8 → 19 while attuned: its checks and saves −1 → +4." in say(item_fit.fit(SHEET, gauntlets, "Cole"))
    full = {**SHEET, "attuned": ["A", "B", "C"]}
    f = item_fit.fit(full, cloak, "Cole")
    assert f["icon"] == "warn" and f["why"] == "Attunement full"
    wizard_only = item("Robe of the Archmagi", attune=True, attune_note="Sorcerer, Warlock, or Wizard")
    assert item_fit.fit(SHEET, wizard_only, "Cole")["why"] == "Attunement: Sorcerer, Warlock, or Wizard only"
    assert item_fit.fit(SHEET, item("Staff", attune=True, attune_note="Druid"), "Cole")["icon"] == "ok"


def test_gear_has_nothing_to_say():
    assert item_fit.fit(SHEET, item("Rope"), "Cole") == {"icon": None, "why": "", "lines": [], "compare": [], "chips": []}


def test_the_browser_shows_the_icon_and_the_section(player, db, sheet, monkeypatch):
    """The list's icon and the details' For Cole, from the catalog (tests/fixtures/ddb/items.json: a made-up list)."""
    from app import giving
    from app.models import Campaign
    from tests.table_setup import char
    from tests.test_item_browser import ITEMS

    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["sync"]
    db.flush()
    monkeypatch.setattr(giving, "_catalog", {"at": 0.0, "tried": 0.0, "items": []})
    monkeypatch.setattr(giving.ddb, "_get_json", lambda url, timeout: {"data": ITEMS})
    page = player.get(f"/characters/{cole.id}/items/browse").text
    assert 'class="ib-fit ok" title="Attunement 3 of 3"' in page and 'class="ib-fit"' in page  # (the Cloak; Rope: nothing)
    detail = player.get(f"/characters/{cole.id}/items/browse/9002").text
    assert "For Cole: now and with it" in detail and '<td class="k">Attuned</td><td>2 of 3</td><td class="then">3 of 3' in detail
    assert '<span class="tag ib-d same">Same</span>' in detail  # (the made-up Cloak grants nothing here: only attunement)
    assert "For Cole" not in player.get(f"/characters/{cole.id}/items/browse/415").text  # (Rope)


def test_an_item_is_compared_with_what_it_would_take_the_place_of():
    """Brett chose both (Nov 4, docs/mockups/gear-compare/): now and with it, number by number, against each attack it could
    replace (A), and the list's chips from the first (B). Facts, never "best"."""
    staff = item("Quarterstaff, +1", weapon_cat=1, attack_type=1, base_name="Quarterstaff", dice="1d6", damage_type="Bludgeoning",
                 mods=[{"type": "bonus", "sub": "magic", "value": 1, "attuned": False}])
    f = item_fit.fit(SHEET, staff, "Cole")
    unarmed = next(c for c in f["compare"] if c["place"] == "Unarmed Strike")
    hit, dmg = unarmed["rows"]
    assert (hit["now"], hit["then"]) == ("+6", "+6") and hit["dir"] == "same" and hit["d"] == "Same"  # (Martial Arts: Dex +2, +3, +1)
    assert (dmg["now"], dmg["then"], dmg["why"]) == ("1d6+3", "1d6 + 3", "average 6.5 → 6.5") and dmg["chip"] == ""
    assert "Martial Arts" in hit["why"] and f["chips"] == []  # (nothing changes against his Unarmed Strike: no chips)
    shield = item_fit.fit(SHEET, item("Shield", armor_type=4, ac=2), "Cole")["compare"][0]
    assert shield["place"] == "In your other hand"
    assert [(r["k"], r["now"], r["then"], r["dir"]) for r in shield["rows"]][:2] == [("Armor Class", "16", "14", "down"), ("Martial Arts", "yes", "no", "lost")]
    chain = item_fit.fit(SHEET, item("Chain Mail", armor_type=3, ac=16, str_req=13, stealth_dis=True), "Cole")
    assert chain["compare"][0]["place"] == "Unarmored Defense" and chain["chips"] == ["Speed ▼20", "No spells"]
    cloak = item("Cloak of Protection", attune=True, mods=[{"type": "bonus", "sub": "armor-class", "value": 1, "attuned": True},
                                                            {"type": "bonus", "sub": "saving-throws", "value": 1, "attuned": True}])
    assert item_fit.fit(SHEET, cloak, "Cole")["chips"] == ["AC ▲1", "Saves ▲1"]
    assert item_fit._avg("1d8 − 1") == 3.5 and item_fit._avg("8 bludgeoning") == 8 and item_fit._avg("") is None
