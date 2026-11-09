"""The Inbox digest (Brett, Nov 9; docs/mockups/inbox-email/, he chose B and A): one email a day, at DIGEST_HOUR in the
table's time, to each person who gets it for a campaign, only when something new reached that campaign's Inbox since
their last one. Counts and a link only: never a word of a suggestion, a draft or the story, never a player's name (an
email can be forwarded or kept by the mail service; the Inbox itself stays behind sign-in).

- **Who**: the campaign's DM, unless they turn it off; its reviewers and askdnd's admins only if they turn it on
  (Your account › Email). Players never: their news is on Your notes.
- **What counts**: suggestions from the table (facts and session or glossary suggestions still waiting) made since
  the last digest, and Claude's description drafts made since then (app/suggestions.py, the Inbox's own lists).
- **Sent by Resend** (RESEND_API_KEY; from EMAIL_FROM, askdnd.ai's own address), where the key is set and never on
  staging. Each email carries a one-click stop link (a signed token, no sign-in needed) and the List-Unsubscribe
  headers mail apps show as their own Unsubscribe.
- **Once a day**: a loop with the app checks every few minutes; past DIGEST_HOUR each person's campaign is looked at
  once that day (`User.emails["checked"]`), whatever it found, so later arrivals wait for tomorrow's. One copy of the
  app at a time (a Postgres advisory lock), as app/unwatched.py.
"""

import asyncio
import json
import logging
import urllib.request
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, web
from app.auth import current_user, is_admin
from app.companion_story import TABLE_TIME
from app.db import get_db
from app.models import Campaign, CampaignMember, Entity, Fact, Role, Suggestion, User
from app.templating import templates

router = APIRouter()
log = logging.getLogger(__name__)

LOCK = 72_042_011  # (app/unwatched.py has its own)
TICK = 600  # seconds between looks (the hour is what matters, not the minute)
RESEND = "https://api.resend.com/emails"


def enabled() -> bool:
    return bool(config.RESEND_API_KEY) and not config.STAGING


# ------------------------------------------------------------------ who gets it

def wants(user: User, campaign_id: int, role: str | None, admin: bool) -> bool:
    """Whether this person gets the campaign's digest: their own choice, else on for its DM, off for anyone else."""
    choice = ((user.emails or {}).get("inbox") or {}).get(str(campaign_id))
    if role not in (Role.DM, Role.REVIEWER) and not admin:
        return False  # (players never)
    return bool(choice) if choice is not None else role == Role.DM


def may_choose(db: Session, user: User) -> list[tuple[Campaign, str | None, bool]]:
    """The campaigns this person could get a digest for: [(campaign, their role there, on now)]."""
    from app import access

    admin = access.level(user.email) == "admin"
    roles = {m.campaign_id: m.role for m in db.scalars(select(CampaignMember).where(CampaignMember.user_id == user.id, CampaignMember.left_on.is_(None)))}
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.is_test.is_(False)).order_by(Campaign.id)):
        role = roles.get(c.id)
        if admin or role in (Role.DM, Role.REVIEWER):
            out.append((c, role, wants(user, c.id, role, admin)))
    return out


def recipients(db: Session, campaign: Campaign) -> list[User]:
    from app import access

    rows = db.execute(select(User, CampaignMember.role).outerjoin(CampaignMember, (CampaignMember.user_id == User.id)
                      & (CampaignMember.campaign_id == campaign.id) & CampaignMember.left_on.is_(None))).all()
    return [u for u, role in rows if access.level(u.email) and wants(u, campaign.id, role, access.level(u.email) == "admin")]


# ------------------------------------------------------------------ what it says

def waiting(db: Session, campaign_id: int, since: datetime) -> dict[str, int]:
    """What reached the campaign's Inbox since then: from the table, and Claude's drafts for an OK."""
    facts = db.scalar(select(func.count()).select_from(Fact).join(Entity, Fact.entity_id == Entity.id)
                      .where(Entity.campaign_id == campaign_id, Fact.status == "pending", Fact.created_at > since)) or 0
    sugg = db.scalar(select(func.count()).select_from(Suggestion).where(Suggestion.campaign_id == campaign_id, Suggestion.status == "pending",
                                                                        Suggestion.target_type.in_(("session", "glossary")), Suggestion.created_at > since)) or 0
    drafts = db.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == campaign_id, Entity.draft_summary.is_not(None),
                                                                      Entity.updated_at > since)) or 0
    return {"table": facts + sugg, "drafts": drafts}


