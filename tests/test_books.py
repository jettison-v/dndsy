"""Books (app/books.py; data strategy, 2026-10-27, Brett's answer 8): a private rules book's entries live only in the
database, each campaign's lookups use the books switched on in its Settings, and the first book is the 2024 Monster
Manual's Beasts among Wild Shape's forms, labelled "MM 2024".

Every beast here is made up: no book's stat blocks or text go into the repo (CLAUDE.md › Rule books)."""

import copy

import pytest

from app import books, rules_data
from app import wild_shape as ws
from app.models import BookEntry, Campaign
from scripts import book_load
from tests.table_setup import char, owned_by
from tests.test_wild_shape import cole

pytestmark = pytest.mark.usefixtures("no_network")


def made_up_beast(**over) -> dict:
    """A Beast of our own, in the monster shape (the Wolf's SRD stat block as the skeleton, renamed and changed)."""
    wolf = copy.deepcopy(rules_data.find("monster", "Wolf"))
    hound = {**wolf, "key": "", "name": "Glimmer Hound", "hp": 13, "ac": 13, "source": "",
             "traits": [{"name": "Glimmer", "text": "The hound sheds Dim Light in a 5-foot radius."}],
             "actions": [{"name": "Bite", "text": "Melee Attack Roll: +4, reach 5 ft. Hit: 6 (1d8 + 2) Radiant damage."}]}
    return hound | over


def test_a_campaigns_books_join_its_lookups_and_nothing_else(db):
    ours, other = Campaign(slug="ours", name="Ours"), Campaign(slug="theirs", name="Theirs", books=[])
    db.add_all([ours, other])
    db.flush()
    assert ours.books == list(books.DEFAULT) and books.on(ours) == ["phb-2024", "dmg-2024", "mm-2024"]  # the 2024 core books
    row = books.save(db, "mm-2024", "monster", made_up_beast(), page=12, image="https://www.dndbeyond.com/avatars/x.jpeg")
    assert (row.book, row.key, row.page, "name" in row.data, "source" in row.data) == ("mm-2024", "glimmer-hound", 12, False, False)
    books.save(db, "mm-2024", "monster", {**rules_data.find("monster", "Wolf"), "hp": 99})  # the same key as the SRD's Wolf

    found = rules_data.find("monster", "glimmer hound", db, ours.id)
    assert (found["source"], found["page"], found["image"]) == ("MM 2024", 12, "https://www.dndbeyond.com/avatars/x.jpeg")
    assert books.label(found) == "MM 2024 p. 12"
    wolves = [m for m in rules_data.catalog("monster", db, ours.id) if m["key"] == "wolf"]
    assert len(wolves) == 1 and (wolves[0]["hp"], wolves[0]["source"]) == (99, "MM 2024")  # a book comes before the SRD
    assert len(rules_data.catalog("monster", db, ours.id)) == len(rules_data.srd("monster")) + 1
    # Off, or no campaign: the SRD alone
    assert rules_data.find("monster", "Glimmer Hound", db, other.id) is None and rules_data.find("monster", "Glimmer Hound") is None
    assert rules_data.find("monster", "Wolf", db, other.id)["source"] == rules_data.SOURCE
    # The campaign's own homebrew comes before its books
    rules_data.save(db, ours.id, "monster", {**made_up_beast(), "hp": 40})
    assert rules_data.find("monster", "Glimmer Hound", db, ours.id)["hp"] == 40


def test_switching_a_book_off_hides_it_and_deletes_nothing(db):
    ours = Campaign(slug="ours", name="Ours")
    db.add(ours)
    db.flush()
    books.save(db, "mm-2024", "monster", made_up_beast())
    assert books.switch(ours, "mm-2024", False) == "Monster Manual (2024) is off for Ours."
    assert books.on(ours) == ["phb-2024", "dmg-2024"] and rules_data.find("monster", "Glimmer Hound", db, ours.id) is None
    assert db.query(BookEntry).count() == 1  # still there
    books.switch(ours, "mm-2024", True)
    assert rules_data.find("monster", "Glimmer Hound", db, ours.id)["source"] == "MM 2024"
    assert books.switch(ours, "xgte", True) == "askdnd doesn't know that book."


