"""Pictures for people, places, factions and everything else in the campaign record.

The DM, reviewers and admins add them from an entity page. Uploads are checked,
resized and re-encoded with Pillow (which also strips camera metadata such as
GPS), then stored in the database: one picture per entity, up to 1200 px plus a
square thumbnail. Player characters without an uploaded picture use their
D&D Beyond portrait.
"""

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app import access
from app.auth import is_reviewer
from app.models import Character, Entity, EntityPicture

MAX_UPLOAD = 15 * 1024 * 1024
FULL_SIZE, THUMB_SIZE = 1200, 320
Image.MAX_IMAGE_PIXELS = 60_000_000  # bigger than any phone photo; refuses "decompression bombs"


class PictureError(Exception):
    pass


def can_manage(user: dict | None) -> bool:
    """The DM runs the story, so the DM adds pictures; so can reviewers and admins."""
    return bool(user) and (is_reviewer(user) or access.is_dm(user.get("email")))


def process(raw: bytes) -> tuple[bytes, bytes]:
    """(full, thumb) as WebP, or PictureError with a message for the person uploading."""
    if not raw:
        raise PictureError("Choose a picture first.")
    if len(raw) > MAX_UPLOAD:
        raise PictureError("That picture is over 15 MB. Try a smaller one.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError):
        raise PictureError("That file isn't a picture askdnd can read (JPEG, PNG, WebP or GIF work).") from None
    img = ImageOps.exif_transpose(img)  # phone photos come sideways otherwise
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    full = img.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE))
    thumb = ImageOps.fit(img, (THUMB_SIZE, THUMB_SIZE), centering=(0.5, 0.35))  # faces sit high in most portraits

    def webp(im: Image.Image) -> bytes:
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()

    return webp(full), webp(thumb)


def save(db: Session, entity: Entity, raw: bytes, user: dict) -> EntityPicture:
    full, thumb = process(raw)
    pic = db.scalar(select(EntityPicture).where(EntityPicture.entity_id == entity.id))
    if pic is None:
        pic = EntityPicture(entity_id=entity.id)
        db.add(pic)
    pic.data, pic.thumb, pic.content_type, pic.added_by = full, thumb, "image/webp", (user.get("email") or "")[:320]
    return pic


def remove(db: Session, entity: Entity) -> None:
    pic = db.scalar(select(EntityPicture).where(EntityPicture.entity_id == entity.id))
    if pic:
        db.delete(pic)


def ddb_full(url: str) -> str:
    """D&D Beyond portrait URLs ask for a 150 px crop; without the query it's the original."""
    return url.split("?", 1)[0] if url else ""


def urls(db: Session, entity_ids) -> dict[int, dict]:
    """{entity_id: {"thumb", "full", "uploaded"}} for the entities that have a picture."""
    ids = set(entity_ids)
    if not ids:
        return {}
    out = {}
    for ch in db.scalars(select(Character).where(Character.entity_id.in_(ids))):
        portrait = ((ch.snapshot.summary or {}) if ch.snapshot else {}).get("portrait")
        if portrait:
            out[ch.entity_id] = {"thumb": portrait, "full": ddb_full(portrait), "uploaded": False}
    pics = db.scalars(select(EntityPicture).where(EntityPicture.entity_id.in_(ids))
                      .options(load_only(EntityPicture.entity_id, EntityPicture.updated_at)))
    for p in pics:
        v = int(p.updated_at.timestamp()) if p.updated_at else 0
        base = f"/campaign/{p.entity_id}/picture"
        out[p.entity_id] = {"thumb": f"{base}?size=thumb&v={v}", "full": f"{base}?v={v}", "uploaded": True}
    return out
