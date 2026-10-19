"""Manage › People (admins): who can sign in and what they can do (app/access.py)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, config
from app.admin import _guard
from app.db import get_db
from app.models import Character, User
from app.templating import templates

router = APIRouter(prefix="/admin/people")


def people(db: Session) -> list[dict]:
    """Everyone with a user row, plus emails only in the Railway lists."""
    rows = access.rows_from(db)
    users = {u.email.lower(): u for u in db.scalars(select(User))}
    emails = set(users) | config.ALLOWED_EMAILS | config.REVIEWER_EMAILS | config.ADMIN_EMAILS
    out = []
    for email in emails:
        u = users.get(email)
        lvl = access.level(email, rows)
        stored = u.access if u else None
        out.append({
            "user": u,
            "email": email,
            "name": u.name if u and u.name != email else "",
            "level": lvl,
            "stored": stored,
            "owner": access.is_owner(email),
            "from_railway": stored is None and lvl is not None,
            "removed": stored == access.REMOVED,
            "invited": lvl is not None,
            "is_dm": (rows.get(email) or {}).get("is_dm", False),
            "last_seen": u.last_seen_at if u else None,
        })
    owned = {}
    for ch in db.scalars(select(Character).where(Character.owner_id.is_not(None))):
        owned.setdefault(ch.owner_id, ch.id)
    for p in out:
        p["character_id"] = owned.get(p["user"].id) if p["user"] else None
    order = {access.ADMIN: 0, access.REVIEWER: 1, access.PLAYER: 2, None: 3}
    return sorted(out, key=lambda p: (order[p["level"]], p["name"].lower() or p["email"]))


@router.get("")
def people_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    return templates.TemplateResponse(
        request, "admin_people.html",
        {"people": people(db), "characters": list(db.scalars(select(Character).order_by(Character.id))), "levels": access.LEVELS, "labels": access.LABELS, "me": user["email"],
         "chart": access.chart(),
         "summaries": {f"{lv}|{int(dm)}": access.summary(lv, dm) for lv in access.LEVELS for dm in (False, True)},
         "toast": request.session.pop("toast", None)},
    )


def assign_character(db: Session, email: str, character_id: int | None) -> None:
    """Who plays which character: their stars and reminders are theirs to set."""
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=email)
        db.add(u)
        db.flush()
    for ch in db.scalars(select(Character).where(Character.owner_id == u.id)):
        if ch.id != character_id:
            ch.owner_id = None
    if character_id:
        ch = db.get(Character, character_id)
        if ch:
            ch.owner_id = u.id
    db.flush()


def _save(db: Session, email: str, level: str, is_dm: bool, name: str = "") -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name or email)
        db.add(u)
    elif name:
        u.name = name
    u.access, u.is_dm = level, is_dm
    db.flush()
    access.invalidate()
    return u


@router.post("")
def add_person(request: Request, email: str = Form(...), name: str = Form(""), level: str = Form(access.PLAYER),
               is_dm: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    email = email.strip().lower()
    if "@" not in email or level not in access.LEVELS:
        request.session["toast"] = "Enter an email address and an access level."
    else:
        _save(db, email, level, bool(is_dm), name.strip())
        db.commit()
        request.session["toast"] = f"Added {email}. Add them as a Google test user too (see below)."
    return RedirectResponse("/admin/people", status_code=303)


@router.post("/update")
def update_person(request: Request, email: str = Form(...), level: str = Form(""), is_dm: str = Form(""),
                  remove: str = Form(""), character_id: str = Form("keep"), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    email = email.strip().lower()
    if remove:
        level = access.REMOVED
    if character_id != "keep" and not remove:
        assign_character(db, email, int(character_id) if character_id.isdigit() else None)
        db.commit()
    if access.is_owner(email) or email == user["email"].lower():
        level = level or access.ADMIN  # their own row only has the character picker
    if access.is_owner(email) and level != access.ADMIN:
        request.session["toast"] = "Owners are set on Railway (ADMIN_EMAILS) and are always admins."
    elif email == user["email"].lower() and level != access.ADMIN:
        request.session["toast"] = "You can't lower your own access."
    elif level not in access.LEVELS + [access.REMOVED]:
        request.session["toast"] = "Pick an access level."
    else:
        _save(db, email, level, bool(is_dm))
        db.commit()
        request.session["toast"] = "Removed" if level == access.REMOVED else "Saved"
    return RedirectResponse("/admin/people", status_code=303)
