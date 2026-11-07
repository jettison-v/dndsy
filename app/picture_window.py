"""The one Picture window (Brett, 2026-11-04, docs/mockups/pictures/ board 2): wherever a picture goes, pressing it (or an
empty slot) opens this, with Upload, Describe it and From D&D Beyond, for a World entry or one of a character's creatures
(`for`: app/pictures.py `owner`). And the campaign's art style (Manage › Settings › Art style, board 3)."""

import base64
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, drawing, files, pictures, web
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, Character, EntityPicture, StoredFile
from app.templating import templates

router = APIRouter()


def _owner(db: Session, request: Request, ref: str) -> tuple[pictures.Owner, dict]:
    user = current_user(request)
    o = pictures.owner(db, ref, user)
    if o is None:
        raise HTTPException(404)
    return o, user


def _done(o: pictures.Owner, said: str) -> Response:
    """Closed, said, and every page showing it shows the new one: in place for a creature (its master's pages), the
    World entry's page loaded again."""
    if o.character is not None:
        return Response(status_code=204, headers={"HX-Trigger": web.changed(o.character, said, closePanel=True)})
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": said, "closePanel": True}), "HX-Refresh": "true"})


def _shown(db: Session, o: pictures.Owner) -> dict | None:
    if o.entity is not None:
        return pictures.urls(db, [o.entity.id]).get(o.entity.id)
    return pictures.creature_urls(db, [o.character.id]).get((o.character.id, o.creature))


@router.get("/pictures")
def window(request: Request, for_: str = "", db: Session = Depends(get_db)):
    """The Picture window, as a modal."""
    o, user = _owner(db, request, request.query_params.get("for", for_))
    campaign = db.get(Campaign, o.campaign_id) if o.campaign_id else None
    pic = pictures.find(db, o)
    return templates.TemplateResponse(request, "_picture_window.html", {
        "o": o, "shown": _shown(db, o), "pic": pic, "style": drawing.style(campaign)["words"] or drawing.PLAIN,
        "styled": bool(drawing.style(campaign)["words"]), "style_refs": len(drawing.style(campaign)["refs"][:drawing.REFS]), "no_drawing": drawing.why_not(db, campaign), "how_many": drawing.HOW_MANY,
        "words": pic.words if pic is not None and pic.source == "drawn" and pic.words else o.words,
        # ?tab=draw opens it on Describe it (an empty picture's Draw one on the Reader)
        "start": "draw" if request.query_params.get("tab") == "draw" else "up",
        "relatives": pictures.relatives(db, o.entity, user), "most_refs": drawing.REFS})


@router.get("/pictures/ref")
def ref_named(request: Request, for_: str = "", name: str = "", db: Session = Depends(get_db)):
    """An entry picked with @ in Describe it, as a ticked "go by its picture" (feedback 36), when it has a picture this
    person may send; else nothing."""
    o, user = _owner(db, request, request.query_params.get("for", for_))
    e = pictures.named(db, o, name, user)
    if e is None:
        return Response(status_code=204)
    return templates.TemplateResponse(request, "_picture_ref.html", {"r": {"id": e.id, "name": e.name, "label": "Named", "pic": pictures.urls(db, [e.id])[e.id]["thumb"]}, "field": "ref", "on": True})


@router.post("/pictures/upload")
def upload(request: Request, for_: str = Form("", alias="for"), file: UploadFile = File(...), db: Session = Depends(get_db)):
    o, user = _owner(db, request, for_)
    raw = file.file.read(pictures.MAX_UPLOAD + 1)
    try:
        pictures.save(db, o, raw, user)
    except pictures.PictureError as e:
        raise HTTPException(409, str(e)) from None
    db.commit()
    return _framing(request, db, o, new=True)


