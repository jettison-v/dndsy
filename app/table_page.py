"""askdnd's table (VTT slice 1, docs/plans/2026-11-02-vtt-build-plan.md; VTT Layout › The first step): one page per
campaign at /c/<campaign>/table, the frame every slice fills in. The fight band across the top is the turn bar, Table
rolls on the left and the side panel on the right are the ones on every page, and the middle lists the fight's rows as
heard from D&D Beyond's VTT while the map stays there. Only where askdnd's VTT is on (app/vtt.py `vtt_table`: test
campaigns until Brett switches it on); refused everywhere else, so no one stumbles on it."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import vtt, web
from app.auth import current_user
from app.character_pages import party_rows
from app.db import get_db
from app.templating import templates

router = APIRouter()


@router.get("/table")
def table_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = web.campaign(db)
    if not vtt.on(campaign, "vtt_table"):
        return web.not_found(request, "There's no page at this address.")
    return templates.TemplateResponse(request, "table.html", {"campaign": campaign, "rows": party_rows(db, user),
                                                              "toast": request.session.pop("toast", None)})