def test_a_books_entries_are_read_once_until_one_changes(db, monkeypatch):
    """A character page doesn't read and check a whole book each time: the entries are kept until one is added,
    changed or removed (here, or by scripts/book_load.py in another process)."""
    ours = Campaign(slug="ours", name="Ours")
    db.add(ours)
    db.flush()
    books.save(db, "mm-2024", "monster", made_up_beast())
    checked = []
    fits = rules_data.fits
    monkeypatch.setattr(rules_data, "fits", lambda kind, entry, what: checked.append(entry["key"]) or fits(kind, entry, what))
    for _ in range(3):
        assert [m["name"] for m in books.entries(db, "monster", ours.id)] == ["Glimmer Hound"]
    assert checked == ["glimmer-hound"]
    books.save(db, "mm-2024", "monster", made_up_beast(hp=20))  # changed here
    assert books.entries(db, "monster", ours.id)[0]["hp"] == 20
    db.add(BookEntry(book="mm-2024", kind="monster", key="ember-cat", name="Ember Cat",
                     data={k: v for k, v in made_up_beast(name="Ember Cat").items() if k not in ("key", "name", "source")}))
    db.flush()  # added elsewhere: the count says so
    assert {m["name"] for m in books.entries(db, "monster", ours.id)} == {"Glimmer Hound", "Ember Cat"}

def test_a_bad_book_entry_is_refused_on_save_and_skipped_on_read(db):
    ours = Campaign(slug="ours", name="Ours")
    db.add(ours)
    db.flush()
    with pytest.raises(ValueError):
        books.save(db, "mm-2024", "monster", {"name": "Blob", "hp": 3})
    with pytest.raises(ValueError):
        books.save(db, "not-a-book", "monster", made_up_beast())
    db.add(BookEntry(book="mm-2024", kind="monster", key="old-beast", name="Old Beast", data={"hp": 3}))
    db.flush()
    assert rules_data.find("monster", "Old Beast", db, ours.id) is None  # saved before a schema change: left out