@router.post("/pictures/draw")
def draw(request: Request, for_: str = Form("", alias="for"), words: str = Form(""), match: str = Form(""),
         like: list[int] = Form([]), ref: list[int] = Form([]), db: Session = Depends(get_db)):
    """Describe it: four to pick from, drawn in the campaign's style (app/drawing.py), going by the ticked pictures: a
    relative's (`like`) and entries named with @ (`ref`; feedback 34, 36)."""
    o, user = _owner(db, request, for_)
    campaign = db.get(Campaign, o.campaign_id) if o.campaign_id else None
    try:
        kept, look = drawing.draw(db, campaign, words, o.frame, match=bool(match),
                                  like=pictures.usable(db, o, like, user), refs_of=pictures.usable(db, o, ref, user))
    except pictures.PictureError as e:
        raise HTTPException(409, str(e)) from None
    options = [{"full": f, "thumb": t, "src": "data:image/webp;base64," + base64.b64encode(files.read(t) or b"").decode()} for f, t in kept]
    return templates.TemplateResponse(request, "_picture_options.html", {"o": o, "options": options, "words": " ".join(words.split()), "style": look})


@router.post("/pictures/use")
def use(request: Request, for_: str = Form("", alias="for"), pick: str = Form(""), words: str = Form(""), style: str = Form(""),
        db: Session = Depends(get_db)):
    """One of the drawn four, by its two keys ("<full>|<thumb>"), only files of this campaign's that askdnd stored."""
    o, user = _owner(db, request, for_)
    full, _, thumb = pick.partition("|")
    rows = db.scalars(select(StoredFile).where(StoredFile.key.in_([full, thumb]))).all()
    if len(rows) != 2 or any(r.campaign_id != o.campaign_id for r in rows):
        raise HTTPException(409, "Pick one of the four first.")
    pictures.use_drawn(db, o, full, thumb, words, style, user)
    db.commit()
    return _framing(request, db, o, new=True)


def _framing(request: Request, db: Session, o: pictures.Owner, new: bool = False) -> Response:
    """The Frame it step (feedback 12, docs/mockups/picture-framing.html A), in place of the window: the last step after
    Upload or a drawn one, and Frame it on a picture already there."""
    pic = pictures.find(db, o)
    shown = _shown(db, o)
    if pic is None or not pic.file_key or not shown:
        return _done(o, "Picture saved")
    x, y = o.centering
    f = pic.frame or {"x": x, "y": y, "zoom": 1.0}
    from app.entity_pages import SHAPES

    shape = SHAPES.get(o.entity.kind, "banner") if o.entity is not None else "square"  # (a creature's is square)
    out = templates.TemplateResponse(request, "_picture_frame.html", {"o": o, "shown": shown, "f": f, "new": new, "most": pictures.ZOOM_MAX,
                                                                       "shape": shape})
    out.headers["HX-Retarget"], out.headers["HX-Reswap"] = "[data-picture-window]", "outerHTML"
    return out


@router.get("/pictures/frame")
def framing(request: Request, db: Session = Depends(get_db)):
    o, _ = _owner(db, request, request.query_params.get("for", ""))
    return _framing(request, db, o)


@router.post("/pictures/frame")
def save_frame(request: Request, for_: str = Form("", alias="for"), x: float = Form(0.5), y: float = Form(0.5), zoom: float = Form(1.0),
               skip: str = Form(""), db: Session = Depends(get_db)):
    """Its middle and how far in (Save), or askdnd's own guess kept (Skip, after a new picture)."""
    o, _ = _owner(db, request, for_)
    if skip:
        return _done(o, "Picture saved")
    try:
        pictures.frame(db, o, x, y, zoom)
    except pictures.PictureError as e:
        raise HTTPException(409, str(e)) from None
    db.commit()
    return _done(o, "Picture framed")


@router.post("/pictures/ddb")
def use_ddb(request: Request, for_: str = Form("", alias="for"), db: Session = Depends(get_db)):
    o, user = _owner(db, request, for_)
    try:
        pictures.use_link(db, o, user)
    except pictures.PictureError as e:
        raise HTTPException(409, str(e)) from None
    db.commit()
    return _done(o, "D&D Beyond's art, as its picture")


@router.post("/pictures/remove")
def remove(request: Request, for_: str = Form("", alias="for"), db: Session = Depends(get_db)):
    o, _ = _owner(db, request, for_)
    pictures.remove(db, o)
    db.commit()
    return _done(o, "Picture removed")


