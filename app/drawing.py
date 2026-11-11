"""Pictures drawn from a description (the Picture window's Describe it; Brett, 2026-11-04, docs/mockups/pictures/): OpenAI's
GPT Image draws four, in the campaign's art style (Campaign.art_style: a few words, and up to four of the campaign's own
pictures to match), and the person picks one. Claude doesn't draw pictures.

Only the words for that picture, the style's words and its pictures are sent: never a transcript, notes or anything else
of the campaign. Every drawing is counted on Manage › Usage (an ExtractionRun of source "picture", at an estimated cost)
and refused once the monthly limit is reached, like every Claude call. Each of the four is resized and kept in file
storage at once (app/files.py); the ones not chosen are swept like any file nothing uses.

Needs OPENAI_API_KEY (scripts/set-secret.sh); OPENAI_IMAGE_MODEL names the model (OpenAI's names change often)."""

import base64
import json
import os
import secrets
import urllib.error
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import pictures, spending
from app.models import Campaign, EntityPicture, ExtractionRun

API = "https://api.openai.com/v1/images"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare")
COST = float(os.getenv("OPENAI_IMAGE_COST_USD", "0.04"))  # an estimate per picture, for Usage and the monthly limit
HOW_MANY = 4  # (Brett, Nov 4: four to pick from)
REFS = 4  # pictures to match, at most
PORTRAIT = "portrait:"  # a picture to match that's a character's D&D Beyond portrait ("portrait:<character id>"; feedback 16)
PLAIN = "A clean fantasy illustration, soft light, a plain background, no text or lettering in the picture."
FETCH = None  # tests replace it: (path, fields, files) -> OpenAI's JSON answer


def key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def style(campaign: Campaign | None) -> dict:
    """The campaign's art style: {"words", "refs", "off"}."""
    return {"words": "", "refs": [], "off": False, **((campaign.art_style if campaign else None) or {})}


def why_not(db: Session, campaign: Campaign | None) -> str:
    """Why Describe it can't draw now, or ""."""
    if style(campaign)["off"]:
        return "Describe it is switched off for this campaign (Manage › Settings › Art style)."
    if not key():
        return "Describe it isn't set up yet: askdnd needs an OpenAI key (an admin's step)."
    return spending.reached(db) or ""


