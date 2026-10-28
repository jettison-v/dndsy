"""About and FAQ: how askdnd works, in plain words. Open to anyone (no campaign data). Pages carry no help lines
(Brett, 2026-10-27): the tour and this page explain them."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.live import GAME_MODE_SECONDS
from app import tour
from app.templating import templates

router = APIRouter()


@router.get("/help")
def help_page(request: Request, tab: str = "faq", db: Session = Depends(get_db)):
    """What askdnd adds, FAQ and About in one page (Brett, 2026-10-23; the first tab 2026-10-26). /help#<id> opens that
    FAQ answer, so the FAQ stays the default."""
    from app import ddb_bridge  # (how long Game Mode lasts: an admin's setting)

    return templates.TemplateResponse(request, "help.html", {"tab": tab if tab in ("adds", "about") else "faq",
                                                             "sections": tour.SECTIONS,
                                                             "game_mode_minutes": GAME_MODE_SECONDS / 60,
                                                             "game_hours": f"{ddb_bridge.timers(db)['game'] / 3600:g}"})


@router.get("/tour")
def tour_stops(request: Request, db: Session = Depends(get_db)):
    """The tour's stops for the person asking (app/tour.py), for app.js to walk."""
    user = current_user(request)
    if not user:
        return Response(status_code=401)
    return JSONResponse({"stops": tour.stops_for(db, user)})
