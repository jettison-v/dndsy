"""Manage › History: every recorded change, with Restore; and Undo for an import.

Two views of the same records (Manage layout, 2026-10-23):
- the campaign's History (/c/<campaign>/manage/history): only that campaign's changes;
- askdnd's History (/manage/history, admins): changes that belong to no campaign (accounts, a character in none),
  or one import's changes in every campaign.

Who sees what: reviewers and admins see story changes (entries, glossary,
sessions, campaign). Characters and People changes are admins only. Players'
notes appear only for people who may read player notes (never the DM).
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, history, house_rules, picks, web
from app import character_views as views
from app import characters as chars
from app import roll_recipes as rr
from app.admin import _guard
from app.auth import can_see_character_notes, can_set_house_rules, is_admin, is_reviewer
from app.db import get_db
from app.models import CampaignCharacter, Character, Revision, User
from app.templating import templates

router = APIRouter(prefix="/manage/history")

STORY = ("entities", "glossary_terms", "game_sessions", "campaigns", "story_events", "entity_aliases", "relationships", "facts")
ADMIN_ONLY = ("characters", "campaign_characters", "users", "campaign_members")
NOTES = ("player_notes", "character_picks")
HOUSE = ("house_rules",)
FILTERS = {"": ("Everything", None), "entries": ("Entries", ("entities", "entity_aliases", "relationships", "facts")),
           "moments": ("Key moments", ("story_events",)), "glossary": ("Glossary", ("glossary_terms",)),
           "sessions": ("Sessions", ("game_sessions",)), "characters": ("Characters", ("characters", "campaign_characters")),
           "notes": ("Player notes", NOTES), "people": ("People", ("users", "campaign_members")), "campaign": ("Campaign", ("campaigns",)),
           "house": ("House rules", HOUSE)}


def visible_tables(user: dict) -> tuple[str, ...]:
    tables = STORY + HOUSE + (ADMIN_ONLY if is_admin(user) else ()) + (NOTES if can_see_character_notes(user) else ())
    return tables


def may_restore(db: Session, user: dict, rev: Revision) -> bool:
    if rev.table in STORY:
        return is_reviewer(user)
    if rev.table in HOUSE:
        return can_set_house_rules(user)
    if rev.table in ADMIN_ONLY:
        return is_admin(user)
    if rev.table in NOTES:
        ch = db.get(Character, rev.character_id) if rev.character_id else None
        return can_see_character_notes(user) and (is_admin(user) or (ch is not None and picks.can_edit(db, user, ch)))
    return False


def recent_imports(db: Session, limit: int = 10) -> list[dict]:
    """Imports recorded in history, newest first, for Manage › Backups and imports."""
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


PAGE = 300  # changes shown at once


def _matching(db: Session, q, keep) -> list[Revision]:
    """The newest PAGE changes from `q` that `keep(revision, campaign id)` accepts (read in chunks)."""
    out: list[Revision] = []
    last = None
    while len(out) < PAGE:
        chunk = list(db.scalars((q.where(Revision.id < last) if last else q).order_by(Revision.id.desc()).limit(1000)))
        if not chunk:
            break
        where = history.campaigns_of(db, chunk)
        out += [r for r in chunk if keep(r, where[r.id])]
        last = chunk[-1].id
    return out[:PAGE]


def _present(db: Session, r: Revision, people: dict[int, str]) -> dict:
    """A change in words people recognize (Brett, 2026-10-23): who plays a character by name, not account number;
    Wild Shape keeps by item name, as what was added or removed; a removed house rule as the ruling it was."""
    if r.field == "owner_id":
        name = lambda v: people.get(v, ("someone", ""))[0] if v else "Nobody"  # noqa: E731
        old, new = name(r.old), name(r.new)
        if old == new and r.old and r.new:  # two accounts with one name (an old and a new sign-in): say which
            old, new = f"{old} ({people[r.old][1]})", f"{new} ({people[r.new][1]})"
        return {"old": old, "new": new}
    if r.field == "wild_shape_keep":
        cc = db.get(CampaignCharacter, r.row_id)
        sheet = chars.character_summary(cc.character) if cc and cc.character else None
        label = lambda ref: ((views.find(sheet, ref) or {}).get("name") if sheet else None) or ref.split(":", 1)[-1].replace("-", " ").capitalize()  # noqa: E731
        before, after = set(r.old or []), set(r.new or [])
        bits = [f"Added {', '.join(sorted(label(x) for x in after - before))}" if after - before else "",
                f"removed {', '.join(sorted(label(x) for x in before - after))}" if before - after else ""]
        text = "; ".join(b for b in bits if b)
        return {"change": (text[:1].upper() + text[1:]) if text else "No change"}
    if r.table == "house_rules" and r.field == "deleted" and isinstance(r.old, dict):
        o = r.old
        text = house_rules.describe(o.get("field", ""), o.get("value", ""), rr.spell(o.get("target_key", "")))
        return {"old": f"{o.get('target_key', '')}: {text}" + (f" ({o['reason']})" if o.get("reason") else "")}
    return {"old": history.shown(r.old, r.field), "new": history.shown(r.new, r.field)}


@router.get("")
def history_page(request: Request, show: str = "", table: str = "", row: int | None = None, batch: str = "",
                 db: Session = Depends(get_db)):
    in_campaign = access.path_slug.get() is not None
    user, denied = _guard(request, allow=is_reviewer if in_campaign else is_admin)
    if denied:
        return denied
    campaign = web.campaign(db) if in_campaign else None
    allowed = visible_tables(user)
    tables = FILTERS.get(show, FILTERS[""])[1] or allowed
    q = select(Revision).where(Revision.table.in_([t for t in tables if t in allowed]))
    if table and row is not None:
        q = q.where(Revision.table == table, Revision.row_id == row)
    if batch:
        q = q.where(Revision.batch == batch)
    if in_campaign:
        revs = _matching(db, q, lambda r, c: campaign is not None and c == campaign.id)
    elif batch:
        revs = _matching(db, q, lambda r, c: True)  # one import, in every campaign
    else:
        revs = _matching(db, q, lambda r, c: c is None)
    days: dict[str, list] = defaultdict(list)
    people = {u.id: (u.name if u.name and u.name != u.email else u.email, u.email) for u in db.scalars(select(User))}
    for r in revs:
        days[r.created_at.strftime("%A %-d %B %Y")].append({
            "r": r, "field": history.FIELD_LABELS.get(r.field, r.field), "source": history.SOURCES.get(r.source, r.source),
            **_present(db, r, people),
            "long": r.field in ("summary", "description", "data", "note", "deleted"),
            "restorable": may_restore(db, user, r) and history.can_restore(db, r)})
    shown_filters = ({k: v[0] for k, v in FILTERS.items() if not v[1] or set(v[1]) & set(allowed)} if in_campaign
                     else {k: FILTERS[k][0] for k in ("", "people", "characters")})
    return templates.TemplateResponse(request, "admin_history.html", {
        "days": list(days.items()), "show": show, "filters": shown_filters, "in_campaign": in_campaign, "campaign": campaign,
        "page_url": f"{web.base()}/manage/history" if in_campaign else "/manage/history",  # not "here": every page already has that (the campaign)
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
    return RedirectResponse(request.headers.get("referer") or f"{web.base()}/manage/history", status_code=303)


@router.post("/undo-import")
def undo_import(request: Request, batch: str = Form(...), db: Session = Depends(get_db)):
    user, denied = _guard(request)  # admins
    if denied:
        return denied
    done, skipped = history.undo_import(db, batch)
    db.commit()
    request.session["toast"] = f"Import undone: {done} change{'s' if done != 1 else ''} put back" + (
        f", {skipped} left alone (changed again since)" if skipped else "")
    return RedirectResponse("/manage/backups", status_code=303)