def _post(path: str, fields: dict, files: list[tuple[str, bytes]]) -> dict:
    """OpenAI's Images API: JSON for a drawing from words alone, a multipart form when pictures go with it."""
    if FETCH is not None:
        return FETCH(path, fields, files)
    headers = {"Authorization": f"Bearer {key()}"}
    if files:
        boundary = "askdnd" + secrets.token_hex(8)
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for i, (name, data) in enumerate(files):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="{i}-{name}"\r\n'
                         f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        body, headers["Content-Type"] = json.dumps(fields).encode(), "application/json"
    req = urllib.request.Request(f"{API}/{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read()).get("error", {}).get("message", "")
        except ValueError:
            said = ""
        raise pictures.PictureError(f"OpenAI didn't draw it ({e.code}{': ' + said[:200] if said else ''}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise pictures.PictureError("OpenAI couldn't be reached. Try again in a moment.") from None


def _portrait(db: Session, character_id: str) -> bytes | None:
    """A character's portrait from D&D Beyond's image server, read when it's drawn and never kept (D&D Beyond's art stays
    a link). None when it can't be had: drawing goes on without it."""
    from app import characters
    from app.models import Character

    c = db.get(Character, int(character_id)) if character_id.isdigit() else None
    url = (characters.character_summary(c) or {}).get("portrait") if c else ""
    if not url:
        return None
    try:
        return READ_PORTRAIT(url)
    except Exception:
        return None


PORTRAIT_HOSTS = ("www.dndbeyond.com", "media.dndbeyond.com")  # (only D&D Beyond's own image server, as with token art)


def _theirs(url: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse(url or "")
    return u.scheme == "https" and (u.hostname or "") in PORTRAIT_HOSTS


class _OnlyTheirs(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _theirs(newurl):
            raise ValueError("A portrait is read only from D&D Beyond.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read(url: str) -> bytes:
    """A character's D&D Beyond portrait. The address comes from the sheet, which its player writes, so it's read only
    from D&D Beyond's own hosts, redirects included (the outside review's W3, Nov 10): never another site, never askdnd's
    own network."""
    if not _theirs(url):
        raise ValueError("A portrait is read only from D&D Beyond.")
    req = urllib.request.Request(url, headers={"User-Agent": "askdnd"})
    with urllib.request.build_opener(_OnlyTheirs).open(req, timeout=15) as r:
        return r.read(8_000_000)


READ_PORTRAIT = _read  # tests replace it


def _png(raw: bytes) -> bytes:
    """A picture to match, as PNG (what the edits endpoint takes)."""
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, "PNG")
    return out.getvalue()


def _guide(db: Session, entity) -> bytes | None:
    """An entry's picture to send along: its own (uploaded or drawn), else its character's D&D Beyond portrait."""
    from app.models import CampaignCharacter

    p = db.scalar(select(EntityPicture).where(EntityPicture.entity_id == entity.id))
    if p is not None and p.file_key:
        return pictures.files.read(p.file_key)
    cc = db.scalar(select(CampaignCharacter).where(CampaignCharacter.entity_id == entity.id).limit(1))
    return _portrait(db, str(cc.character_id)) if cc else None


def draw(db: Session, campaign: Campaign | None, words: str, frame: str = "scene", match: bool = False,
         like: list | None = None, refs_of: list | None = None) -> tuple[list[tuple[str, str]], str]:
    """Four pictures of `words` in the campaign's style, framed for what they're of (pictures.FRAMES: a portrait, the
    whole item…), each kept in file storage: ([(full key, thumb key)], the style's words). The caller lets go of the
    database first (OpenAI takes up to a minute). `like`: relatives to resemble; `refs_of`: entries named with @ to draw
    as they look (feedback 34, 36; entries pictures.usable checked); with the style's pictures, REFS in all."""
    words = " ".join((words or "").split())[:1000]
    if not words:
        raise pictures.PictureError("Say what it looks like first.")
    stop = why_not(db, campaign)
    if stop:
        raise pictures.PictureError(stop)
    st = style(campaign)
    look = st["words"].strip() or PLAIN
    refs, said = [], []  # who or what the first pictures show, then the Art style's
    for kind, e in [("like", e) for e in like or []] + [("ref", e) for e in refs_of or []]:
        data = _guide(db, e) if len(refs) < REFS else None
        if data:
            refs.append(("ref.png", _png(data)))
            said.append(f"Picture {len(refs)} shows {e.name}, family of this subject: give a clear family resemblance (face shape, "
                        "eyes, nose, skin and hair colour) while keeping a different person, with their own age and features as described."
                        if kind == "like" else f"Picture {len(refs)} shows {e.name} as it looks in this campaign: where it appears, draw it to match.")
    guided = len(refs)
    for pid in (st["refs"][:REFS - guided] if match else []):  # (only when asked to match them: Brett, Nov 6, everyone looked alike)
        if isinstance(pid, str) and pid.startswith(PORTRAIT):
            data = _portrait(db, pid[len(PORTRAIT):])
        else:
            p = db.get(EntityPicture, pid)
            data = pictures.files.read(p.file_key) if p and p.file_key else None
        if data:
            refs.append(("ref.png", _png(data)))
    framing, size, centering = pictures.FRAMES.get(frame, pictures.FRAMES["scene"])
    styling = len(refs) > guided
    prompt = f"{words}\n\n{framing}\n\nArt style for every picture in this campaign: {look}" + (
        "\n" + "\n".join(said) if said else "") + (
        ("\nUse the " + ("remaining " if said else "") + "pictures given only for their painting style: palette, brushwork and light. "
         "Don't copy any face, hair, body, clothing, pose or composition from them: this subject looks only as described above.") if styling else "")
    run = ExtractionRun(source="picture", model=MODEL, status="running")
    db.add(run)
    db.commit()  # (counted before the call; the database isn't held while OpenAI draws)
    fields = {"model": MODEL, "prompt": prompt, "n": HOW_MANY, "size": size}
    try:
        got = _post("edits" if refs else "generations", fields, refs)
        images = [base64.b64decode(d["b64_json"]) for d in got.get("data") or [] if d.get("b64_json")]
        if not images:
            raise pictures.PictureError("OpenAI sent no pictures back. Try again.")
        kept = []
        for raw in images:
            full, thumb = pictures.process(raw, centering)
            kept.append(pictures.keep(db, campaign.id if campaign else None, full, thumb))
        run.status, run.cost_usd = "done", COST * len(images)
    except pictures.PictureError as e:
        run.status, run.error = "error", str(e)[:500]
        db.commit()
        raise
    db.commit()
    return kept, look