@router.get("/characters/{character_id:int}/creatures/{creature}/picture")
def creature_picture(request: Request, character_id: int, creature: str, size: str = "full", db: Session = Depends(get_db)):
    """A creature's picture, for anyone at its table (like the World's pictures)."""
    user = current_user(request)
    ch = db.get(Character, character_id)
    from app import hit_points

    if not user or ch is None or not (hit_points.can_apply(db, user, ch) or access.role(user.get("email"), ch.campaign_id)):
        return Response(status_code=404)
    pic = db.scalar(select(EntityPicture).where(EntityPicture.character_id == character_id, EntityPicture.creature == creature))
    if pic is None or not pic.file_key:
        return Response(status_code=404)
    return pictures.serve(db, pic, size)


# ------------------------------------------------------------------ the campaign's art style (Manage › Settings)


@router.post("/manage/settings/art-style")
def save_style(request: Request, words: str = Form(""), refs: list[str] = Form([]), off: str = Form(""), db: Session = Depends(get_db)):
    """Its DM or an admin: the words, up to four of the campaign's own pictures to match, and whether Describe it is on."""
    from app.auth import can_edit_settings

    user = current_user(request)
    campaign = web.campaign(db)
    if campaign is None or not can_edit_settings(user):
        raise HTTPException(404)
    mine = {p.id for p in db.scalars(select(EntityPicture).where(EntityPicture.file_key.is_not(None)))
            if (p.entity_id and _campaign_of_entity(db, p.entity_id) == campaign.id)
            or (p.character_id and (c := db.get(Character, p.character_id)) and c.campaign_id == campaign.id)}
    faces = {f"{drawing.PORTRAIT}{c.id}" for c, _ in _portraits(db, campaign)}
    picked = [int(r) if r.isdigit() else r for r in refs if (r.isdigit() and int(r) in mine) or r in faces][: drawing.REFS]
    campaign.art_style = {"words": " ".join(words.split())[:600], "refs": picked, "off": bool(off)}
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": "Art style saved"})})


def _campaign_of_entity(db: Session, entity_id: int) -> int | None:
    from app.models import Entity

    e = db.get(Entity, entity_id)
    return e.campaign_id if e else None


def _portraits(db: Session, campaign: Campaign) -> list[tuple[Character, str]]:
    """The campaign's characters with a portrait on D&D Beyond (its image server only), as (character, its address)."""
    from app import characters

    out = []
    for c in characters.campaign_characters(db, campaign.id):
        url = ((characters.character_summary(c) or {}).get("portrait") or "") if c.copy_of_id is None else ""
        if url:
            out.append((c, url))
    return out


def style_choices(db: Session, campaign: Campaign) -> list[dict]:
    """The campaign's own pictures, for Art style's pictures to match: {"id", "thumb", "name", "on"}; then each character's
    D&D Beyond portrait (feedback 16, Brett, Nov 5), a link to D&D Beyond's picture, fetched only when something is drawn."""
    from app.models import Entity

    on = set(drawing.style(campaign)["refs"])
    out = []
    for p in db.scalars(select(EntityPicture).where(EntityPicture.file_key.is_not(None)).order_by(EntityPicture.id)):
        if p.entity_id:
            e = db.get(Entity, p.entity_id)
            if e is None or e.campaign_id != campaign.id:
                continue
            out.append({"id": p.id, "thumb": f"/campaign/{e.id}/picture?size=thumb&v={files.version(p.thumb_key)}", "name": e.name, "on": p.id in on})
        elif p.character_id:
            c = db.get(Character, p.character_id)
            if c is None or c.campaign_id != campaign.id:
                continue
            out.append({"id": p.id, "thumb": f"/characters/{c.id}/creatures/{p.creature}/picture?size=thumb&v={files.version(p.thumb_key)}",
                        "name": f"{c.name}'s {p.creature}", "on": p.id in on})
    for c, url in _portraits(db, campaign):
        key = f"{drawing.PORTRAIT}{c.id}"
        out.append({"id": key, "thumb": url, "name": f"{c.name}, from D&D Beyond", "on": key in on})
    return out
