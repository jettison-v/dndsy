"""Backstage › Tool corrections (admins, /manage/tool-corrections): corrections to how askdnd reads D&D Beyond, made
from character side panels (tool_corrections). They apply to every character in every campaign, so they belong to
askdnd as a whole. A DM's rulings for one table are House rules instead."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import rules_terms as terms
from app.admin import _guard
from app.db import get_db
from app.fft import rules as fft
from app.fft import views as fft_views
from app.fft.models import FftIssue, FftNote
from app.models import Character, ToolCorrection
from app.templating import templates

router = APIRouter(prefix="/manage/tool-corrections")


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    overrides = list(db.scalars(select(ToolCorrection).order_by(ToolCorrection.updated_at.desc())))
    labels = {f: dict(c) for f, c in {**views.OVERRIDE_CHOICES, **views.TERM_CHOICES}.items()}
    pairs = _pairs(db)  # (every character's sheet, read once for all three: Nov 20)
    sheets = [sh for _, sh in pairs]
    split = _split(db, overrides, sheets)
    return templates.TemplateResponse(request, "tool_corrections.html", {
        "overrides": overrides, "labels": labels, "field_labels": views.FIELD_LABELS, "names": _names(overrides, pairs),
        "says": {o.id: says(o) for o in overrides}, "sent": _sent(db, split["open"]),
        **split,
        "toast": request.session.pop("toast", None),
    })


# What a correction does, in words (Brett's pick TC1 on docs/mockups/backstage-round-3/, Nov 25: "Costs an Action",
# never "Section (what it costs): Action").
SAYS = {"hide": {"hide": "Hidden everywhere in askdnd"},
        "cost": {"Action": "Costs an Action", "Bonus action": "Costs a Bonus Action", "Reaction": "Costs a Reaction",
                 "No action": "Needs no action", "Other": "Not on your turn"},
        "battle": {"common": "Shown on Battle", "normal": "Only in Battle's See all", "hide": "Not on Battle"},
        "feature_group": {"use": "Listed under Things you can use", "passive": "Listed as always on, in your numbers"},
        "situ_group": {"situational": "Listed as situational", "in_numbers": "Already in your numbers"},
        "underline": {"on": "Underlined in descriptions", "off": "Not underlined in descriptions"}}


def says(o: ToolCorrection) -> str:
    """One correction as a person says it: its change, in words."""
    if o.field == "item_group":
        return f"Listed under {dict(views.ITEM_GROUPS).get(o.value, o.value)}"
    return SAYS.get(o.field, {}).get(o.value) or f"{views.FIELD_LABELS.get(o.field, o.field)}: {o.value}"


KINDS = {"spell": "Spell", "item": "Item", "feature": "Feature", "action": "Action", "attack": "Attack", "creature": "Wild Shape form"}


def automatic(sheets: list[dict], ref: str, field: str, seen: dict | None = None) -> str | None:
    """What askdnd chooses on its own for this thing, without any correction: the value the correction would set
    if askdnd got it right. None when no character has the thing (or for "hide", which askdnd never chooses).
    When a code fix makes this equal a correction's value, the correction is built in (Brett, 2026-10-23). `seen` keeps
    each sheet's options across the corrections of one count (Nov 20: rebuilt per correction, it cost every Backstage
    page's counts half a second)."""
    if field == "underline":
        term = next((t for t in terms.TERMS if f"term:{t.name}" == ref), None)
        return None if term is None else ("off" if term.basic else "on")
    seen = {} if seen is None else seen
    for n, raw in enumerate(sheets):
        sheet = seen.get(("sheet", n))
        if sheet is None:
            sheet = seen[("sheet", n)] = views.apply_overrides(raw, {})
        if ref.split(":", 1)[-1].isdigit() and (x := views.find(sheet, ref)):  # an older correction, stored by D&D Beyond number
            ref = views.override_ref(x, x["section"])
        if field in ("cost", "battle"):
            opts = seen.get(("options", n))
            if opts is None:
                opts = seen[("options", n)] = views.options(sheet)
            o = next((o for o in opts if o["oref"] == ref), None)
            if o:
                return o["cost"] if field == "cost" else ("common" if o.get("common") else "normal")
        section, key = {"feature_group": ("features", "use"), "situ_group": ("situational", "in_numbers"),
                        "item_group": ("inventory", "group")}.get(field, (None, None))
        if section:
            x = next((x for x in sheet.get(section) or [] if views.override_ref(x, section) == ref), None)
            if x is not None:
                if field == "feature_group":
                    return "use" if x["use"] else "passive"
                if field == "situ_group":
                    return "in_numbers" if x["in_numbers"] else "situational"
                return x["group"]
    return None


