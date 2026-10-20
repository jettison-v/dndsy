"""About and FAQ: how askdnd works, in plain words. Open to anyone (no campaign data)."""

from fastapi import APIRouter, Request

from app.live import GAME_MODE_SECONDS
from app.templating import templates

router = APIRouter()


@router.get("/about")
def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})


@router.get("/faq")
def faq(request: Request):
    return templates.TemplateResponse(request, "faq.html", {"game_mode_minutes": GAME_MODE_SECONDS / 60})
