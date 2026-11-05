"""Pictures in askdnd (Brett, 2026-11-04, docs/mockups/pictures/: one Picture window wherever a picture goes, one kind
of picture, one place): a World entry's (a person, place, faction, map) and one of a character's creatures' (a familiar
keeps one picture across its forms). Added in the one window (app/picture_window.py) by uploading, drawing from a
description (app/drawing.py) or taking D&D Beyond's art (a link, never copied). Uploads and drawings are checked,
resized and re-encoded with Pillow (which also strips camera metadata such as GPS), then kept in file storage
(app/files.py): up to 1200 px plus a square thumbnail. Whoever can change the thing can change its picture: the DM,
reviewers and admins for the World; a creature's master's player and the DM. Player characters keep their D&D Beyond
portrait.
"""

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app import access, files
from app.models import CampaignCharacter, Character, Entity, EntityPicture

MAX_UPLOAD = 15 * 1024 * 1024
FULL_SIZE, THUMB_SIZE = 1200, 320
ZOOM_MAX = 3.0  # (Frame it: up to three times in)
Image.MAX_IMAGE_PIXELS = 60_000_000  # bigger than any phone photo; refuses "decompression bombs"


class PictureError(Exception):
    pass


# What a picture is of decides how it's drawn and cut (Brett, 2026-11-04: "a weapon (showing the whole item) or a profile
# image (just showing the head)"): the framing added to a description, OpenAI's size for it, and where the square version
# is cut (faces sit high; anything else in the middle). One rule for every place a picture shows.
FRAMES = {
    "portrait": ("A head-and-shoulders portrait: the whole head and shoulders in frame, the face in the upper middle, "
                 "looking toward the viewer.", "1024x1024", (0.5, 0.35)),
    "creature": ("The whole creature, centred, seen from a little above eye level, nothing cut off.", "1024x1024", (0.5, 0.45)),
    "item": ("The whole object, centred and complete with nothing cut off, on a plain background, evenly lit.", "1024x1024", (0.5, 0.5)),
    "place": ("A wide view of the place at eye level, as a traveller first sees it; no people up close.", "1536x1024", (0.5, 0.5)),
    "faction": ("The group's emblem or banner, centred on a plain background.", "1024x1024", (0.5, 0.5)),
    "scene": ("A wide scene that shows what happens, with room around it.", "1536x1024", (0.5, 0.5)),
}
KIND_FRAMES = {"pc": "portrait", "npc": "portrait", "creature": "creature", "item": "item", "place": "place", "faction": "faction",
               "quest": "scene", "other": "scene"}


def can_manage(user: dict | None) -> bool:
    """The DM runs the story, so the DM adds pictures; so can reviewers and admins."""
    return bool(user) and access.allows("story_extras", access.level(user.get("email")), access.role(user.get("email")))


def process(raw: bytes, centering: tuple[float, float] = (0.5, 0.35)) -> tuple[bytes, bytes]:
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
    thumb = ImageOps.fit(img, (THUMB_SIZE, THUMB_SIZE), centering=centering)  # (FRAMES: faces sit high in portraits)

    def webp(im: Image.Image) -> bytes:
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()

    return webp(full), webp(thumb)


@dataclass
class Owner:
    """What a picture belongs to, as the Picture window names it (`ref`): "entity:<id>" or "creature:<character>:<id>"."""
    ref: str
    campaign_id: int | None
    name: str  # "Pip's picture"
    words: str  # what Describe it starts from
    ddb_art: str = ""  # D&D Beyond's art for it, if it has some
    entity: Entity | None = None
    character: Character | None = None
    creature: str | None = None  # "familiar", or a creature's D&D Beyond id
    frame: str = "scene"  # what it's a picture of (FRAMES)

    @property
    def framing(self) -> str:
        return FRAMES[self.frame][0]

    @property
    def size(self) -> str:
        return FRAMES[self.frame][1]

    @property
    def centering(self) -> tuple[float, float]:
        return FRAMES[self.frame][2]


