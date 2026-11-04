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

from sqlalchemy.orm import Session

from app import pictures, spending
from app.models import Campaign, EntityPicture, ExtractionRun

API = "https://api.openai.com/v1/images"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare")
COST = float(os.getenv("OPENAI_IMAGE_COST_USD", "0.04"))  # an estimate per picture, for Usage and the monthly limit
HOW_MANY = 4  # (Brett, Nov 4: four to pick from)
REFS = 4  # pictures to match, at most
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


def _png(raw: bytes) -> bytes:
    """A picture to match, as PNG (what the edits endpoint takes)."""
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, "PNG")
    return out.getvalue()


def draw(db: Session, campaign: Campaign | None, words: str, frame: str = "scene") -> tuple[list[tuple[str, str]], str]:
    """Four pictures of `words` in the campaign's style, framed for what they're of (pictures.FRAMES: a portrait, the
    whole item…), each kept in file storage: ([(full key, thumb key)], the style's words). The caller lets go of the
    database first (OpenAI takes up to a minute)."""
    words = " ".join((words or "").split())[:1000]
    if not words:
        raise pictures.PictureError("Say what it looks like first.")
    stop = why_not(db, campaign)
    if stop:
        raise pictures.PictureError(stop)
    st = style(campaign)
    look = st["words"].strip() or PLAIN
    refs = []
    for pid in st["refs"][:REFS]:
        p = db.get(EntityPicture, pid)
        data = pictures.files.read(p.file_key) if p and p.file_key else None
        if data:
            refs.append(("ref.png", _png(data)))
    framing, size, centering = pictures.FRAMES.get(frame, pictures.FRAMES["scene"])
    prompt = f"{words}\n\n{framing}\n\nArt style for every picture in this campaign: {look}" + (
        "\nMatch the style (not the subjects) of the pictures given." if refs else "")
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
