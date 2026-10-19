"""Manage › History: every recorded change, with Restore; and Undo for an import.

Who sees what: reviewers and admins see story changes (entries, glossary,
sessions, campaign). Characters and People changes are admins only. Players'
notes appear only for people who may read player notes (never the DM).
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import history, picks
from app.admin import _guard
from app.auth import can_see_character_notes, is_admin, is_reviewer
from app.db import get_db
from app.models import Character, Revision
from app.templating import templates

router = APIRouter(prefix="/admin/history")

STORY = ("entities", "glossary_terms", "game_sessions", "campaigns")
ADMIN_ONLY = ("characters", "users")
NOTES = ("player_notes", "character_picks")
FILTERS = {"": ("Everything", None), "entries": ("Entries", ("entities",)), "glossary": ("Glossary", ("glossary_terms",)),
           "sessions": ("Sessions", ("game_sessions",)), "characters": ("Characters", ("characters",)),
           "notes": ("Player notes", NOTES), "people": ("People", ("users",)), "campaign": ("Campaign", ("campaigns",))}


def visible_tables(user: dict) -> tuple[str, ...]:
    tables = STORY + (ADMIN_ONLY if is_admin(user) else ()) + (NOTES if can_see_character_notes(user) else ())
    return tables


def may_restore(db: Session, user: dict, rev: Revision) -> bool:
    if rev.table in STORY:
        return is_reviewer(user)
    if rev.table in ADMIN_ONLY:
        return is_admin(user)
    if rev.table in NOTES:
        ch = db.get(Character, rev.character_id) if rev.character_id else None
        return can_see_character_notes(user) and (is_admin(user) or (ch is not None and picks.can_edit(db, user, ch)))
    return False


def recent_imports(db: Session, limit: int = 10) -> list[dict]:
    """Imports recorded in history, newest first, for Manage › Data."""
    rows = db.scalars(select(Revision).where(Revision.source == "import", Revision.batch.is_not(None))
                      .order_by(Revision.id.desc()).limit(5000))
    batches: dict[str, dict] = {}
    for r in rows:
        b = batches.setdefault(r.batch, {"batch": r.batch, "at": r.created_at, "actor": r.actor, "changes": 0, "things": set()})
        b["changes"] += 1
        b["things"].add(r.label)
    out = sorted(batches.values(), key=lambda b: b["at"], reverse=True)[:limit]
    for b in out:
        b["things"] = len(b["things"])
    return out


@router.get("")
def history_page(request: Request, show: str = "", table: str = "", row: int | None = None, batch: str = "",
                 db: Session = Depends(get_db)):
    user, denied = _guard(request, allow=is_reviewer)
    if denied:
        return denied
    allowed = visible_tables(user)
    tables = FILTERS.get(show, FILTERS[""])[1] or allowed
    q = select(Revision).where(Revision.table.in_([t for t in tables if t in allowed]))
    if table and row is not None:
        q = q.where(Revision.table == table, Revision.row_id == row)
    if batch:
        q = q.where(Revision.batch == batch)
    revs = list(db.scalars(q.order_by(Revision.id.desc()).limit(300)))
    days: dict[str, list] = defaultdict(list)
    for r in revs:
        days[r.created_at.strftime("%A %-d %B %Y")].append({
            "r": r, "field": history.FIELD_LABELS.get(r.field, r.field), "source": history.SOURCES.get(r.source, r.source),
            "old": history.shown(r.old, r.field), "new": history.shown(r.new, r.field),
            "long": r.field in ("summary", "description", "data", "note", "deleted"),
            "restorable": may_restore(db, user, r) and history.can_restore(db, r)})
    return templates.TemplateResponse(request, "admin_history.html", {
        "days": list(days.items()), "show": show, "filters": {k: v[0] for k, v in FILTERS.items() if not v[1] or set(v[1]) & set(allowed)},
        "focus": revs[0].label if (table and row is not None and revs) else "", "batch": batch,
        "toast": request.session.pop("toast", None)})


@router.post("/{rev_id:int}/restore")
def restore(request: Request, rev_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request, allow=is_reviewer)
    if denied:
        return denied
    rev = db.get(Revision, rev_id)
    if rev is None or rev.table not in visible_tables(user) or not may_restore(db, user, rev) or not history.can_restore(db, rev):
        request.session["toast"] = "That can't be restored."
    else:
        request.session["toast"] = history.restore(db, rev)
        db.commit()
    return RedirectResponse(request.headers.get("referer") or "/admin/history", status_code=303)


@router.post("/undo-import")
def undo_import(request: Request, batch: str = Form(...), db: Session = Depends(get_db)):
    user, denied = _guard(request)  # admins
    if denied:
        return denied
    done, skipped = history.undo_import(db, batch)
    db.commit()
    request.session["toast"] = f"Import undone: {done} change{'s' if done != 1 else ''} put back" + (
        f", {skipped} left alone (changed again since)" if skipped else "")
    return RedirectResponse("/admin/import", status_code=303)
