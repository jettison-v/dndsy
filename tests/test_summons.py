"""Summons and Find Steed as askdnd's own creatures (app/summons.py; Brett chose A, Nov 4: docs/mockups/steeds-summons/,
DECISIONS): D&D Beyond's Extras has none, so a summon's stat block (a private book, kind "summon") is worked out for
the level it's cast at, the choice made and its master's spell attack and DC, kept on the character with its Hit
Points, and goes with Concentration. Made-up stat blocks only: the book's own words never go in the repo."""

import pytest

from app import books, characters, creatures, summons
from app.models import Campaign
from tests.table_setup import char

BEAST = {"name": "Testing Spirit", "spell": "Summon Beast", "spell_level": 2, "classes": ["Druid"], "choose": ["Air", "Land"],
         "what": "Small Beast, Neutral", "ac": "11 + the spell's level", "hp": "20 (Air only) or 30 (Land only) + 5 for each spell level above 2",
         "speed": "30 ft.; Fly 60 ft. (Air only)", "abilities": {"str": 18, "dex": 11, "con": 16, "int": 4, "wis": 14, "cha": 5},
         "senses": "Darkvision 60 ft.; Passive Perception 12", "languages": "",
         "traits": [{"name": "Glide (Air Only)", "text": "Made-up words for the air."}],
         "actions": [{"name": "Multiattack", "text": "It makes a number of Poke attacks equal to half this spell's level (round down)."},
                     {"name": "Poke", "text": "Melee Attack Roll: Bonus equals your spell attack modifier, reach 5 ft. Hit: 1d8 + 4 + the spell's level Piercing damage."}],
         "turn": "Made-up words: it acts right after you.", "concentration": True}
STEED = {"name": "Testing Steed", "spell": "Find Steed", "spell_level": 2, "classes": ["Paladin"], "choose": ["Celestial", "Fey", "Fiend"],
         "what": "Large Celestial, Fey, or Fiend (Your Choice), Neutral", "ac": "10 + 1 per spell level", "hp": "5 + 10 per spell level",
         "speed": "60 ft., Fly 60 ft. (requires level 4+ spell)", "abilities": {"str": 18, "dex": 12, "con": 14, "int": 6, "wis": 12, "cha": 8},
         "actions": [{"name": "Slam", "text": "Melee Attack Roll: Bonus equals your spell attack modifier, reach 5 ft. Hit: 1d8 plus the spell's level "
                                               "of Radiant (Celestial), Psychic (Fey), or Necrotic (Fiend) damage."}],
         "bonus_actions": [{"name": "Glare (Fiend Only; Recharges after a Long Rest)", "text": "DC equals your spell save DC, made-up words."}]}


def test_a_stat_block_is_worked_out_for_the_level_the_choice_and_its_master():
    assert summons.work(BEAST["hp"], 2, "Air") == "20" and summons.work(BEAST["hp"], 4, "Land") == "40"
    assert summons.work(BEAST["speed"], 3, "Land") == "30 ft." and summons.work(BEAST["speed"], 3, "Air") == "30 ft.; Fly 60 ft."
    assert summons.work("11 + the spell's level + 2 (Guard only)", 5, "Other") == "16"
    assert summons.work("11 + the spell's level + 2 (Guard only)", 5, "Guard") == "18"
    c = summons.creature(STEED, 4, "Fey", attack=6, dc=14, name="Ember", look="a warhorse")
    b = c["block"]
    assert (c["name"], c["look"], b["ac"], b["hp"], b["speed"]) == ("Ember", "a warhorse", 14, 45, {"walk": 60, "fly": 60})
    assert b["actions"][0]["text"] == "Melee Attack Roll: +6, reach 5 ft. Hit: 1d8 + 4 Psychic damage."
    assert b["bonus_actions"] == []  # (Glare is the Fiend's only)
    assert summons.creature(STEED, 2, "Fiend", 6, 14)["block"]["bonus_actions"][0] == {"name": "Glare (Recharges after a Long Rest)", "text": "DC 14, made-up words."}
    assert summons.creature(STEED, 2, "Fey", 6, 14)["block"]["speed"] == {"walk": 60}  # (Fly from level 4)


