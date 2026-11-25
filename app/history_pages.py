"""Backstage › History: every recorded change, with Restore; and Undo for an import.

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
    """Imports recorded in history, newest first, for Backstage › Backups and imports."""
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
        name = lambda v: people.get(v, ("someone", ""))[0] if v else "Nobody"
        old, new = name(r.old), name(r.new)
        if old == new and r.old and r.new:  # two accounts with one name (an old and a new sign-in): say which
            old, new = f"{old} ({people[r.old][1]})", f"{new} ({people[r.new][1]})"
        return {"old": old, "new": new}
    if r.field == "wild_shape_keep":
        cc = db.get(CampaignCharacter, r.row_id)
        sheet = chars.character_summary(cc.character) if cc and cc.character else None
        label = lambda ref: ((views.find(sheet, ref) or {}).get("name") if sheet else None) or ref.split(":", 1)[-1].replace("-", " ").capitalize()
        before, after = set(r.old or []), set(r.new or [])
        bits = [f"Added {', '.join(sorted(label(x) for x in after - before))}" if after - before else "",
                f"removed {', '.join(sorted(label(x) for x in before - after))}" if before - after else ""]
        text = "; ".join(b for b in bits if b)
        return {"change": (text[:1].upper() + text[1:]) if text else "No change"}
    if r.table == "house_rules" and r.field == "deleted" and isinstance(r.old, dict):
        o = r.old
        text = house_rules.describe(o.get("field", ""), o.get("value", ""), rr.spell(o.get("target_key", "")))
        return {"old": f"{o.get('target_key', '')}: {text}" + (f" ({o['reason']})" if o.get("reason") else "")}
    if r.field == "deleted" and isinstance(r.old, dict):  # (what was deleted, by its name or words, not its fields: HI1)
        o = r.old
        said = next((str(o[k]) for k in ("name", "title", "term", "text", "summary", "value", "label") if o.get(k)), "")
        return {"old": " ".join(said.split())[:300] or "Something with no name"}
    return {"old": history.shown(r.old, r.field), "new": history.shown(r.new, r.field)}


@router.get("")
def history_page(request: Request, show: str = "", table: str = "", row: int | None = None, batch: str = "", older: int = 0,
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
    people = {u.id: (u.name if u.name and u.name != u.email else u.email, u.email) for u in db.scalars(select(User))}
    known = history.targets(db, revs)
    items = [_item(db, user, r, people, known) for r in revs]
    entries = group_changes(items)
    days: dict[str, list] = defaultdict(list)
    for e in entries:
        days[e["at"].strftime("%b %-d, %Y")].append(e)  # (dates one way, "Nov 5, 2026": the UI review)
    every = list(days.items())
    shown = every if older else every[:DAYS_SHOWN]
    shown_filters = ({k: v[0] for k, v in FILTERS.items() if not v[1] or set(v[1]) & set(allowed)} if in_campaign
                     else {k: FILTERS[k][0] for k in ("", "people", "characters")})
    return templates.TemplateResponse(request, "admin_history.html", {
        "days": shown, "more_days": len(every) - len(shown), "show": show, "filters": shown_filters, "in_campaign": in_campaign, "campaign": campaign,
        "page_url": f"{web.base()}/manage/history" if in_campaign else "/manage/history",  # not "here": every page already has that (the campaign)
        "focus": revs[0].label if (table and row is not None and revs) else "", "batch": batch,
        "toast": request.session.pop("toast", None)})


DAYS_SHOWN = 7  # (the newest week of days with changes, then Show older: Brett's pick HI3, Nov 25)
RUN_SECONDS = 180  # (changes to many things alike within three minutes are one: a publish, Brett's pick HI1)
NOUNS = {"story_events": ("key moment", "key moments"), "entities": ("entry", "entries"), "glossary_terms": ("glossary term", "glossary terms"),
         "game_sessions": ("session", "sessions"), "characters": ("character", "characters"), "campaign_characters": ("character", "characters"),
         "users": ("person", "people"), "campaign_members": ("person", "people"), "facts": ("fact", "facts"),
         "relationships": ("relationship", "relationships"), "entity_aliases": ("name", "names"), "house_rules": ("house rule", "house rules"),
         "player_notes": ("note", "notes"), "character_picks": ("mark", "marks"), "campaigns": ("campaign", "campaigns")}


def _subject(r: Revision, known: dict) -> str:
    """What a change is about, named (Brett's pick HI1): a key moment by its own words, else the row's label."""
    t = known.get((r.table, r.row_id))
    if r.table == "story_events":
        text = getattr(t, "text", None) or (r.old.get("text") if isinstance(r.old, dict) else "")
        if text:
            words = " ".join(str(text).split())
            return f"“{words[:60]}{'…' if len(words) > 60 else ''}”"
    return r.label or NOUNS.get(r.table, (r.table, r.table))[0].capitalize()


def _item(db: Session, user: dict, r: Revision, people: dict, known: dict) -> dict:
    by_email = {e: n for n, e in people.values()}
    return {"r": r, "field": history.FIELD_LABELS.get(r.field, r.field), "source": history.SOURCES.get(r.source, r.source),
            "subject": _subject(r, known), "who": by_email.get((r.actor or "").lower(), r.actor or ""),  # (people by name: S5)
            **_present(db, r, people),
            "long": r.field in ("summary", "description", "data", "note", "deleted"),
            "restorable": may_restore(db, user, r) and history.can_restore(db, r, known)}


def group_changes(items: list[dict]) -> list[dict]:
    """The changes, newest first, as History's rows (Brett's picks HI1 and AH1, Nov 25): one import is one row; the
    same field of one thing changed again and again is one row (changed 8 times, now Nobody); the same change to many
    things together (a session's 24 key moments published) is one row. Each row keeps its changes, in order."""
    out: list[dict] = []
    for x in items:
        r, last = x["r"], (out[-1] if out else None)
        if last is not None:
            y = last["items"][-1]["r"]
            same_batch = r.batch and r.batch == y.batch
            same_run = (r.table, r.row_id, r.field, r.actor) == (y.table, y.row_id, y.field, y.actor) and not r.batch and not y.batch
            alike = ((r.table, r.field, r.actor) == (y.table, y.field, y.actor) and r.new == y.new and r.row_id != y.row_id
                     and not r.batch and abs((y.created_at - r.created_at).total_seconds()) <= RUN_SECONDS)
            if same_batch or (same_run and last["kind"] in ("one", "run")) or (alike and last["kind"] in ("one", "alike")):
                last["items"].append(x)
                last["kind"] = "batch" if same_batch else "run" if same_run else "alike"
                continue
        out.append({"kind": "one", "items": [x]})
    for e in out:
        first, newest = e["items"][-1], e["items"][0]
        e["at"], e["ids"] = newest["r"].created_at, [x["r"].id for x in e["items"]]
        e["who"] = newest["who"]
        n = len(e["items"])
        if e["kind"] == "one":
            e["title"] = newest["subject"]
        elif e["kind"] == "batch":
            e["title"] = f"An import: {n} changes" if newest["r"].source in ("import", "undo-import") else f"{n} changes together"
        elif e["kind"] == "run":
            e["title"] = f"{newest['subject']}: {newest['field'].lower()}"
            e["line"] = f"Changed {n} times, {first['r'].created_at:%-I:%M}–{newest['r'].created_at:%-I:%M %p} · now {newest.get('new') or newest.get('change') or '—'}"
        else:
            noun = NOUNS.get(newest["r"].table, ("thing", "things"))[1]
            field, value = newest["field"], str(newest.get("new") or "")
            if newest["r"].field == "deleted":
                e["title"] = f"{n} {noun} deleted"
            elif value.lower() == field.lower() or newest["r"].field == "status":
                e["title"] = f"{n} {noun} {value.lower() or field.lower()}"  # (24 key moments published)
            else:
                e["title"] = f"{n} {noun}: {field.lower()} → {value}" if value else f"{n} {noun}: {field.lower()} changed"
    return out


@router.get("/window")
def history_window(request: Request, ids: str = "", db: Session = Depends(get_db)):
    """A History row's window (Brett's pick HI2, Nov 25): each of its changes, before and after, with its Restore. Only
    changes this person may see, and only in the campaign of the address (or none, on askdnd's)."""
    in_campaign = access.path_slug.get() is not None
    user, denied = _guard(request, allow=is_reviewer if in_campaign else is_admin)
    if denied:
        return denied
    campaign = web.campaign(db) if in_campaign else None
    want = [int(i) for i in ids.split(",") if i.strip().isdigit()][:PAGE]
    revs = list(db.scalars(select(Revision).where(Revision.id.in_(want or [0]), Revision.table.in_(visible_tables(user))).order_by(Revision.id.desc())))
    where = history.campaigns_of(db, revs)
    revs = [r for r in revs if (where[r.id] == campaign.id if campaign is not None else (not in_campaign and (where[r.id] is None or r.batch)))]
    people = {u.id: (u.name if u.name and u.name != u.email else u.email, u.email) for u in db.scalars(select(User))}
    known = history.targets(db, revs)
    items = [_item(db, user, r, people, known) for r in revs]
    entry = (group_changes(items) or [{"title": "Nothing to show", "items": [], "kind": "one", "who": ""}])[0]
    return templates.TemplateResponse(request, "_history_window.html", {
        "e": entry, "all": items, "page_url": f"{web.base()}/manage/history" if in_campaign else "/manage/history"})


@router.post("/{rev_id:int}/restore")
def restore(request: Request, rev_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request, allow=is_reviewer)
    if denied:
        return denied
    rev = db.get(Revision, rev_id)
    if rev is None or rev.table not in visible_tables(user) or not may_restore(db, user, rev) or not history.can_restore(db, rev):
        request.session["toast"] = web.notice("That can't be restored.", "warn")
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
