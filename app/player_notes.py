"""Player notes on the Character page (Plan mode): Battle combos, Leveling strategy, Personal
quests and General notes. They replace syncing players' Google Docs.

- Only the character's player writes them (like stars and reminders, app/picks.py).
- Every player can read them; the DM never sees them (CLAUDE.md).
- Names of things on the character's sheet (spells, features, items, Wild Shape
  forms) become links that open them; so do people and places from the campaign.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import picks, web
from app import wild_shape as ws
from app.auth import can_see_character_notes, current_user
from app.db import get_db
from app.linking import TAG, entity_linker
from app.models import Character, PlayerNote
from app.render import markdown_to_html
from app.templating import templates

router = APIRouter()

KINDS = {
    "combo": {"label": "Battle combo", "tab": "Combos", "plural": "Battle combos", "new": "New battle combo",
              "about": "A plan that plays out over more than one turn: the setup, then the payoff."},
    "leveling": {"label": "Leveling strategy", "tab": "Leveling", "plural": "Leveling strategy", "new": "New leveling plan",
                 "about": "Where you're taking the character, level by level, and why."},
    "quest": {"label": "Personal quest", "tab": "Quests", "plural": "Personal quests", "new": "New personal quest",
              "about": "Something your character is after: the goal, why, who's involved and the leads."},
    "general": {"label": "General note", "tab": "Notes", "plural": "General notes", "new": "New note",
                "about": "Anything else, written however you like."},
}
QUEST_STATUS = {"open": "Open", "done": "Done", "abandoned": "Abandoned"}
MAX_TEXT, MAX_BODY, MAX_ROWS = 2000, 20000, 20
TURN_FIELDS = ("label", "action", "bonus", "reaction", "move", "notes")  # the older fixed-box shape
STEP_KINDS = {"bonus": "Bonus action", "action": "Action", "reaction": "Reaction", "move": "Movement", "free": "Free"}


def combo_steps(turn: dict) -> list[dict]:
    """A combo turn's steps in the order the player plays them. Older combos had one
    box per kind (action, bonus, reaction, move); those read in that order."""
    if "steps" in turn:
        return turn["steps"]
    return [{"kind": k, "text": turn[k]} for k in ("action", "bonus", "reaction", "move") if turn.get(k)]


def _combo_turns(form) -> list[dict]:
    """Turns from the form, walking its fields in page order: a turn_label starts a
    turn, each step_kind / step_text pair adds a step to it, turn_notes ends it. So a
    Bonus action can come before the Action, as it can at the table."""
    if form.getlist("turn_action"):  # the older form (one box per kind)
        rows = zip(*(form.getlist(f"turn_{f}") for f in TURN_FIELDS), strict=False)
        turns = [dict(zip(TURN_FIELDS, (_clean(v) for v in r), strict=True)) for r in rows]
        return [{"label": x["label"], "steps": combo_steps(x), "notes": x["notes"]} for x in turns]
    turns, kind = [], "action"
    for key, value in form.multi_items():
        if key == "turn_label":
            turns.append({"label": _clean(value, 200), "steps": [], "notes": ""})
        elif not turns:
            continue
        elif key == "step_kind":
            kind = value if value in STEP_KINDS else "action"
        elif key == "step_text" and _clean(value):
            turns[-1]["steps"].append({"kind": kind, "text": _clean(value)})
        elif key == "turn_notes":
            turns[-1]["notes"] = _clean(value)
    return turns


def _clean(value, limit: int = MAX_TEXT) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def parse(kind: str, form) -> tuple[str, str, dict]:
    """(title, status, data) from a submitted note form. Raises ValueError."""
    if kind not in KINDS:
        raise ValueError("Unknown kind of note.")
    title = _clean(form.get("title"), 200)
    status = ""
    if kind == "combo":
        turns = [t for t in _combo_turns(form) if t["steps"] or t["notes"]][:MAX_ROWS]
        for i, t in enumerate(turns):
            t["label"] = t["label"] or f"Turn {i + 1}"
        data = {k: _clean(form.get(k)) for k in ("when", "needs", "payoff", "risks")} | {"turns": turns}
    elif kind == "leveling":
        rows = zip(*(form.getlist(f"step_{f}") for f in ("level", "class", "take", "why", "done")), strict=False)
        steps = [{"level": _clean(lv, 10), "class": _clean(c, 60), "take": _clean(t), "why": _clean(w), "done": d == "1"}
                 for lv, c, t, w, d in rows]
        data = {"goal": _clean(form.get("goal")), "steps": [s for s in steps if s["level"] or s["take"] or s["why"]][:MAX_ROWS]}
    elif kind == "quest":
        rows = zip(form.getlist("step_text"), form.getlist("step_done"), strict=False)
        steps = [{"text": _clean(t), "done": d == "1"} for t, d in rows if _clean(t)][:MAX_ROWS]
        data = {k: _clean(form.get(k)) for k in ("goal", "why", "who")} | {"steps": steps}
        status = form.get("status") if form.get("status") in QUEST_STATUS else "open"
    else:
        data = {"body": _clean(form.get("body"), MAX_BODY)}
    if not title:
        title = {"combo": "Untitled combo", "leveling": "Level plan", "quest": "Untitled quest", "general": "Note"}[kind]
    return title, status, data


def notes_for(db: Session, character: Character, user: dict | None) -> list[PlayerNote]:
    """This character's notes, or none for the DM."""
    if not can_see_character_notes(user):
        return []
    return list(db.scalars(select(PlayerNote).where(PlayerNote.character_id == character.id)
                           .order_by(PlayerNote.position, PlayerNote.id)))