def test_wild_shape_offers_the_books_beasts_labelled_and_switchable(db, cole, player, dm):
    books.save(db, "mm-2024", "monster", made_up_beast(), page=12)
    url = f"/characters/{cole.id}"
    page = player.get(url).text  # Sheet › Wild Shape: every form Cole could learn
    assert "<b>Glimmer Hound</b>" in page and 'title="From a book this campaign uses (Manage › Settings › Books)">MM 2024</span>' in page
    assert 'data-ls-value="MM 2024"' in page  # the Book filter
    panel = player.get(f"{url}/form?name=Glimmer Hound").text
    assert ">MM 2024 p. 12</span>" in panel and "Stat block from the Monster Manual (2024), p. 12, a book this campaign uses" in panel
    assert "6 (1d8 + 2) Radiant" in panel
    assert "Glimmer Hound" in player.get(f"{url}/plan").text  # Plan › Wild Shapes too
    r = player.post(f"{url}/pick", data={"kind": "remind", "ref": "form:Glimmer Hound"})
    assert r.status_code == 200 and "Glimmer Hound (Wild Shape, CR 1/4)" in player.get(f"{url}/battle").text
    assert "Stat block from the SRD 5.2.1" in player.get(f"{url}/form?name=Polar Bear").text  # the SRD's forms stay the SRD's

    # The campaign's DM switches the book off on Manage › Settings › Books: only the SRD's Beasts
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    assert player.post("/c/main/manage/settings/books/mm-2024", data={}).status_code == 403  # not a player's
    settings = dm.get("/c/main/manage/settings").text
    assert '<section class="section" id="books">' in settings and "Monster Manual (2024)" in settings and "1 monster" in settings
    r = dm.post("/c/main/manage/settings/books/mm-2024", data={}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/c/main/manage/settings#books"
    db.refresh(db.get(Campaign, cole.campaign_id))
    assert "mm-2024" not in db.get(Campaign, cole.campaign_id).books
    page = player.get(url).text
    assert "Glimmer Hound" not in page and 'data-ls-value="MM 2024"' not in page
    assert player.get(f"{url}/form?name=Glimmer Hound").status_code == 404
    dm.post("/c/main/manage/settings/books/mm-2024", data={"on": "1"})
    assert "<b>Glimmer Hound</b>" in player.get(url).text


def test_settings_say_when_no_book_is_in_askdnd(db, admin):
    main = Campaign(slug="main", name="Main")
    db.add(main)
    db.flush()
    assert "No books are in askdnd yet, so lookups use the SRD alone." in admin.get("/c/main/manage/settings").text
    assert ws.beasts(db, main.id) == ws._catalog()


# ------------------------------------------------------------------ the loader (scripts/book_load.py)


def ddb_beast(**over) -> dict:
    """D&D Beyond's data for a made-up Beast, in the shape of private/books/mm-2024/monsters-data.json."""
    return {
        "name": "Glimmer Hound", "typeId": 2, "subTypes": [], "sizeId": 4, "alignmentId": 10, "armorClass": 13,
        "initiativeBonus": 2, "averageHitPoints": 13, "hitPointDice": {"diceString": "3d8 + -1"}, "challengeRatingId": 3,
        "stats": [{"statId": i, "value": v} for i, v in enumerate((12, 15, 9, 3, 12, 6), start=1)],
        "savingThrows": [{"statId": 2, "bonusModifier": None}], "skillsHtml": "Stealth +4, Perception +3",
        "damageAdjustments": [9, 22, 41], "conditionImmunitiesHtml": "Charmed, Frightened",
        "senses": [{"senseId": 2, "notes": "60 ft."}], "passivePerception": 13, "languages": [], "languageDescription": None,
        "movements": [{"movementId": 1, "speed": 40, "notes": None}, {"movementId": 5, "speed": 20, "notes": None}],
        "swarm": None, "isLegendary": False, "isMythic": False, "hasLair": False, "legendaryActionsDescription": "",
        "specialTraitsDescription": "<p><em><strong>Glimmer.</strong></em> The hound&rsquo;s fur sheds Dim Light.</p>",
        "actionsDescription": "<p><em><strong>Bite.</strong> Melee Attack Roll:</em>&nbsp;+4;{\"diceNotation\":\"1d20+4\"}) , reach 5 ft. "
                              "<em>Hit:</em> 4 (1d4 – 2) Radiant damage, and it can&rsquo;t take opportunity attack;Opportunity Attacks.</p>",
        "bonusActionsDescription": "", "reactionsDescription": "", "sourceId": 147, "sourcePageNumber": 12,
        "avatarUrl": "https://www.dndbeyond.com/avatars/x.jpeg",
    } | over


def test_the_loader_turns_ddb_data_into_the_monster_shape():
    entry, page, image = book_load.convert(ddb_beast())
    assert (entry["key"], entry["size"], entry["type"], entry["alignment"]) == ("glimmer-hound", "Medium", "Beast", "Unaligned")
    assert (entry["hp"], entry["hit_dice"], entry["cr"], entry["cr_label"], entry["xp"], entry["pb"]) == (13, "3d8 − 1", 0.25, "1/4", 50, 2)
    assert entry["saves"] == {"str": 1, "dex": 4, "con": -1, "int": -4, "wis": 1, "cha": -2}  # Dex proficient
    assert entry["skills"] == {"Stealth": 4, "Perception": 3} and entry["speed"] == {"walk": 40, "swim": 20}
    assert (entry["resistances"], entry["immunities"], entry["vulnerabilities"]) == (["Fire"], ["Poison"], ["Fire"])
    assert entry["condition_immunities"] == ["Charmed", "Frightened"] and entry["senses"] == {"darkvision": 60}
    assert entry["traits"] == [{"name": "Glimmer", "text": "The hound's fur sheds Dim Light."}]
    assert entry["actions"][0]["text"] == ("Melee Attack Roll: +4, reach 5 ft. Hit: 4 (1d4 − 2) Radiant damage, "
                                           "and it can't take Opportunity Attacks.")  # D&D Beyond's markup gone
    assert (page, image, entry["languages"], entry["section"]) == (12, "https://www.dndbeyond.com/avatars/x.jpeg", "None", "Animals")
    with pytest.raises(book_load.Unconvertible):
        book_load.convert(ddb_beast(damageAdjustments=[999]))  # something it doesn't know: fail, never guess


def test_the_loader_takes_saves_and_xp_from_the_books_own_text(tmp_path):
    (tmp_path / "animals.md").write_text(
        "### Glimmer Hound\n\nMedium Beast, Unaligned\n\n| Ability | Score | Mod | Save |\n| --- | --- | --- | --- |\n"
        "| Str | 12 | +1 | +1 |\n| Dex | 15 | +2 | +4 |\n| Con | 9 | −1 | −1 |\n\n| Ability | Score | Mod | Save |\n"
        "| --- | --- | --- | --- |\n| Int | 3 | −4 | −4 |\n| Wis | 12 | +1 | +3 |\n| Cha | 6 | −2 | −2 |\n\nCR 0 (XP 0; PB +2)\n")
    printed = book_load.printed(tmp_path)
    assert printed == {"Glimmer Hound": {"saves": {"str": 1, "dex": 4, "con": -1, "int": -4, "wis": 3, "cha": -2}, "xp": 0, "size": "Medium"}}
    entry, _, _ = book_load.convert(ddb_beast(challengeRatingId=1), printed)
    assert entry["saves"]["wis"] == 3 and entry["xp"] == 0  # D&D Beyond's data missed the Wisdom save


def test_the_loader_takes_legendary_actions_lair_xp_and_languages_from_the_book(tmp_path):
    """Every monster in the book, not only Beasts (Brett, 2026-10-30: encounters need them all)."""
    (tmp_path / "monsters.md").write_text(
        "### Glimmer Hound\n\nHuge Beast (Titan, Demon), Unaligned\n\nAC 13 Initiative +5 (15)\n\nSpeed 40 ft., Fly 30 ft. (hover)\n\n"
        "| Ability | Score | Mod | Save |\n| --- | --- | --- | --- |\n| Str | 12 | +1 | +1 |\n| Dex | 15 | +2 | +4 |\n| Con | 9 | −1 | −1 |\n"
        "| Int | 3 | −4 | −4 |\n| Wis | 12 | +1 | +3 |\n| Cha | 6 | −2 | −2 |\n\nGear Bell, Thieves’ Tools\n\nLanguages Common, Giant\n\n"
        "CR 10 (XP 5,900, or 7,200 in lair; PB +4)\n\nLegendary Action Uses: 3 (4 in Lair).\n")
    printed = book_load.printed(tmp_path)
    entry, _, _ = book_load.convert(ddb_beast(challengeRatingId=14, typeId=13, languages=[{"languageId": 1}], isLegendary=True, hasLair=True,
                                              legendaryActionsDescription="<p><strong>Blink.</strong> It moves.</p>"), printed)
    assert (entry["xp"], entry["xp_lair"], entry["cr"], entry["languages"], entry["size"]) == (5900, 7200, 10, "Common, Giant", "Huge")
    assert entry["legendary_actions"] == [{"name": "Blink", "text": "It moves."}] and entry["legendary_uses"].startswith("Legendary Action Uses: 3")
    assert (entry["initiative"], entry["hover"], entry["gear"], entry["tags"]) == (5, True, ["Bell", "Thieves' Tools"], ["Titan", "Demon"])


def test_a_stat_block_with_no_text_of_its_own_learns_its_languages_from_the_others():
    book_text = {"Hound": {"languages": "Common, Giant"}}
    data = [{"name": "Hound", "languages": [{"languageId": 1}, {"languageId": 2}]}]
    assert book_load.language_names(data, book_text) == {1: "Common", 2: "Giant"}
    entry, _, _ = book_load.convert(ddb_beast(languages=[{"languageId": 2}]), {}, {2: "Giant"})
    assert entry["languages"] == "Giant"
    with pytest.raises(book_load.Unconvertible):
        book_load.convert(ddb_beast(languages=[{"languageId": 3}]), {}, {2: "Giant"})  # never guess


def test_the_loader_writes_a_books_monsters_and_replaces_them_on_a_rerun(db, tmp_path, monkeypatch):
    import json

    from app import db as app_db

    data = tmp_path / "monsters-data.json"
    data.write_text(json.dumps([ddb_beast(), ddb_beast(name="Dusk Otter", sourcePageNumber=13), ddb_beast(name="Not a Beast", typeId=13)]))
    monkeypatch.setattr(app_db, "SessionLocal", lambda: _no_close(db))
    monkeypatch.setattr("sys.argv", ["book_load.py", "--file", str(data), "--yes"])
    book_load.main()
    assert sorted(db.scalars(BookEntry.__table__.select().with_only_columns(BookEntry.key))) == ["dusk-otter", "glimmer-hound", "not-a-beast"]
    data.write_text(json.dumps([ddb_beast()]))
    book_load.main()
    assert [r.key for r in db.query(BookEntry)] == ["glimmer-hound"]  # Dusk Otter left the file, so it left askdnd


class _no_close:
    """The test's session for the loader's `with SessionLocal() as db:` (commit inside the test's savepoint)."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_beta_gets_a_book_through_its_own_upload(admin, player, db):
    """Beta's database has no public address, so a book reaches it as a file uploaded on Manage › Backups and imports
    (scripts/book_load.py --export writes it): written as the loader writes, replacing the book's old entries."""
    import gzip
    import json

    from sqlalchemy import select

    old = books.save(db, "mm-2024", "monster", made_up_beast(name="Old Hound")).id
    db.commit()
    rows = [[made_up_beast(), 12, ""], [made_up_beast(name="Dusk Hound", hp=20), 13, ""]]
    packed = gzip.compress(json.dumps({"book": "mm-2024", "kind": "monster", "rows": rows}).encode())
    assert player.post("/manage/backups/books", files={"file": ("mm.json.gz", packed)}, follow_redirects=False).status_code in (302, 303, 403)
    assert db.scalar(select(BookEntry).where(BookEntry.key == "dusk-hound")) is None  # (not an admin: nothing written)

    r = admin.post("/manage/backups/books", files={"file": ("mm.json.gz", packed)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/manage/backups#books"
    db.expire_all()
    assert sorted(db.scalars(select(BookEntry.key).where(BookEntry.book == "mm-2024"))) == ["dusk-hound", "glimmer-hound"]
    assert db.get(BookEntry, old) is None  # (no longer in the file)
    page = admin.get("/manage/backups").text
    assert "Monster Manual" in page and "2 monsters" in page and "Upload book" in page

    bad = gzip.compress(json.dumps({"book": "mm-2024", "kind": "monster", "rows": [[{"name": "Nothing"}, 1, ""]]}).encode())
    admin.post("/manage/backups/books", files={"file": ("bad.json.gz", bad)})
    db.expire_all()
    assert len(db.scalars(select(BookEntry.key).where(BookEntry.book == "mm-2024")).all()) == 2  # nothing written when one doesn't fit