def _stopper() -> URLSafeSerializer:
    return URLSafeSerializer(config.SESSION_SECRET, salt="email-stop")


def stop_link(user: User, campaign: Campaign) -> str:
    return f"{config.PROD_URL}/email/stop?t={_stopper().dumps([user.id, campaign.id])}"


def compose(campaign: Campaign, counts: dict[str, int], user: User, role: str | None) -> dict:
    """The email: subject, HTML and plain text. Counts and a link only."""
    total = counts["table"] + counts["drafts"]
    title = f"{total} new {'thing' if total == 1 else 'things'} in the Inbox"
    rows = [("From the table", counts["table"]), ("Claude's drafts for your OK", counts["drafts"])]
    rows = [r for r in rows if r[1]]
    why = "You get this as the campaign's DM." if role == Role.DM else "You turned this on in Your account › Email."
    link = f"{config.PROD_URL}/c/{campaign.slug}/manage/inbox"
    stop = stop_link(user, campaign)
    html = templates.get_template("email/digest.html").render(campaign=campaign, title=title, rows=rows, link=link, why=why, stop=stop)
    text = "\n".join([f"{campaign.name}: {title}", "", *[f"- {w}: {n}" for w, n in rows], "", f"Open the Inbox: {link}", "",
                      f"{why} Stop these emails: {stop}"])
    return {"subject": f"{campaign.name}: {title}", "html": html, "text": text, "stop": stop}


