"""Admin: the campaign doc (a Google Doc of session notes that recap drafts come
from), under Manage › Recaps, and its Sync button.

Players' character docs used to sync here too; structured player notes on the
Character page replace them (2026-10-18). Old character-doc sources are no longer
synced; they're listed only so an admin who isn't the DM can remove them.

Sync asks Google for read-only Drive access each time and keeps no token:
in Testing mode Google expires stored refresh tokens after 7 days anyway.
"""


from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app import config
from app.admin import _guard as _admin_guard
from app.auth import can_see_character_notes, is_admin
from app.auth import oauth
from app.db import get_db
from app.gdocs import (
    DOCS_URL,
    EXPORT_URL,
    MAX_EXPORT_BYTES,
    ExportedDoc,
    doc_id_from_url,
    docs_json_to_text,
    export_image_order,
    parse_export,
    shrink_image,
)
from app.models import NoteImage, NoteSnapshot, NoteSource
from app.notes_sync import sync_sources
from app.render import markdown_to_html
from app.templating import templates

DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"

oauth.register(
    name="google_drive",
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": f"openid email {DRIVE_READONLY}"},
)

router = APIRouter(prefix="/admin/notes")

_API_OFF = (
    "A Google API this needs isn't turned on for your Google Cloud project. Enable both the "
    "Google Docs API and the Google Drive API (Google Cloud → search each name → Enable), "
    "wait a few minutes, then sync again."
)
GOOGLE_ERROR_HELP = {
    "accessNotConfigured": _API_OFF,
    "SERVICE_DISABLED": _API_OFF,
    "notFound": "Google can't find this doc for your account. Check the link, and that you're signed in with the account that owns or can open the doc.",
    "insufficientFilePermissions": "Your account can't open this doc. Check it's shared with you.",
    "exportSizeLimitExceeded": "Google can't export a doc this large (10 MB limit). Try making its images smaller.",
}


class GoogleError(Exception):
    pass



def _guard(request: Request):
    """Admins (the campaign doc is for the whole table)."""
    return _admin_guard(request, allow=is_admin)


def _visible(source: NoteSource, user: dict) -> bool:
    """Old character docs stay hidden from the DM."""
    return source.character_id is None or can_see_character_notes(user)

def explain_google_error(resp) -> str:
    """Turn a Drive API error response into a plain-English message."""
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}
    reasons = [e.get("reason", "") for e in err.get("errors", [])]
    reasons += [d.get("reason", "") for d in err.get("details", []) if isinstance(d, dict)]
    for reason in reasons:
        if reason in GOOGLE_ERROR_HELP:
            return GOOGLE_ERROR_HELP[reason]
    return f"Google said {resp.status_code}: {err.get('message') or 'unknown error'}"


@router.get("")
def notes_page(request: Request, db: Session = Depends(get_db), result: str | None = None):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
    every = [s for s in db.scalars(select(NoteSource).order_by(NoteSource.id)) if _visible(s, user)] if campaign else []
    sources = [s for s in every if s.character_id is None]
    retired = [s for s in every if s.character_id is not None]
    stats = {}
    for s in every:
        latest = s.snapshots[-1] if s.snapshots else None
        n_images = db.scalar(select(func.count()).where(NoteImage.snapshot_id == latest.id)) if latest else 0
        stats[s.id] = {"latest": latest, "words": len(latest.text.split()) if latest else 0, "images": n_images}
    results = request.session.pop("sync_results", None)
    return templates.TemplateResponse(
        request,
        "admin_notes.html",
        {
            "user": user,
            "campaign": campaign,
            "sources": sources,
            "retired": retired,
            "stats": stats,
            "results": results,
            "failed_count": sum(1 for v in (results or {}).values() if v.startswith("failed")),
            "error": request.session.pop("notes_error", None),
        },
    )