@pytest.fixture
def summoner(db, sheet):
    """Cole with Your creatures on, two of his spells renamed Summon Beast (Moonbeam: Concentration) and Find Steed (Augury), and the
    made-up stat blocks as the campaign's Player's Handbook entries."""
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["sync", "labs", "creatures"]

    def rename(x, was, now):
        if isinstance(x, dict):
            d = x.get("definition")
            if isinstance(d, dict) and d.get("name") == was:
                d["name"] = now
            for v in x.values():
                rename(v, was, now)
        elif isinstance(x, list):
            for v in x:
                rename(v, was, now)
    rename(sheet, "Moonbeam", "Summon Beast")
    rename(sheet, "Augury", "Find Steed")
    characters.refresh(db, cole)
    books.save(db, "phb-2024", "summon", BEAST)
    books.save(db, "phb-2024", "summon", STEED)
    db.flush()
    return cole


def _key(cole, name):
    from app import spellbook as sb

    return next(e["key"] for e in sb.entries(characters.character_summary(cole)) if e["name"] == name)


def test_casting_a_summon_brings_its_creature_and_concentration_ends_it(player, db, summoner):
    """Board 3: the Cast window asks its kind; cast at a level, its numbers are worked out (Cole's Druid spell attack);
    it's on Battle's switch with them; damage is kept in askdnd; when Concentration ends it's gone."""
    url = f"/characters/{summoner.id}/cast?key={_key(summoner, 'Summon Beast')}"
    win = player.get(url).text
    assert "Testing Spirit: its numbers follow the level you cast it at, and it goes when Concentration ends" in win and 'value="Land"' in win
    r = player.post(url, data={"way": "none", "choice": "Land"})
    assert r.status_code == 200 and "Testing Spirit (Land) is here, at level 2" in r.json()["text"]
    db.refresh(summoner)
    spirit = next(c for c in creatures.own(summoner))
    assert creatures.where(summoner, spirit) == "here" and spirit["block"]["hp"] == 30 and spirit["block"]["ac"] == 13
    page = player.get(f"/characters/{summoner.id}/battle?creature={spirit['id']}").text
    assert "Testing Spirit" in page and "Summon Beast at level 2" in page
    assert player.post(f"/characters/{summoner.id}/creatures/{spirit['id']}/hp", data={"amount": "7", "to": "damage"}).status_code == 204
    db.refresh(summoner)
    assert summoner.companions[str(spirit["id"])]["removed"] == 7
    summoner.concentration = None  # (Concentration ended: a failed save, End, another spell)
    k = creatures.placed(summoner, creatures.card(characters.character_summary(summoner), spirit), spirit)
    assert (k["where"], k["why"]) == ("gone", "Concentration ended")


def test_find_steed_brings_the_one_that_disappeared_or_another(player, db, summoner):
    """Board 4: a new steed with its kind, name and look; at 0 Hit Points it disappears; cast again, the one that
    disappeared comes back as it was (at the new level)."""
    url = f"/characters/{summoner.id}/cast?key={_key(summoner, 'Find Steed')}"
    r = player.post(url, data={"way": "none", "choice": "Fiend", "creature_name": "Ember", "look": "a warhorse"})
    assert r.status_code == 200 and "Ember (Fiend) is here" in r.json()["text"]
    db.refresh(summoner)
    steed = creatures.own(summoner)[0]
    assert "The one that disappeared" not in player.get(url).text  # (it's here: casting again brings a new one, review Nov 4)
    assert player.post(f"/characters/{summoner.id}/creatures/{steed['id']}/hp", data={"amount": "99", "to": "damage"}).status_code == 204
    db.refresh(summoner)
    assert creatures.where(summoner, steed) == "gone"
    win = player.get(url).text
    assert "The one that disappeared" in win and "Ember" in win
    player.post(url, data={"way": "none", "choice": "Celestial", "again": "1"})
    db.refresh(summoner)
    back = creatures.own(summoner)[0]
    assert (back["name"], back["choice"], back["look"], creatures.where(summoner, back)) == ("Ember", "Fiend", "a warhorse", "here")
    # Its World entry (slice 9, board 4): made the first time, and it remembers disappearing
    from app.models import Entity

    story = summoner.creature_story["steed"]
    assert db.get(Entity, story["entity"]).name == "Ember" and [x["what"] for x in story["log"]] == ["cast", "gone", "cast"]
    page = player.get(f"/campaign/{story['entity']}/peek").text
    assert "Companion · Cole's steed" in page and "Disappeared at 0 Hit Points" in page and "Fiend" in page
