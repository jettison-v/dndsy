"""Stars and reminders a player puts on their own character.

- A star shows the thing (action, spell, item, feature…) on the Battle page.
- A reminder lists it under "Easy to forget".

Rules (Brett, 2026-10-16): only the character's player can set them (not
admins, not the DM). Like character notes, they're visible to the players but
never to the DM.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import can_see_character_notes
from app.models import Character, CharacterPick, User

KINDS = ("star", "remind")


def user_row(db: Session, user: dict | None) -> User | None:
    email = (user or {}).get("email", "").lower()
    return db.scalar(select(User).where(User.email == email)) if email else None


def my_character(db: Session, user: dict | None) -> Character | None:
    """The character the signed-in person plays (set on Manage › People)."""
    me = user_row(db, user)
    return db.scalar(select(Character).where(Character.owner_id == me.id).order_by(Character.id)) if me else None


def can_edit(db: Session, user: dict | None, character: Character) -> bool:
    me = user_row(db, user)
    return bool(me and character.owner_id == me.id)


def can_see(user: dict | None) -> bool:
    return can_see_character_notes(user)


def picks(db: Session, character: Character, user: dict | None) -> dict:
    """{"star": {ref,…}, "remind": {ref: label}} — empty for the DM."""
    out = {"star": set(), "remind": {}}
    if not can_see(user):
        return out
    for p in db.scalars(select(CharacterPick).where(CharacterPick.character_id == character.id).order_by(CharacterPick.id)):
        if p.kind == "star":
            out["star"].add(p.ref)
        elif p.kind == "remind":
            out["remind"][p.ref] = p.label
    return out


def toggle(db: Session, character: Character, kind: str, ref: str, label: str = "") -> bool:
    """Turn a star or reminder on or off. Returns the new state."""
    if kind not in KINDS or not ref:
        raise ValueError("unknown pick")
    pick = db.scalar(select(CharacterPick).where(
        CharacterPick.character_id == character.id, CharacterPick.kind == kind, CharacterPick.ref == ref[:300]))
    if pick:
        db.delete(pick)
        db.flush()
        return False
    db.add(CharacterPick(character_id=character.id, kind=kind, ref=ref[:300], label=label[:500]))
    db.flush()
    return True