@router.post("/sources")
def add_source(request: Request, url: str = Form(...), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
    doc_id = doc_id_from_url(url)
    if campaign is None:
        request.session["notes_error"] = "Import the campaign first."
    elif doc_id is None:
        request.session["notes_error"] = "That doesn't look like a Google Docs link."
    elif db.scalar(select(NoteSource).where(NoteSource.google_doc_id == doc_id)):
        request.session["notes_error"] = "That doc is already on the list."
    else:
        db.add(NoteSource(campaign_id=campaign.id, google_doc_id=doc_id))
        db.commit()
    return RedirectResponse("/admin/notes", status_code=303)


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    source = db.get(NoteSource, source_id)
    if source and _visible(source, user):
        db.delete(source)
        db.commit()
    return RedirectResponse("/admin/notes", status_code=303)


@router.post("/sync")
async def start_sync(request: Request):
    user, denied = _guard(request)
    if denied:
        return denied
    redirect_uri = str(request.url_for("notes_sync_callback"))
    return await oauth.google_drive.authorize_redirect(
        request, redirect_uri, login_hint=user["email"], include_granted_scopes="true"
    )


@router.get("/callback", name="notes_sync_callback")
async def sync_callback(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    try:
        token = await oauth.google_drive.authorize_access_token(request)
    except OAuthError as e:
        request.session["notes_error"] = f"Google didn't grant access: {e.description or e.error}"
        return RedirectResponse("/admin/notes", status_code=303)
    granted_email = (token.get("userinfo") or {}).get("email", "").lower()
    if granted_email != user["email"] or DRIVE_READONLY not in token.get("scope", ""):
        request.session["notes_error"] = "Sign in with your own account and allow read-only Drive access."
        return RedirectResponse("/admin/notes", status_code=303)

    sources = list(db.scalars(select(NoteSource).where(NoteSource.character_id.is_(None)).order_by(NoteSource.id)))
    fetched: dict[str, object] = {}
    for s in sources:
        try:
            fetched[s.google_doc_id] = await fetch_doc(s.google_doc_id, token)
        except Exception as e:
            fetched[s.google_doc_id] = e

    def fetch(doc_id):
        value = fetched[doc_id]
        if isinstance(value, Exception):
            raise value
        return value

    results = sync_sources(db, sources, fetch)
    db.commit()
    request.session["sync_results"] = results
    return RedirectResponse("/admin/notes", status_code=303)


async def fetch_doc(doc_id: str, token: dict) -> tuple[str, ExportedDoc]:
    """Read a doc via the Docs API (all tabs, exact nesting, images). Drawings
    aren't available there, so if the doc has any, fill them in from Drive's
    HTML export, matching images by their order in the document."""
    client = oauth.google_drive
    resp = await client.get(DOCS_URL.format(id=doc_id), token=token, timeout=60)
    if resp.status_code != 200:
        raise GoogleError(explain_google_error(resp))
    doc = resp.json()
    text, objects = docs_json_to_text(doc)
    images: dict[str, tuple[str, bytes]] = {}
    for obj in objects:
        if obj["kind"] == "image":
            r = await client.get(obj["uri"], token=token, timeout=60)
            if r.status_code == 200:
                ctype = r.headers.get("content-type", "image/png").split(";")[0]
                images[obj["name"]] = shrink_image(ctype, r.content)
    if any(o["kind"] == "drawing" for o in objects):
        try:
            export = await client.get(EXPORT_URL.format(id=doc_id), token=token, timeout=120)
            if export.status_code == 200 and len(export.content) <= MAX_EXPORT_BYTES:
                exported = parse_export(export.content)
                order = export_image_order(exported)
                if len(order) == len(objects):
                    for obj, name in zip(objects, order):
                        if obj["kind"] == "drawing" and name in exported.images:
                            images[obj["name"]] = shrink_image(*exported.images[name])
        except Exception:
            pass  # drawings are a bonus; the text and images still sync
    return doc.get("title", ""), ExportedDoc(text=text, images=images)


@router.get("/snapshots/{snapshot_id}")
def view_snapshot(request: Request, snapshot_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    snap = db.get(NoteSnapshot, snapshot_id)
    if snap is None or not _visible(snap.source, user):
        return RedirectResponse("/admin/notes", status_code=303)
    ids = {img.name: img.id for img in snap.images}
    body = markdown_to_html(snap.text, lambda name: f"/admin/notes/images/{ids[name]}" if name in ids else None)
    return templates.TemplateResponse(request, "admin_snapshot.html", {"user": user, "snap": snap, "body": body})


@router.get("/images/{image_id}")
def image(request: Request, image_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    img = db.get(NoteImage, image_id)
    if img is None or not _visible(db.get(NoteSnapshot, img.snapshot_id).source, user):
        return Response(status_code=404)
    return Response(img.data, media_type=img.content_type, headers={"Cache-Control": "private, max-age=3600"})
