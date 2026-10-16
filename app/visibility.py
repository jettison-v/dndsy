"""Who can see what. Everything is visible to everyone at the table, including
character notes (Brett, 2026-10-17: important context for the whole campaign).
The one exception, players' stars and reminders, lives in app/picks.py."""

from app.models import Role


def can_view_character_notes(role: Role | None) -> bool:
    return role in (Role.PLAYER, Role.DM)


def can_view_published_story(role: Role | None) -> bool:
    return role in (Role.PLAYER, Role.DM)