def grouped(notes: list[PlayerNote]) -> list[tuple[str, dict, list[PlayerNote]]]:
    return [(k, meta, [n for n in notes if n.kind == k]) for k, meta in KINDS.items()]


# ------------------------------------------------------------------ linking


@dataclass
class NoteLinker:
    """Links names in a player's note: things on their sheet, then campaign names."""

    pattern: re.Pattern | None
    urls: dict[str, tuple[str, bool]]  # name -> (url, opens in the large modal)
    campaign: object | None

    def _replace(self, m: re.Match) -> str:
        url, large = self.urls[m.group(0)]
        attr = f'data-modal-url="{url}" data-modal-size="large"' if large else f'data-panel-url="{url}"'
        return f'<a class="ent sheet-ref" href="#" {attr}>{m.group(0)}</a>'

    def html(self, html: str | Markup) -> Markup:
        out, in_link = [], 0
        for part in TAG.split(str(html)):
            if part.startswith("<"):
                low = part.lower()
                in_link += 1 if low.startswith("<a ") else -1 if low.startswith("</a") else 0
                out.append(part)
            elif in_link or not self.pattern:
                out.append(part)
            else:
                out.append(self.pattern.sub(self._replace, part))
        linked = Markup("".join(out))
        return self.campaign.html(linked) if self.campaign else linked

    def text(self, text: str | None) -> Markup:
        return self.html(escape(text or ""))

    def md(self, text: str | None) -> Markup:
        return self.html(Markup(markdown_to_html(text or "", lambda name: None)))


def note_linker(db: Session, character: Character, sheet: dict | None) -> NoteLinker:
    urls: dict[str, tuple[str, bool]] = {}
    base = f"/characters/{character.id}"
    for section in ("spells", "actions", "features", "inventory", "situational"):
        for x in (sheet or {}).get(section) or []:
            name = (x.get("base_name") or x.get("name") or "").strip()
            if len(name) >= 4 and x.get("key") and ":" not in name:
                urls.setdefault(name, (f"{base}/detail?ref={x['key']}", False))
    for book in (sheet or {}).get("spellbook") or []:
        for x in book["spells"]:
            urls.setdefault(x["name"], (f"{base}/detail?ref={x['key']}", False))
    if ws.druid(sheet):
        for f in ws.forms(sheet, set()):
            urls[f["name"]] = (f"{base}/form?name={f['name'].replace(' ', '%20')}", True)
    names = sorted(urls, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])") if names else None
    campaign = entity_linker(db, character.entity.campaign_id) if character.entity else None
    return NoteLinker(pattern, urls, campaign)


# ------------------------------------------------------------------ routes


def _load(request: Request, db: Session, character_id: int, edit: bool = False):
    user = current_user(request)
    if not user:
        return None, None, RedirectResponse("/login", status_code=303)
    ch = db.get(Character, character_id)
    if ch is None:
        return user, None, HTMLResponse("Not found", status_code=404)
    if not can_see_character_notes(user) or (edit and not picks.can_edit(db, user, ch)):
        return user, None, web.forbidden(request, "Only this character's player can do that.")
    return user, ch, None


@router.get("/characters/{character_id:int}/notes/new")
def new_note(request: Request, character_id: int, kind: str = "combo", db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id, edit=True)
    if stop:
        return stop
    if kind not in KINDS:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "_note_form.html", {"c": ch, "n": None, "kind": kind, "meta": KINDS[kind],
                                                                   "data": {}, "status": "open", "statuses": QUEST_STATUS})