def owner(db: Session, ref: str, user: dict | None) -> Owner | None:
    """The thing `ref` names, if it exists and this person may change its picture; else None."""
    from app import characters as chars
    from app import creatures, hit_points

    kind, _, rest = (ref or "").partition(":")
    if kind == "entity" and rest.isdigit():
        e = db.get(Entity, int(rest))
        email = (user or {}).get("email")
        if e is None or not can_manage(user) or (access.level(email) != access.ADMIN and access.current_campaign_id(email) != e.campaign_id):
            return None
        return Owner(ref, e.campaign_id, e.name, (f"{e.name}: {e.summary}" if e.summary else e.name)[:600], entity=e,
                     frame=KIND_FRAMES.get(str(e.kind), "scene"))
    if kind == "creature":
        cid, _, crid = rest.partition(":")
        ch = db.get(Character, int(cid)) if cid.isdigit() else None
        if ch is None or not hit_points.can_apply(db, user, ch):
            return None
        c = next((x for x in creatures.yours(chars.character_summary(ch)) if str(x["id"]) == crid), None)
        if c is None:
            return None
        k = creatures.placed(ch, creatures.card(chars.character_summary(ch), c), c)
        what = f"a {k['made'].lower()} {k['kind'].lower()}" if k["made"] else f"a {k['kind'].lower()}"
        return Owner(ref, ch.campaign_id, f"{k['name']}'s picture", f"{k['name']}, {ch.name}'s {k['role']}: {what}",
                     ddb_art=c.get("picture") or "", character=ch, creature=creature_key(c), frame="creature")
    return None


def creature_key(c: dict) -> str:
    """A familiar keeps one picture across its forms; another creature has its own."""
    from app.creatures import FAMILIAR

    return "familiar" if c.get("group_id") == FAMILIAR else str(c["id"])


def find(db: Session, o: Owner) -> EntityPicture | None:
    if o.entity is not None:
        return db.scalar(select(EntityPicture).where(EntityPicture.entity_id == o.entity.id))
    return db.scalar(select(EntityPicture).where(EntityPicture.character_id == o.character.id, EntityPicture.creature == o.creature))


def _row(db: Session, o: Owner, user: dict) -> EntityPicture:
    pic = find(db, o)
    if pic is None:
        pic = EntityPicture(entity_id=o.entity.id if o.entity is not None else None,
                            character_id=o.character.id if o.character is not None else None, creature=o.creature)
        db.add(pic)
    pic.added_by = (user.get("email") or "")[:320]
    return pic


def keep(db: Session, campaign_id: int | None, full: bytes, thumb: bytes) -> tuple[str, str]:
    """Both sizes into file storage: their keys."""
    try:
        return files.put(db, campaign_id, full, "image/webp"), files.put(db, campaign_id, thumb, "image/webp")
    except files.StorageNotReady:
        raise PictureError("askdnd can't keep pictures right now (its file storage isn't set up).") from None


def square(full: bytes, x: float, y: float, zoom: float) -> bytes:
    """The square version cut around a picture's middle (`x`, `y` as fractions) at `zoom`, as WebP: the Frame it step."""
    img = Image.open(io.BytesIO(full))
    img.load()
    w, h = img.size
    side = max(1, round(min(w, h) / max(1.0, zoom)))
    left = min(max(0, round(x * w - side / 2)), w - side)
    top = min(max(0, round(y * h - side / 2)), h - side)
    out = io.BytesIO()
    img.crop((left, top, left + side, top + side)).resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS).save(out, "WEBP", quality=82, method=4)
    return out.getvalue()


def frame(db: Session, o: Owner, x: float, y: float, zoom: float) -> EntityPicture:
    """Its middle and how far in, kept with the picture; the square version cut again around it. Only a picture askdnd
    keeps (D&D Beyond's art is a link: D&D Beyond frames it)."""
    pic = find(db, o)
    full = files.read(pic.file_key) if pic is not None and pic.file_key else None
    if full is None:
        raise PictureError("Only a picture askdnd keeps can be framed.")
    x, y = (min(1.0, max(0.0, float(v))) for v in (x, y))
    zoom = min(ZOOM_MAX, max(1.0, float(zoom)))
    thumb = square(full, x, y, zoom)
    try:
        pic.thumb_key = files.put(db, o.campaign_id, thumb, "image/webp")
    except files.StorageNotReady:
        raise PictureError("askdnd can't keep pictures right now (its file storage isn't set up).") from None
    pic.frame = {"x": round(x, 4), "y": round(y, 4), "zoom": round(zoom, 3)}
    return pic


