"""About and FAQ: how askdnd works, in plain words. Open to anyone (no campaign data).
Also the help lines on character pages (_help.html): one short line each, with "Got it" to hide it for
that person (remembered on their user row, so on every device) and "More" to the FAQ answer
(DESIGN.md › Components › Help line, Brett 2026-10-22)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.live import GAME_MODE_SECONDS
from app.templating import templates

router = APIRouter()

# Help line key -> the FAQ answer its "More" opens (_help_faq.html q(..., id=...))
HELP = {"battle": "modes", "sheet": "marks", "plan": "notes", "features": "modes", "situational": "modes",
        "background": "privacy", "spells": "spell-book", "forms": "wild-shape", "items": "items"}


def dismissed(db: Session, user: dict | None) -> set[str]:
    from app.picks import user_row

    me = user_row(db, user)
    return set(me.dismissed_help or []) if me else set()


@router.post("/help/dismiss")
def dismiss_help(request: Request, key: str = Form(...), db: Session = Depends(get_db)):
    """"Got it" on a help line: hidden for this person from now on. Returns nothing, so the line goes away."""
    from app.picks import user_row

    me = user_row(db, current_user(request))
    if me is None:
        return Response(status_code=403)
    if key not in HELP:
        return Response(status_code=400)
    me.dismissed_help = sorted(set(me.dismissed_help or []) | {key})
    db.commit()
    return HTMLResponse("")


@router.get("/help")
def help_page(request: Request, tab: str = "faq"):
    """FAQ and About in one page (Brett, 2026-10-23). /help#<id> opens that FAQ answer."""
    return templates.TemplateResponse(request, "help.html", {"tab": "about" if tab == "about" else "faq",
                                                             "game_mode_minutes": GAME_MODE_SECONDS / 60})


@router.get("/faq")
def faq():
    return RedirectResponse("/help", status_code=301)  # the browser keeps #<id>, so old answer links still open


@router.get("/about")
def about():
    return RedirectResponse("/help?tab=about", status_code=301)
