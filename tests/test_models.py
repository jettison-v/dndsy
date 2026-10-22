import subprocess

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import characters
from app.config import sqlalchemy_url
from app.models import (
    Campaign,
    CampaignMember,
    Character,
    Entity,
    EntityAlias,
    EntityKind,
    Role,
    User,
)
from app.visibility import can_view_character_notes, can_view_published_story


def test_sqlalchemy_url_uses_psycopg():
    assert sqlalchemy_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert sqlalchemy_url("postgres://h/db") == "postgresql+psycopg://h/db"
    assert sqlalchemy_url("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"
    assert sqlalchemy_url(None) == ""


def test_character_notes_hidden_from_dm():
    assert can_view_character_notes(Role.PLAYER)
    assert not can_view_character_notes(Role.DM)
    assert not can_view_character_notes(None)


def test_published_story_visible_to_whole_table():
    assert can_view_published_story(Role.PLAYER)
    assert can_view_published_story(Role.DM)
    assert not can_view_published_story(None)


def make_campaign(db):
    campaign = Campaign(name="Test Campaign", slug="test")
    db.add(campaign)
    db.flush()
    return campaign


def test_renamed_character_found_by_old_name(db):
    campaign = make_campaign(db)
    player = User(email="player@example.com", name="Player")
    pc = Entity(campaign_id=campaign.id, kind=EntityKind.PC, name="No Name")
    pc.aliases.append(EntityAlias(alias="Sarkas", note="former name"))
    db.add_all([player, pc])
    db.flush()
    ch = Character(name=pc.name, owner_id=player.id)
    db.add(ch)
    characters.join(db, ch, pc)

    found = db.scalars(
        select(Entity).join(EntityAlias).where(EntityAlias.alias == "Sarkas")
    ).one()
    assert found.name == "No Name"


def test_role_is_per_campaign(db):
    one, two = Campaign(name="One", slug="one"), Campaign(name="Two", slug="two")
    user = User(email="dm@example.com", name="DM")
    db.add_all([one, two, user])
    db.flush()
    db.add_all([
        CampaignMember(campaign_id=one.id, user_id=user.id, role=Role.DM),
        CampaignMember(campaign_id=two.id, user_id=user.id, role=Role.PLAYER),
    ])
    db.flush()
    roles = {m.campaign.slug: m.role for m in db.scalars(select(CampaignMember))}
    assert roles == {"one": Role.DM, "two": Role.PLAYER}


def test_user_email_unique(db):
    db.add_all([User(email="a@example.com", name="A"), User(email="a@example.com", name="B")])
    with pytest.raises(IntegrityError):
        db.flush()


def test_migrations_match_models(db_engine):
    """Fails if someone changes app/models.py without adding a migration."""
    url = db_engine.url.render_as_string(hide_password=False)
    env = {"DATABASE_URL": url, "PATH": __import__("os").environ["PATH"]}
    from app.db import Base

    Base.metadata.drop_all(db_engine)
    try:
        up = subprocess.run(["alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr
        check = subprocess.run(["alembic", "check"], env=env, capture_output=True, text=True)
        assert check.returncode == 0, check.stdout + check.stderr
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)
