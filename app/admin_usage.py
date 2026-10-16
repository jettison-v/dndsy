"""Admin: what askdnd has spent on Claude, and an estimated credit balance."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import _guard
from app.db import get_db
from app.extraction import session_label
from app.models import CreditTopUp, ExtractionRun, GameSession
from app.templating import templates

router = APIRouter(prefix="/admin")


def _spent(db: Session, since: datetime | None = None) -> float:
    q = select(func.coalesce(func.sum(ExtractionRun.cost_usd), 0.0))
    if since is not None:
        q = q.where(ExtractionRun.created_at >= since)
    return float(db.scalar(q) or 0.0)


def usage_summary(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    bought = float(db.scalar(select(func.coalesce(func.sum(CreditTopUp.amount_usd), 0.0))) or 0.0)
    total = _spent(db)
    done = db.scalar(select(func.count()).select_from(ExtractionRun).where(ExtractionRun.status == "done")) or 0
    return {
        "today": _spent(db, today),
        "month": _spent(db, month),
        "total": total,
        "bought": bought,
        "balance": bought - total if bought else None,
        "average": total / done if done else None,
        "drafts": done,
    }


@router.get("/usage")
def usage_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    runs = list(db.scalars(select(ExtractionRun).order_by(ExtractionRun.id.desc()).limit(100)))
    sessions = {s.id: s for s in db.scalars(select(GameSession).where(GameSession.id.in_({r.session_id for r in runs})))}
    rows = [{"r": r, "label": session_label(sessions[r.session_id]) if r.session_id in sessions else "—"} for r in runs]
    topups = list(db.scalars(select(CreditTopUp).order_by(CreditTopUp.added_on.desc())))
    return templates.TemplateResponse(
        request,
        "admin_usage.html",
        {"u": usage_summary(db), "rows": rows, "topups": topups, "today_iso": date.today().isoformat(), "toast": request.session.pop("toast", None)},
    )


@router.post("/usage/topups")
def add_topup(request: Request, amount: float = Form(...), added_on: date = Form(...), note: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    if amount <= 0 or amount > 10_000:
        request.session["toast"] = "Enter an amount between $0 and $10,000."
    else:
        db.add(CreditTopUp(amount_usd=round(amount, 2), added_on=added_on, note=note.strip()[:200]))
        db.commit()
        request.session["toast"] = f"Added ${amount:,.2f}"
    return RedirectResponse("/admin/usage", status_code=303)


@router.post("/usage/topups/{topup_id}/delete")
def delete_topup(request: Request, topup_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    t = db.get(CreditTopUp, topup_id)
    if t:
        db.delete(t)
        db.commit()
        request.session["toast"] = "Removed"
    return RedirectResponse("/admin/usage", status_code=303)
