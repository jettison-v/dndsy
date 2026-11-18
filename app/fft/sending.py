"""Sending a note (screen 9 of docs/mockups/found-fixed-tried/; the window is `_feedback_window.html`, app.js "send a
note"): `\\` on any page, for admins and the accounts switched on for it (`access.sends_feedback`).

What it carries: what it is (a problem, an idea or a question: picked each time, never for you), the words, the page's
picture and any added, each marked with Box, Arrow, Draw and Text, and the page as drawn. The page's picture comes as
two copies: the full one, which only its sender ever sees, and the safe copy with the sender's character notes covered
(`[data-private]`, painted over in the browser before it's sent), which approvers, the DM and Claude see (T5). The
page as drawn is sent with those parts already emptied. A picture the sender added themselves is theirs to share.

On staging the note goes to askdnd.ai's relay (`/api/fft/relay`, its own key) with safe copies only, where it always
waits for an admin (T6). The answer says truthfully what happens next (`views.send_line`)."""

import base64
import json
import os
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import access, config, files, view_as, web
from app.auth import current_user
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftPicture, FftTry
from app.templating import templates

router = APIRouter()
MAX_TEXT, MAX_HTML, MAX_CONTEXT = 4000, 3_000_000, 50_000
MAX_PICS, MAX_PIC_BYTES = 4, 8_000_000
IMAGE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$")


def real(request: Request) -> dict | None:
    """The person really signed in: an admin viewing as someone is still themself here."""
    who = request.session.get("real_user")
    return who if who and access.level(who.get("email")) else current_user(request)


def can_send(request: Request) -> bool:
    user = real(request)
    return bool(user and access.sends_feedback(user.get("email")))


def image(value) -> tuple[bytes, str] | None:
    m = IMAGE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        return None
    return (data, m.group(1)) if len(data) <= MAX_PIC_BYTES else None


