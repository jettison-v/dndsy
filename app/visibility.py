"""Who can see what. Rule (CLAUDE.md): character notes are visible to players
but NOT the DM. Everything else is visible to everyone at the table."""

from app.models import Role


def can_view_character_notes(role: Role | None) -> bool:
    return role in (Role.PLAYER, Role.REVIEWER)


def can_view_published_story(role: Role | None) -> bool:
    return role in (Role.PLAYER, Role.REVIEWER, Role.DM)