def _pairs(db: Session) -> list[tuple[int, dict]]:
    """Every character's sheet, with the character's id (a correction's row opens its side panel there)."""
    return [(c.id, sh) for c in db.scalars(select(Character).order_by(Character.id)) if (sh := chars.character_summary(c))]


def _sheets(db: Session) -> list[dict]:
    return [sh for _, sh in _pairs(db)]


def _status(db: Session, overrides: list[ToolCorrection], sheets: list[dict] | None = None) -> dict[int, str]:
    """Each correction: "open" (askdnd still gets it wrong), "built_in" (askdnd now chooses the same on its own,
    so the correction can go) or "unseen" (no character has the thing now)."""
    sheets = _sheets(db) if sheets is None else sheets
    out, seen = {}, {}
    for o in overrides:
        auto = automatic(sheets, o.ref, o.field, seen)
        out[o.id] = "open" if o.field == "hide" or (auto is not None and auto != o.value) else ("built_in" if auto == o.value else "unseen")
    return out


def _split(db: Session, overrides: list[ToolCorrection], sheets: list[dict] | None = None) -> dict:
    status = _status(db, overrides, sheets)
    return {"open": [o for o in overrides if status[o.id] != "built_in"], "built": [o for o in overrides if status[o.id] == "built_in"],
            "unseen": {o.id for o in overrides if status[o.id] == "unseen"}}


_OPEN: dict = {}  # (the inputs' fingerprint → the count: one per process)


def open_count(db: Session) -> int:
    """For Needs you: corrections askdnd still needs a code fix for. Working it out builds every character's roll options
    (about half a second), and Backstage's counts ask on every page, so the answer is kept until a sheet, a character or
    a correction changes (their row counts and newest change, and this process's code: a deploy starts afresh)."""
    rows = list(db.scalars(select(ToolCorrection).where(ToolCorrection.field != "hide")))
    if not rows:
        return 0
    from app.models import CharacterSnapshot

    marks = (db.execute(select(func.count(), func.max(CharacterSnapshot.updated_at))).one(),
             db.execute(select(func.count(), func.max(Character.updated_at)).select_from(Character)).one(),
             tuple(sorted((o.id, o.value, str(o.updated_at)) for o in rows)))
    key = repr(marks)
    if key not in _OPEN:
        _OPEN.clear()
        _OPEN[key] = sum(1 for v in _status(db, rows).values() if v == "open")
    return _OPEN[key]


WHAT = {"spell": "a spell", "item": "an item", "feature": "a feature", "action": "an action", "attack": "an attack",
        "form": "a Wild Shape form", "creature": "a Wild Shape form", "term": "a rule term"}


def _names(overrides: list[ToolCorrection], pairs: list[tuple[int, dict]]) -> dict[str, dict]:
    """What each correction is about, by name (Brett, 2026-10-23: the bare number meant nothing), what it is in words
    ("an item"; an item's own action "its Turn invisible action": the UI review's TC1, Nov 25, never
    "Ring of Invisibility#turn invisible"), and the side panel it was made from, on a character who has it."""
    out = {}
    for o in overrides:
        base, _, part = o.ref.partition("#")
        kind, _, rest = base.partition(":") if ":" in base else ("", "", base)
        cid, found = _where(pairs, base)
        plain = rest.replace("-", " ").replace("_", " ").strip()
        plain = plain[:1].upper() + plain[1:] if plain.islower() else plain
        name = (found or {}).get("name") or (plain if not rest.isdigit() else f"Item {rest} (no character has it now)")
        action = part.replace("-", " ").replace("_", " ").strip()
        out[o.ref] = {"name": name, "kind": KINDS.get(kind, kind.capitalize()),
                      "what": f"its {action[:1].upper() + action[1:]} action" if action else WHAT.get(kind, ""),
                      "panel": f"/characters/{cid}/detail?ref={quote(found['key'], safe='')}" if found and found.get("key") else ""}
    return out