def _pictures(body: dict) -> list[dict]:
    """[{full, safe, kind}] as sent: each a data: URL (safe may be None: nothing private was on screen)."""
    raw = body.get("pictures") or []
    if not isinstance(raw, list) or len(raw) > MAX_PICS:
        raise HTTPException(400, f"{MAX_PICS} pictures at most.")
    out = []
    for p in raw:
        if not isinstance(p, dict) or image(p.get("full")) is None or (p.get("safe") is not None and image(p.get("safe")) is None):
            raise HTTPException(400, "A picture as PNG, JPEG or WebP, 8 MB at most.")
        out.append({"full": p["full"], "safe": p.get("safe"), "kind": "page" if p.get("kind") == "page" else "added"})
    return out


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Private(HTMLParser):
    """The page as drawn, re-written with every [data-private] part emptied."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            self.skip += int(tag not in VOID)
        elif any(k == "data-private" for k, _ in attrs):
            self.out.append(f'<{tag} data-private="emptied">')
            self.skip = int(tag not in VOID)
        else:
            self.out.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if not self.skip:
            self.out.append(f'<{tag} data-private="emptied">' if any(k == "data-private" for k, _ in attrs) else self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip:
            if tag in VOID:
                return
            self.skip -= 1
            if self.skip:
                return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")

    def handle_decl(self, decl):
        self.out.append(f"<!{decl}>")


def safe_html(html: str) -> str:
    """The page as drawn, kept only with every private part emptied (a player's character notes: T5), whatever the
    browser sent: app.js empties them first, and this makes sure (an older app.js in a tab left open, a part it
    missed; the review of PR #417). Anything it can't read whole is dropped from where it went wrong."""
    p = _Private()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return ""
    return "".join(p.out)


def store_pictures(db: Session, pics: list[dict], safe_only: bool = False) -> list[tuple[str, str, str]]:
    """Each picture into file storage first: (full key, safe key, kind). Done before a note's event is written, so a
    slow upload never holds a change open that Claude's inbox may already have passed (T8)."""
    campaign = web.campaign(db)
    out = []
    if campaign is None or not pics:
        return out
    for p in pics:
        try:
            safe = files.put(db, campaign.id, *image(p["safe"])) if p.get("safe") else None
            full = safe if safe_only and safe else files.put(db, campaign.id, *image(p["full"]))
        except (files.FileError, files.StorageNotReady) as e:
            raise HTTPException(400, str(e)) from e
        out.append((full, safe or full, p["kind"]))
    return out


def attach_pictures(db: Session, stored: list[tuple[str, str, str]], *, note_id: int | None = None, line_id: int | None = None) -> None:
    """`key` the full copy (its sender's), `safe_key` the one everyone else sees."""
    for full, safe, kind in stored:
        db.add(FftPicture(note_id=note_id, line_id=line_id, kind=kind, key=full, safe_key=safe))


@router.post("/feedback")
def send(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    user = real(request)
    if not user or not access.sends_feedback(user.get("email")):
        raise HTTPException(404)
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or "").strip()[:MAX_TEXT]
    kind = body.get("kind") if body.get("kind") in rules.KINDS else ""
    if not kind:
        raise HTTPException(400, "Say what it is first: a problem, an idea or a question.")
    if not text:
        raise HTTPException(400, "Say what it's about first.")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    if len(json.dumps(context)) > MAX_CONTEXT:
        context = {"left_out": "The page's details were too long to keep."}
    viewing = view_as.viewing(request.session)
    if viewing:
        context |= {"viewing_as": (viewing.get("name") or "").split(" ")[0] or "someone"}  # (a first name: no email, T2)
    pics = _pictures(body)
    if viewing:  # (the page was someone else's: their full copy is no one's to keep)
        pics = [p | {"full": p["safe"] or p["full"]} for p in pics]
    me = views.person(db, user)
    try_id = body.get("try") if type(body.get("try")) is int and me["admin"] else None
    if try_id is not None and db.get(FftTry, try_id) is None:
        raise HTTPException(400, "That try isn't there.")
    fields = {"kind": kind, "text": text, "url": str(body.get("url") or "")[:1000], "page": str(context.get("page") or "")[:120],
              "context": context, "html": safe_html(str(body.get("html") or "")[:MAX_HTML])}
    if config.STAGING:
        sent = relay(me, fields, pics)
        if "id" in sent:
            return JSONResponse({"ok": True, "id": sent["id"], "waits": True, "said": "Sent to askdnd.ai: an admin reads it first."})
        fields["context"] = {**fields["context"], "not_relayed": sent.get("error", "")[:300]}
    stored = store_pictures(db, pics)
    try:
        note = rules.send_note(db, user_id=me["id"], first_name=me["first_name"], role=me["role"], try_id=try_id,
                               staging=config.STAGING, **fields)
    except rules.RuleError as e:
        raise HTTPException(400, e.words) from e
    attach_pictures(db, stored, note_id=note.id)
    note.seen = note.told = views.marker(db, note, me["id"])  # (its sender knows what they just did)
    db.commit()
    waits = note.state == "waiting"
    return JSONResponse({"ok": True, "id": note.id, "waits": waits,
                         "said": views.send_line(db, not waits, sent=True)})


SEND = None  # tests replace it: (url, payload, key) -> dict


def relay(me: dict, fields: dict, pics: list[dict]) -> dict:
    """Staging's note to askdnd.ai's relay: safe copies only, a first name, never an email (T2, T6)."""
    key = os.getenv("FFT_RELAY_KEY", "").strip()
    if not key:
        return {"error": "Staging has no FFT_RELAY_KEY, so the note stays here."}
    payload = {**{k: v for k, v in fields.items() if k != "html"}, "context": rules._clean_context(fields["context"]),
               "first_name": me["first_name"], "role": me["role"],
               "pictures": [p["safe"] or p["full"] for p in pics]}  # (no safe copy: nothing private was on screen)
    url = f"{config.PROD_URL}/api/fft/relay"
    if SEND is not None:
        return SEND(url, payload, key)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Fft-Key": key, "User-Agent": "askdnd-staging/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"error": f"askdnd.ai didn't take it ({e})."}


@router.get("/feedback/line")
def line(request: Request, db: Session = Depends(get_db)):
    """The line beside Send, asked as the window opens: true now (is a Claude session listening?)."""
    user = real(request)
    if not user or not access.sends_feedback(user.get("email")):
        raise HTTPException(404)
    admin = access.level(user.get("email")) == access.ADMIN
    return JSONResponse({"line": views.send_line(db, admin), "listening": admin and views.listening(db)}, headers={"Cache-Control": "no-store"})


def shows_menu(request: Request) -> bool:
    """The account menu's item, and More's on a phone: admins only, as the page is seen (viewing as a player, a player's
    menus)."""
    from app.auth import is_admin

    return is_admin(current_user(request))


templates.env.globals["feedback_send"] = can_send
templates.env.globals["feedback_menu"] = shows_menu
templates.env.globals["feedback_kinds"] = views.KIND_SAID
templates.env.globals["feedback_asks"] = views.KIND_ASK