def save(db: Session, o: Owner, raw: bytes, user: dict) -> EntityPicture:
    """An uploaded picture, checked and resized."""
    full, thumb = process(raw, o.centering)
    file_key, thumb_key = keep(db, o.campaign_id, full, thumb)
    pic = _row(db, o, user)
    pic.file_key, pic.thumb_key, pic.content_type, pic.source, pic.words, pic.style, pic.link = file_key, thumb_key, "image/webp", "upload", "", "", ""
    pic.frame = None
    return pic


def use_drawn(db: Session, o: Owner, file_key: str, thumb_key: str, words: str, style: str, user: dict) -> EntityPicture:
    """One of the pictures drawn from a description (already in file storage, app/drawing.py)."""
    pic = _row(db, o, user)
    pic.file_key, pic.thumb_key, pic.content_type, pic.source, pic.words, pic.style, pic.link = file_key, thumb_key, "image/webp", "drawn", words[:2000], style[:2000], ""
    pic.frame = None
    return pic


def use_link(db: Session, o: Owner, user: dict) -> EntityPicture:
    """D&D Beyond's art for it: shown from D&D Beyond, never copied."""
    if not o.ddb_art:
        raise PictureError("D&D Beyond has no art for this.")
    pic = _row(db, o, user)
    pic.file_key = pic.thumb_key = pic.frame = None
    pic.source, pic.link, pic.words, pic.style = "ddb", o.ddb_art[:500], "", ""
    return pic


def serve(db: Session, pic: EntityPicture, size: str = "full"):
    """The picture (or its thumbnail) for a route that has checked who may see it. The database connection goes back
    before the download (files.serve `release`)."""
    if size == "thumb":
        return files.serve(pic.thumb_key, pic.content_type, release=db)
    return files.serve(pic.file_key, pic.content_type, release=db)


def remove(db: Session, o: Owner) -> None:
    pic = find(db, o)
    if pic:
        db.delete(pic)


def _urls(p: EntityPicture, base: str) -> dict:
    if p.source == "ddb" or not p.file_key:
        return {"thumb": p.link, "full": ddb_full(p.link), "uploaded": True, "source": "ddb"}
    # ?v= changes with the picture, so the browser keeps each copy for good (files.CACHE_FOREVER)
    f = p.frame or {}
    return {"thumb": f"{base}?size=thumb&v={files.version(p.thumb_key)}", "full": f"{base}?v={files.version(p.file_key)}",
            "uploaded": True, "source": p.source,
            # where a wide band shows it from (object-position): its middle, once framed
            "pos": f"{f['x'] * 100:.1f}% {f['y'] * 100:.1f}%" if f else ""}


def creature_urls(db: Session, character_ids) -> dict[tuple[int, str], dict]:
    """{(character id, creature key): {"thumb", "full", "source"}} for the characters' creatures that have a picture."""
    ids = set(character_ids)
    if not ids:
        return {}
    return {(p.character_id, p.creature): _urls(p, f"/characters/{p.character_id}/creatures/{p.creature}/picture")
            for p in db.scalars(select(EntityPicture).where(EntityPicture.character_id.in_(ids)))}


def ddb_full(url: str) -> str:
    """D&D Beyond portrait URLs ask for a 150 px crop; without the query it's the original."""
    return url.split("?", 1)[0] if url else ""


def urls(db: Session, entity_ids) -> dict[int, dict]:
    """{entity_id: {"thumb", "full", "uploaded"}} for the entities that have a picture."""
    ids = set(entity_ids)
    if not ids:
        return {}
    out = {}
    for m in db.scalars(select(CampaignCharacter).where(CampaignCharacter.entity_id.in_(ids))):
        snap = m.character.snapshot
        portrait = ((snap.summary or {}) if snap else {}).get("portrait")
        if portrait:
            out[m.entity_id] = {"thumb": portrait, "full": ddb_full(portrait), "uploaded": False}
    pics = db.scalars(select(EntityPicture).where(EntityPicture.entity_id.in_(ids))
                      .options(load_only(EntityPicture.entity_id, EntityPicture.file_key, EntityPicture.thumb_key, EntityPicture.source, EntityPicture.link)))
    for p in pics:
        out[p.entity_id] = _urls(p, f"/campaign/{p.entity_id}/picture")
    return out