def _resend(to: str, mail: dict) -> bool:
    body = json.dumps({"from": config.EMAIL_FROM, "to": [to], "subject": mail["subject"], "html": mail["html"], "text": mail["text"],
                       "headers": {"List-Unsubscribe": f"<{mail['stop']}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}).encode()
    req = urllib.request.Request(RESEND, data=body, method="POST", headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                                                                           "Content-Type": "application/json", "User-Agent": "askdnd"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 (Resend's own address, above)
        return 200 <= r.status < 300


SEND = _resend  # (tests replace it)


# ------------------------------------------------------------------ once a day

def run_day(db: Session, now: datetime | None = None) -> list[tuple[str, str]]:
    """Past DIGEST_HOUR in the table's time: each person's campaigns not yet looked at today, an email where something
    is new. Returns [(email, campaign name)] sent."""
    now = now or datetime.now(UTC)
    local = now.astimezone(TABLE_TIME)
    if local.hour < config.DIGEST_HOUR:
        return []
    today, sent = local.date().isoformat(), []
    for campaign in db.scalars(select(Campaign).where(Campaign.is_test.is_(False))):
        roles = {m.user_id: m.role for m in db.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign.id,
                                                                                    CampaignMember.left_on.is_(None)))}
        for user in recipients(db, campaign):
            e = dict(user.emails or {})
            cid = str(campaign.id)
            if (e.get("checked") or {}).get(cid) == today:
                continue
            last = (e.get("at") or {}).get(cid)
            since = datetime.fromisoformat(last) if last else now - timedelta(days=1)
            counts = waiting(db, campaign.id, since)
            if counts["table"] + counts["drafts"]:
                try:
                    ok = SEND(user.email, compose(campaign, counts, user, roles.get(user.id)))
                except Exception:  # noqa: BLE001 - Resend away for a moment: the next look tries again
                    log.warning("The Inbox digest didn't go out this time", exc_info=True)
                    continue
                if not ok:
                    continue
                e["at"] = {**(e.get("at") or {}), cid: now.isoformat()}
                sent.append((user.email, campaign.name))
            e["checked"] = {**(e.get("checked") or {}), cid: today}
            user.emails = e
    db.commit()
    return sent


def run_once() -> list[tuple[str, str]]:
    from app.db import SessionLocal, engine

    with engine.connect() as hold:
        got = hold.execute(select(func.pg_try_advisory_lock(LOCK))).scalar()
        hold.commit()
        if not got:
            return []
        try:
            with SessionLocal() as db:
                return run_day(db)
        finally:
            hold.execute(select(func.pg_advisory_unlock(LOCK)))
            hold.commit()


async def loop() -> None:
    """Started with the app (app/main.py) where email is set up: a look every TICK seconds, never stopping on an error."""
    while True:
        await asyncio.sleep(TICK)
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # noqa: BLE001 - the database away for a moment: the next look tries again
            log.warning("The Inbox digest's look failed this time", exc_info=True)


# ------------------------------------------------------------------ Your account › Email, and the stop link

def _me(db: Session, request: Request) -> User | None:
    user = current_user(request)
    return db.scalar(select(User).where(User.email == user["email"].lower())) if user else None


def _set(user: User, campaign_id: int, on: bool) -> None:
    e = dict(user.emails or {})
    e["inbox"] = {**(e.get("inbox") or {}), str(campaign_id): on}
    user.emails = e


@router.get("/email")
def settings(request: Request, db: Session = Depends(get_db)):
    """Your account › Email: the campaigns you could get the Inbox digest for, each a switch."""
    me = _me(db, request)
    if me is None:
        return HTMLResponse("", status_code=401)
    return templates.TemplateResponse(request, "_email_settings.html", {"rows": may_choose(db, me), "hour": config.DIGEST_HOUR,
                                                                        "sending": enabled()})


@router.post("/email/inbox")
def choose(request: Request, campaign: int = Form(...), on: str = Form(""), db: Session = Depends(get_db)):
    me = _me(db, request)
    if me is None or campaign not in {c.id for c, _, _ in may_choose(db, me)}:
        return HTMLResponse("", status_code=403)
    _set(me, campaign, on == "1")
    db.commit()
    resp = templates.TemplateResponse(request, "_email_settings.html", {"rows": may_choose(db, me), "only_rows": True})
    resp.headers["HX-Trigger"] = json.dumps({"toast": "Inbox digest " + ("on" if on == "1" else "off")})
    return resp


def _stop(db: Session, t: str) -> tuple[User, Campaign] | None:
    try:
        uid, cid = _stopper().loads(t)
    except (BadSignature, ValueError, TypeError):
        return None
    user, campaign = db.get(User, uid), db.get(Campaign, cid)
    if not user or not campaign:
        return None
    _set(user, campaign.id, False)
    db.commit()
    return user, campaign


@router.get("/email/stop")
def stop_page(request: Request, t: str = "", db: Session = Depends(get_db)):
    """The email's own link: no sign-in, the signed token says who and which campaign."""
    done = _stop(db, t)
    if not done:
        return web.message(request, "That link doesn't work", "It may be from another copy of askdnd. Your account › Email turns the digest off.", 400)
    return web.message(request, "No more Inbox emails", f"You won't get {done[1].name}'s Inbox digest any more. Your account › Email turns it back on.")


@router.post("/email/stop")
def stop_one_click(t: str = "", db: Session = Depends(get_db)):
    """A mail app's own Unsubscribe (List-Unsubscribe-Post): the same, with no page."""
    return Response(status_code=200 if _stop(db, t) else 400)


@router.get("/email/preview")
def preview(request: Request, db: Session = Depends(get_db)):
    """Admins: this campaign's digest as it would look now (the last week's arrivals), to try it without sending."""
    user = current_user(request)
    if not is_admin(user):
        return web.forbidden(request, "Only admins can preview the email.")
    campaign = web.campaign(db)
    me = _me(db, request)
    counts = waiting(db, campaign.id, datetime.now(UTC) - timedelta(days=7))
    if not counts["table"] + counts["drafts"]:
        counts = {"table": 2, "drafts": 1}  # (nothing new: the shape with made-up counts)
    return HTMLResponse(compose(campaign, counts, me, Role.DM)["html"])
