"""Manage › Table as one list (Brett, 2026-10-30, docs/mockups/the-table.html): one Add for a person, a character or both,
what each row does, and a Remove that never deletes: Left the table brings them back."""

import pytest
from sqlalchemy import select

from app import access, characters
from app.importer import import_bundle
from app.models import CampaignCharacter, CampaignMember, Character, Entity, User
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by

TABLE = "/c/main/manage/table"


@pytest.fixture(autouse=True)
def the_table(db):
    import_bundle(db, BUNDLE)


def test_a_person_and_their_character_are_one_row(admin, db):
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    set_role(db, "player@example.com", "player")
    page = admin.get(TABLE).text
    row = next(x for x in page.split('<details class="seat">') if "<b>Cole" in x)
    assert "player@example.com" in row and "Remove from the table" in row and "Remove Cole" in row


def test_one_add_does_a_person_and_their_character_together(admin, db):
    r = admin.post(f"{TABLE}/add", data={"new_email": "nia@example.com", "name": "Nia", "role": "player", "char_name": "Enemy 1"})
    assert r.status_code in (200, 303)
    ch = db.scalar(select(Character).where(Character.name == "Enemy 1"))
    assert ch.owner.email == "nia@example.com" and access.role("nia@example.com", ch.campaign_id) == "player"
    admin.post(f"{TABLE}/add", data={"char_name": "Enemy 2"})  # just a character
    assert db.scalar(select(Character).where(Character.name == "Enemy 2")).owner_id is None


def test_a_character_added_by_its_link_takes_its_name_from_the_sheet(admin, db, monkeypatch):
    from tests.table_setup import COLE

    monkeypatch.setattr(characters, "FETCH", lambda _id: COLE)
    admin.post(f"{TABLE}/add", data={"ddb_link": "https://www.dndbeyond.com/characters/12345678"})
    ch = db.scalar(select(Character).where(Character.ddb_id == "12345678"))
    assert ch.name == "Cole Lockhard" and ch.membership.entity.name == "Cole Lockhard"


def test_adding_needs_someone_or_a_character(admin, db):
    before = len(db.scalars(select(Character)).all())
    admin.post(f"{TABLE}/add", data={})
    assert len(db.scalars(select(Character)).all()) == before


def test_what_someone_plays_changes_from_their_row_one_per_person(admin, db):
    cole, trah = char(db, "Cole"), char(db, "Trah")
    set_role(db, "player@example.com", "player")
    me = db.scalar(select(User).where(User.email == "player@example.com"))
    admin.post(f"{TABLE}/plays", data={"email": me.email, "character_id": cole.id})
    assert cole.owner_id == me.id
    admin.post(f"{TABLE}/plays", data={"email": me.email, "character_id": trah.id})
    db.expire_all()
    assert trah.owner_id == me.id and cole.owner_id is None
    admin.post(f"{TABLE}/plays", data={"email": me.email, "character_id": ""})
    db.expire_all()
    assert trah.owner_id is None


def test_removing_a_character_deletes_nothing_and_it_comes_back(admin, db):
    """Brett, 2026-10-30: nothing is ever deleted; its story, rolls and notes stay."""
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    campaign, entity = cole.campaign_id, cole.membership.entity_id
    admin.post(f"{TABLE}/characters/{cole.id}/remove")
    db.expire_all()
    assert cole.campaign_id is None and cole.owner_id is None and db.get(Entity, entity) is not None
    page = admin.get(TABLE).text
    left = page.split("Left the table")[1]
    assert "<b>Cole</b>" in left and "Bring back" in left and "<b>Cole</b>" not in page.split("Left the table")[0]
    admin.post(f"{TABLE}/characters/{cole.id}/back")
    db.expire_all()
    assert cole.campaign_id == campaign and cole.membership.entity_id == entity  # its own story page
    assert "Left the table" not in admin.get(TABLE).text


def test_removing_a_person_leaves_their_character_at_the_table_and_they_come_back_in_their_role(admin, db):
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    set_role(db, "player@example.com", "reviewer")
    admin.post(f"{TABLE}/people", data={"email": "player@example.com", "role": "none"})
    db.expire_all()
    assert access.role("player@example.com", cole.campaign_id) is None and cole.campaign_id is not None and cole.owner_id is None
    assert db.scalar(select(User).where(User.email == "player@example.com")) is not None  # their account stays
    left = admin.get(TABLE).text.split("Left the table")[1]
    assert "player@example.com" in left and 'value="reviewer"' in left
    admin.post(f"{TABLE}/people/back", data={"email": "player@example.com", "role": "reviewer"})
    assert access.role("player@example.com", cole.campaign_id) == "reviewer"
    assert len(db.scalars(select(CampaignMember).join(User).where(User.email == "player@example.com")).all()) == 2  # the old row stays


def test_a_character_moved_to_another_campaign_didnt_leave_the_table(admin, db):
    from app.models import Campaign

    cole = char(db, "Cole")
    other = Campaign(name="Elsewhere", slug="elsewhere")
    db.add(other)
    db.commit()
    page = admin.get(TABLE).text
    assert f'action="/manage/campaigns/characters/{cole.id}/move"' in page and "Elsewhere" in page
    r = admin.post(f"/manage/campaigns/characters/{cole.id}/move", data={"campaign_id": other.id, "back": TABLE}, follow_redirects=False)
    assert r.headers["location"] == TABLE
    assert "Left the table" not in admin.get(TABLE).text
    assert len(db.scalars(select(CampaignCharacter).where(CampaignCharacter.character_id == cole.id)).all()) == 2


def test_only_the_dm_and_admins_change_the_table(player, db):
    """A standing rule (app/access.py): a player can't change who's at the table."""
    cole = char(db, "Cole")
    assert player.post(f"{TABLE}/characters/{cole.id}/remove").status_code == 403
    assert player.post(f"{TABLE}/plays", data={"email": "player@example.com", "character_id": cole.id}).status_code == 403
    db.expire_all()
    assert cole.campaign_id is not None


def test_a_test_copy_that_left_comes_back_instead_of_a_second_one(admin, db):
    from app.models import Campaign

    cole = char(db, "Cole")
    lab = Campaign(name="Lab", slug="lab", is_test=True)
    db.add(lab)
    db.commit()
    admin.post("/c/lab/manage/table/test-copies", data={"character_ids": [cole.id]})
    copy = db.scalar(select(Character).where(Character.copy_of_id == cole.id))
    admin.post(f"/c/lab/manage/table/characters/{copy.id}/remove")
    admin.post("/c/lab/manage/table/test-copies", data={"character_ids": [cole.id]})
    db.expire_all()
    assert len(db.scalars(select(Character).where(Character.copy_of_id == cole.id)).all()) == 1 and copy.campaign_id == lab.id


def test_campaign_lists_skip_who_left(admin, db):
    cole = char(db, "Cole")
    campaign = cole.campaign_id
    admin.post(f"{TABLE}/characters/{cole.id}/remove")
    db.expire_all()
    assert cole not in characters.campaign_characters(db, campaign)
