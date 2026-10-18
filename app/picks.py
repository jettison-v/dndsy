"""Stars and reminders a player puts on their own character.

- A star shows the thing (action, spell, item, feature…) on the Battle page.
- A reminder lists it under "Easy to forget".
- A heart puts a spell or Wild Shape form on the player's shortlist.
- Shortlist picks and reminders can carry a short note: why it's there.

Rules (Brett, 2026-10-16): only the character's player can set them (not
admins, not the DM). Like character notes, they're visible to the players but
never to the DM.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import can_see_character_notes
from app.models import Character, CharacterPick, User

KINDS = ("star", "remind", "fav")  # fav: a spell or Wild Shape form on the player's shortlist
NOTE_KINDS = ("fav", "remind")
NOTE_MAX = 500


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
    """{"star": {ref,…}, "remind": {ref: label}, "notes": {"fav|ref": note}…} — empty for the DM."""
    out = {"star": set(), "remind": {}, "fav": set(), "order": {}, "notes": {}}
    if not can_see(user):
        return out
    for p in db.scalars(select(CharacterPick).where(CharacterPick.character_id == character.id).order_by(CharacterPick.id)):
        if p.note and p.kind in NOTE_KINDS:
            out["notes"][f"{p.kind}|{p.ref}"] = p.note
        if p.kind in ("star", "fav"):
            out[p.kind].add(p.ref)
        elif p.kind == "remind":
            out["remind"][p.ref] = p.label
        elif p.kind == "order":
            try:
                out["order"][p.ref.removeprefix("order:")] = json.loads(p.label)
            except ValueError:
                pass
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


def set_note(db: Session, character: Character, kind: str, ref: str, note: str) -> bool:
    """The player's note on a shortlist pick or reminder. False if that pick isn't on."""
    if kind not in NOTE_KINDS:
        raise ValueError("notes are for the shortlist and reminders")
    pick = db.scalar(select(CharacterPick).where(
        CharacterPick.character_id == character.id, CharacterPick.kind == kind, CharacterPick.ref == ref[:300]))
    if not pick:
        return False
    pick.note = note.strip()[:NOTE_MAX]
    db.flush()
    return True


def set_order(db: Session, character: Character, column: str, keys: list[str]) -> None:
    """The player's own order for a Battle column (drag and drop)."""
    ref = f"order:{column}"
    pick = db.scalar(select(CharacterPick).where(
        CharacterPick.character_id == character.id, CharacterPick.kind == "order", CharacterPick.ref == ref))
    label = json.dumps([k[:300] for k in keys][:60])
    if len(label) > 500:  # keep within the column; the first options matter most
        keys = keys[:]
        while keys and len(json.dumps(keys)) > 500:
            keys.pop()
        label = json.dumps(keys)
    if pick:
        pick.label = label
    else:
        db.add(CharacterPick(character_id=character.id, kind="order", ref=ref, label=label))
    db.flush()
