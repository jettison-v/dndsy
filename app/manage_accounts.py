"""Manage › Accounts (admins, /manage/accounts): who can sign in to askdnd at all, who's an admin, and which
campaigns each person is in (Manage layout, 2026-10-23). Roles in a campaign are set on that campaign's Table
(app/manage_table.py)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import view_as
from app import access, config, web
from app.auth import is_admin
from app.db import get_db
from app.models import Campaign, User
from app.templating import templates

router = APIRouter(prefix="/manage/accounts")
DENIED = "Accounts are for admins."
BACK = "/manage/accounts"


def accounts(db: Session) -> list[dict]:
    """Everyone with an account, plus emails only in the Railway lists, with their campaigns and roles."""
    rows = access.rows_from(db)
    users = {u.email.lower(): u for u in db.scalars(select(User))}
    campaigns = list(db.scalars(select(Campaign).order_by(Campaign.id)))
    out = []
    for email in set(users) | config.ALLOWED_EMAILS | config.REVIEWER_EMAILS | config.ADMIN_EMAILS:
        u = users.get(email)
        lvl = access.level(email, rows)
        stored = u.access if u else None
        out.append({
            "user": u, "email": email, "name": u.name if u and u.name != email else "", "level": lvl,
            "owner": access.is_owner(email), "from_railway": stored is None and lvl is not None,
            "removed": stored == access.REMOVED, "invited": lvl is not None, "last_seen": u.last_seen_at if u else None,
            "campaigns": [(c, r) for c in campaigns if (r := access.role(email, c.id, rows))],
        })
    return sorted(out, key=lambda p: (p["name"].lower() or p["email"]))


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    everyone = accounts(db)
    return templates.TemplateResponse(request, "manage_accounts.html", {
        "people": [p for p in everyone if p["invited"]], "away": [p for p in everyone if not p["invited"]],
        "role_labels": access.ROLE_LABELS, "me": user["email"].lower(), "toast": request.session.pop("toast", None),
        "can_view": {p["email"] for p in everyone if not view_as.refusal(user["email"], p["email"])}})


def _save(db: Session, email: str, tool: str, name: str = "") -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name or email)
        db.add(u)
    elif name:
        u.name = name
    u.access = tool
    db.flush()
    access.invalidate()
    return u


@router.post("")
def add(request: Request, email: str = Form(...), name: str = Form(""), admin: str = Form(""), db: Session = Depends(get_db)):
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    email = email.strip().lower()
    if "@" not in email:
        request.session["toast"] = "Enter an email address."
    else:
        _save(db, email, access.ADMIN if admin else access.MEMBER, " ".join(name.split())[:200])
        db.commit()
        request.session["toast"] = f"Added {email}. Add them as a Google test user too (see below), then to a campaign on its Table."
    return RedirectResponse(BACK, status_code=303)


@router.post("/update")
def update(request: Request, email: str = Form(...), admin: str = Form(""), remove: str = Form(""),
           db: Session = Depends(get_db)):
    """The Admin flag, removing someone (they can't sign in; their campaign roles stay, for coming back), or inviting
    someone back."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    email = email.strip().lower()
    mine = access.is_owner(email) or email == user["email"].lower()
    tool = access.REMOVED if remove else access.ADMIN if (admin or mine) else access.MEMBER
    if access.is_owner(email) and tool != access.ADMIN:
        request.session["toast"] = "Owners are set on Railway (ADMIN_EMAILS) and are always admins."
    elif email == user["email"].lower() and tool != access.ADMIN:
        request.session["toast"] = "You can't lower your own access."
    else:
        _save(db, email, tool)
        db.commit()
        request.session["toast"] = "Removed" if tool == access.REMOVED else "Saved"
    return RedirectResponse(BACK, status_code=303)