def _where(pairs: list[tuple[int, dict]], ref: str) -> tuple[int | None, dict | None]:
    """A character who has the thing, and the thing on their sheet: by its stored name ("item:Arrows"), or an older
    correction's D&D Beyond number."""
    for cid, sheet in pairs:
        if x := views.find(sheet, ref):
            return cid, x
        for section in ("features", "inventory", "attacks", "spells", "actions", "creatures"):
            for x in sheet.get(section) or []:
                if views.override_ref(x, section) == ref:
                    return cid, x
    return None, None


def _sent(db: Session, waiting: list[ToolCorrection]) -> dict | None:
    """The last time they were sent to Claude, while its issue is open and nothing has changed since: the page says so
    in place of the button (TC2)."""
    note = db.scalars(select(FftNote).where(FftNote.url == SENT_FROM, FftNote.issue_id.is_not(None)).order_by(FftNote.id.desc()).limit(1)).first()
    if note is None or not waiting:
        return None
    issue = db.get(FftIssue, note.issue_id)
    if issue is None or issue.state == "closed" or any(o.updated_at > note.created_at for o in waiting):
        return None
    return {"at": note.created_at, "issue": issue.id}


SENT_FROM = "/manage/tool-corrections"


@router.post("/send")
def send_to_claude(request: Request, db: Session = Depends(get_db)):
    """Send these to Claude (Brett's pick TC2 on docs/mockups/backstage-round-3/, Nov 25): the corrections askdnd still
    gets wrong, filed in Feedback as one issue under Corrections, to be built into askdnd with a test each."""
    user, denied = _guard(request)
    if denied:
        return denied
    overrides = list(db.scalars(select(ToolCorrection).order_by(ToolCorrection.updated_at.desc())))
    pairs = _pairs(db)
    waiting = _split(db, overrides, [sh for _, sh in pairs])["open"]
    if not waiting:
        request.session["toast"] = "Nothing waits: askdnd gets them all right"
        return RedirectResponse(SENT_FROM, status_code=303)
    names = _names(waiting, pairs)
    lines = [f"- {names[o.ref]['name']}{', ' + names[o.ref]['what'] if names[o.ref]['what'] else ''}: {says(o)}"
             f"{'. Why: ' + o.reason if o.reason else ''} ({o.ref}, {o.field} = {o.value})" for o in waiting]
    text = "Build these tool corrections into askdnd, each with a test, so they move to Built into askdnd:\n" + "\n".join(lines)
    me = fft_views.person(db, user)
    note = fft.send_note(db, user_id=me["id"], first_name=me["first_name"], role=me["role"], kind="problem", text=text,
                         url=SENT_FROM, page="Tool corrections")
    issue = db.get(FftIssue, note.issue_id) if note.issue_id else None
    if issue is not None:
        fft.retitle(db, f"user:{me['id']}", issue, f"Build in {len(waiting)} tool correction{'s' if len(waiting) != 1 else ''}")
        fft.set_feature(db, f"user:{me['id']}", issue, "corrections")
    note.seen = note.told = fft_views.marker(db, note, me["id"])
    db.commit()
    request.session["toast"] = "Sent to Claude, in Feedback"
    return RedirectResponse(SENT_FROM, status_code=303)


@router.post("/overrides/{override_id:int}/delete")
def undo_override(request: Request, override_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        db.delete(row)
        db.commit()
        request.session["toast"] = "Back to automatic"
    return RedirectResponse("/manage/tool-corrections", status_code=303)


@router.post("/overrides/{override_id:int}/reason")
def override_reason(request: Request, override_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    """Why a tool correction was needed (feedback for fixing the parser)."""
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        row.reason = " ".join(reason.split())[:300]
        db.commit()
        request.session["toast"] = "Saved"
    return RedirectResponse("/manage/tool-corrections", status_code=303)