@router.get("/characters/{character_id:int}/notes/{note_id:int}/edit")
def edit_note(request: Request, character_id: int, note_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id, edit=True)
    if stop:
        return stop
    n = db.get(PlayerNote, note_id)
    if n is None or n.character_id != ch.id:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "_note_form.html", {"c": ch, "n": n, "kind": n.kind, "meta": KINDS[n.kind],
                                                                   "data": n.data or {}, "status": n.status, "statuses": QUEST_STATUS})


@router.post("/characters/{character_id:int}/notes")
async def save_note(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id, edit=True)
    if stop:
        return stop
    form = await request.form()
    note_id = form.get("note_id")
    n = db.get(PlayerNote, int(note_id)) if note_id and str(note_id).isdigit() else None
    if note_id and (n is None or n.character_id != ch.id):
        return HTMLResponse("", status_code=404)
    kind = n.kind if n else str(form.get("kind", ""))
    try:
        title, status, data = parse(kind, form)
    except ValueError as e:
        return HTMLResponse(str(e), status_code=400)
    if n is None:
        last = db.scalar(select(func.max(PlayerNote.position)).where(PlayerNote.character_id == ch.id)) or 0
        me = picks.user_row(db, user)
        n = PlayerNote(character_id=ch.id, author_id=me.id if me else None, kind=kind, position=last + 1)
        db.add(n)
    n.title, n.status, n.data = title, status, data
    db.commit()
    if request.headers.get("HX-Request"):  # saved from the modal: the page updates in place, no reload (roadmap step 6)
        return _changed(ch, kind, f"Saved: {title}")
    request.session["toast"] = f"Saved: {title}"
    return RedirectResponse(_back(request, ch), status_code=303)


def _changed(ch: Character, kind: str, toast: str) -> Response:
    """No page to send: tell the page a note changed (it closes the modal and refreshes that part)."""
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": toast, "notesChanged": {"character": ch.id, "kind": kind}})})


@router.get("/characters/{character_id:int}/notes/{note_id:int}")
def note_panel(request: Request, character_id: int, note_id: int, db: Session = Depends(get_db)):
    """Side panel: one note in full (Plan's rows and tiles open it)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    n = db.get(PlayerNote, note_id)
    if n is None or n.character_id != ch.id:
        return HTMLResponse("", status_code=404)
    from app import characters as chars

    return templates.TemplateResponse(request, "_note_panel.html", {
        "c": ch, "n": n, "meta": KINDS[n.kind], "can_pick": picks.can_edit(db, user, ch), "quest_status": QUEST_STATUS,
        "nl": note_linker(db, ch, chars.character_summary(ch))})


@router.post("/characters/{character_id:int}/notes/order")
def order_notes(request: Request, character_id: int, column: str = Form(...), keys: list[str] = Form(default=[]),
                db: Session = Depends(get_db)):
    """Drag and drop on Plan: the player's own order for one kind of note (combos, leveling, quests, notes)."""
    user, ch, stop = _load(request, db, character_id, edit=True)
    if stop:
        return stop
    ids = [int(k) for k in keys if k.isdigit()]
    mine = {n.id: n for n in db.scalars(select(PlayerNote).where(PlayerNote.character_id == ch.id, PlayerNote.kind == column))}
    for i, nid in enumerate(x for x in ids if x in mine):
        mine[nid].position = i + 1
    db.commit()
    return Response(status_code=204)


def _back(request: Request, ch: Character) -> str:
    """After saving: back to Battle if the note was added there (Battle combos), else Plan."""
    came_from = urlparse(request.headers.get("referer", "")).path
    return came_from if came_from == f"/characters/{ch.id}/battle" else f"/characters/{ch.id}/plan"


@router.post("/characters/{character_id:int}/notes/{note_id:int}/delete")
def delete_note(request: Request, character_id: int, note_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id, edit=True)
    if stop:
        return stop
    n = db.get(PlayerNote, note_id)
    if n is not None and n.character_id == ch.id:
        db.delete(n)
        db.commit()
        if request.headers.get("HX-Request"):
            return _changed(ch, n.kind, f"Deleted: {n.title}")
        request.session["toast"] = f"Deleted: {n.title}"
    return RedirectResponse(_back(request, ch), status_code=303)


def page_context(db: Session, ch: Character, user: dict | None, sheet: dict | None) -> dict:
    """What the Character page needs to show notes (Plan, and combos on Battle)."""
    notes = notes_for(db, ch, user)
    return {"player_notes": grouped(notes), "note_count": len(notes), "combos": [n for n in notes if n.kind == "combo"],
            "nl": note_linker(db, ch, sheet) if notes else None, "note_kinds": KINDS, "quest_status": QUEST_STATUS}

