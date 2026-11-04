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
    o, _ = _owner(db, request, request.query_params.get("for", for_))
    campaign = db.get(Campaign, o.campaign_id) if o.campaign_id else None
    pic = pictures.find(db, o)
    return templates.TemplateResponse(request, "_picture_window.html", {
        "o": o, "shown": _shown(db, o), "pic": pic, "style": drawing.style(campaign)["words"] or drawing.PLAIN,
        "styled": bool(drawing.style(campaign)["words"]), "no_drawing": drawing.why_not(db, campaign), "how_many": drawing.HOW_MANY,
        "words": pic.words if pic is not None and pic.source == "drawn" and pic.words else o.words})


@router.post("/pictures/upload")
def upload(request: Request, for_: str = Form("", alias="for"), file: UploadFile = File(...), db: Session = Depends(get_db)):
    o, user = _owner(db, request, for_)
    raw = file.file.read(pictures.MAX_UPLOAD + 1)
    try:
        pictures.save(db, o, raw, user)
    except pictures.PictureError as e:
        raise HTTPException(409, str(e)) from None
    db.commit()
    return _done(o, "Picture saved")


@router.post("/pictures/draw")
def draw(request: Request, for_: str = Form("", alias="for"), words: str = Form(""), db: Session = Depends(get_db)):
    """Describe it: four to pick from, drawn in the campaign's style (app/drawing.py)."""
    o, _ = _owner(db, request, for_)
    campaign = db.get(Campaign, o.campaign_id) if o.campaign_id else None
    try:
        kept, look = drawing.draw(db, campaign, words, o.frame)
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
    return _done(o, "Picture saved")


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
    picked = [int(r) for r in refs if r.isdigit() and int(r) in mine][: drawing.REFS]
    campaign.art_style = {"words": " ".join(words.split())[:600], "refs": picked, "off": bool(off)}
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": "Art style saved"})})


def _campaign_of_entity(db: Session, entity_id: int) -> int | None:
    from app.models import Entity

    e = db.get(Entity, entity_id)
    return e.campaign_id if e else None


def style_choices(db: Session, campaign: Campaign) -> list[dict]:
    """The campaign's own pictures, for Art style's pictures to match: {"id", "thumb", "name", "on"}."""
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
    return out
