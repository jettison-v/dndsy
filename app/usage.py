"""Which features get used (Brett, Nov 9; docs/mockups/feature-use/, he chose A and A): askdnd's own counts, never sent
anywhere. A use is doing something (a roll, a cast, an item used, a change made), not opening a page, and each is tagged
with the page it was done on (Battle, Sheet, askdnd's table…), to see both what's used and where, for UX decisions.

- **Recorded in one place**: `Recorder`, in front of the app, notes every action route that succeeded (POST, PUT,
  PATCH, DELETE) after its reply has gone, so no one waits. `FEATURES` turns a route into a feature's name, first match
  wins; `IGNORED` is askdnd's own bookkeeping (the bridge, syncing, error reports). tests/test_usage.py fails on a
  route in neither, so a new feature is counted the day it's added. A route can name its use more finely through
  `request.state.usage` (Table rolls: "Rolls: attacks", "Roll card: attacks").
- **The page**: from the address the browser says it was on (HTMX's HX-Current-URL, else the Referer), by `PAGES`.
- **The table only** (A): admins' uses and test campaigns' (where the test accounts play) are left out when the counts
  are read (`counted`), not when they're kept, so Table rolls' history could be loaded in.
"""

import logging
import os
import re
from urllib.parse import urlparse

from starlette.concurrency import run_in_threadpool

log = logging.getLogger(__name__)

# Route → feature, first match wins (the route as the app declares it: /characters/{character_id}/cast)
FEATURES: list[tuple[str, str]] = [
    (r"^/rolls$", "Rolls"),
    (r"^/characters/\{character_id\}/cast", "Cast"),
    (r"^/characters/\{character_id\}/(hp/apply|creatures/\{creature_id\}/hp)$", "Hit points"),
    (r"^/characters/\{character_id\}/(conditions|concentration)", "Conditions"),
    (r"^/characters/\{character_id\}/death$", "Death saves"),
    (r"^/characters/\{character_id\}/rest$", "Rests"),
    (r"^/characters/\{character_id\}/(count|inspiration)$", "Resources"),
    (r"^/characters/\{character_id\}/use/", "Using an item"),
    (r"^/characters/\{character_id\}/coins$", "Coins"),
    (r"^/characters/\{character_id\}/items/add$", "Item browser"),
    (r"^/characters/\{character_id\}/items/\{item_id\}/give$", "Giving"),
    (r"^/characters/\{character_id\}/items/", "Inventory"),
    (r"^/characters/\{character_id\}/(prepare|spells/prepare)$", "Preparing spells"),
    (r"^/characters/\{character_id\}/wild-shape", "Wild Shape"),
    (r"^/characters/\{character_id\}/bring/", "Items that bring a creature"),
    (r"^/characters/\{character_id\}/creatures/", "Your creatures"),
    (r"^/characters/\{character_id\}/ready", "Ready"),
    (r"^/characters/\{character_id\}/turn$", "Your turn's bar"),
    (r"^/characters/\{character_id\}/(pick|order)", "Pinning to Battle"),
    (r"^/characters/\{character_id\}/notes", "Your notes on your character"),
    (r"^/characters/\{character_id\}/override", "Corrections"),
    (r"^/characters/\{character_id\}/link$", "Linking a sheet"),
    (r"^/fight/initiative$", "Initiative from askdnd"),
    (r"^/table/fight/", "askdnd's table: the fight"),
    (r"^/table/tokens/", "askdnd's table: tokens"),
    (r"^/table/scenes", "askdnd's table: scene notes"),
    (r"^/table/places/\{place_id\}/(fog|terrain)$", "askdnd's table: fog and terrain"),
    (r"^/table/places/\{place_id\}/areas", "askdnd's table: areas"),
    (r"^/table/", "askdnd's table: places and maps"),
    (r"^/pictures/", "Pictures"),
    (r"^/sessions/\{session_id\}/(full/)?narrate$", "Listen to the recap"),
    (r"^/sessions/\{session_id\}/suggest$", "Suggesting (story)"),
    (r"^/(campaign/\{entity_id\}/(suggest|facts)|campaign/glossary/(suggest|\{term_id\}/suggest))$", "Suggesting (story)"),
    (r"^/(campaign|admin/suggestions|suggestions|manage/proposals)/", "World and the Inbox"),
    (r"^/questions/", "World and the Inbox"),
    (r"^/manage/sessions/", "Session Story review"),
    (r"^/manage/table", "Manage › Table"),
    (r"^/manage/(settings|house-rules)", "Manage › Settings and house rules"),
    (r"^/manage/", "Admin pages"),
    (r"^/dice$", "Your dice"),
    (r"^/feedback$", "Feedback for Claude"),
    (r"^/your-notes/", "Your notes"),
    (r"^/email/inbox$", "Email settings"),
    (r"^/rules/terms/", "Rule terms"),
    (r"^/view-as", "View as"),
]
# askdnd's own bookkeeping, never a person's use
IGNORED = re.compile(r"^/(bridge/|api/|errors/page$|live/|logout$|email/stop$|characters/refresh$|characters/\{character_id\}/"
                     r"(refresh|level-up/read|reminders|hp/work)$)")
# The page an action was done on, from its address, first match wins
PAGES: list[tuple[str, str]] = [
    (r"^/characters/\d+/battle", "Battle"), (r"^/characters/\d+/plan", "Plan"), (r"^/characters/\d+(/sheet)?/?$", "Sheet"),
    (r"^/characters/\d+", "Character (other)"), (r"^/party", "Party"), (r"^/c/[^/]+/table", "askdnd's table"),
    (r"^/c/[^/]+/manage", "Manage"), (r"^/manage", "Admin"), (r"^/c/[^/]+/campaign", "Campaign"), (r"^/c/[^/]+/sessions", "Story"),
    (r"^/c/[^/]+/?$", "Story"), (r"^/your-notes", "Your notes"), (r"^/help", "Help"),
]
_FEATURES = [(re.compile(p), f) for p, f in FEATURES]
_PAGES = [(re.compile(p), n) for p, n in PAGES]
VERSION = (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:12]


def feature_of(route: str) -> str | None:
    """The feature an action route belongs to, "" for askdnd's own bookkeeping, None if it isn't mapped."""
    if IGNORED.match(route):
        return ""
    return next((f for rx, f in _FEATURES if rx.match(route)), None)


def page_of(url: str) -> str:
    path = urlparse(url or "").path or ""
    return next((n for rx, n in _PAGES if rx.match(path)), "Other" if path else "")


def _route(scope) -> str:
    r = scope.get("route")
    return re.sub(r":[a-z]+\}", "}", getattr(r, "path", "") or "")  # ("{character_id:int}" → "{character_id}")


def _opener():
    from app.db import SessionLocal, engine

    return SessionLocal() if engine is not None else None


opener = _opener  # (tests open their own session: tests/conftest.py)


def _keep(email: str, route: str, feature: str, page: str, path: str) -> None:
    """Kept on a worker thread, after the reply: who, which campaign (the character's, else the one they're in), what."""
    from sqlalchemy import select

    from app import access
    from app.models import Character, UsageEvent, User

    session = opener()
    if session is None:
        return
    with session as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            return
        m = re.match(r"^/characters/(\d+)", path)
        ch = db.get(Character, int(m.group(1))) if m else None
        campaign = ch.campaign_id if ch else (access.current_campaign(email) or {}).get("id")
        db.add(UsageEvent(campaign_id=campaign, user_id=user.id, feature=feature[:60], page=page[:30], version=VERSION))
        db.commit()


class Recorder:
    """ASGI middleware: after an action route has answered (2xx), keep its use. Never in the way: a failure to keep it
    is logged, not raised."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            return await self.app(scope, receive, send)
        status = {}

        async def sending(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        await self.app(scope, receive, sending)
        try:
            if not 200 <= status.get("code", 500) < 300:
                return
            route = _route(scope)
            feature = (scope.get("state") or {}).get("usage") or feature_of(route)
            email = ((scope.get("session") or {}).get("user") or {}).get("email", "")
            if not feature or not email:
                return
            headers = dict(scope.get("headers") or [])
            where = (headers.get(b"hx-current-url") or headers.get(b"referer") or b"").decode("latin-1")
            await run_in_threadpool(_keep, email.lower(), route, feature, page_of(where), scope.get("path", ""))
        except Exception:  # noqa: BLE001 - counting must never break a use
            log.warning("A use wasn't counted", exc_info=True)


# ------------------------------------------------------------------ reading them (Admin › Features)

def counted(db, campaign_id: int | None):
    """The uses that count: the table's (not admins', not test accounts', not in a test campaign)."""
    from sqlalchemy import select

    from app.models import Campaign, UsageEvent, User

    left_out = {u.id for u in db.scalars(select(User)) if _left_out(u.email)}
    tests = set(db.scalars(select(Campaign.id).where(Campaign.is_test.is_(True))))
    q = select(UsageEvent)
    if campaign_id:
        q = q.where(UsageEvent.campaign_id == campaign_id)
    return [e for e in db.scalars(q) if e.user_id not in left_out and e.campaign_id not in tests]


ADMIN_ONLY = {"Admin pages", "View as", "Corrections", "Linking a sheet", "Manage › Table", "Manage › Settings and house rules",
              "Session Story review", "World and the Inbox", "Email settings"}  # (the DM's or an admin's: not "never touched" by players)


def _family(feature: str) -> str:
    """A use's feature as the map names it: "Rolls: attacks" → "Rolls", "Roll card: damage" → "The roll card"."""
    head = feature.split(":", 1)[0]
    return "The roll card" if head == "Roll card" else head


def summary(db, campaign_id: int | None, days: int, now=None) -> dict:
    """Admin › Features: everything the page draws, for the last `days` against the `days` before."""
    from collections import Counter, defaultdict
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.companion_story import TABLE_TIME
    from app.models import CampaignCharacter, CampaignMember, Character, Role, User

    now = now or datetime.now(UTC)
    start, before = now - timedelta(days=days), now - timedelta(days=2 * days)
    every = counted(db, campaign_id)
    here = [e for e in every if e.at >= start]
    prev = [e for e in every if before <= e.at < start]
    day0 = (start.astimezone(TABLE_TIME)).date()
    daily = [0] * (days + 1)
    for e in here:
        i = (e.at.astimezone(TABLE_TIME).date() - day0).days
        if 0 <= i <= days:
            daily[i] += 1
    first_seen: dict[str, datetime] = {}
    for e in every:
        if e.version and (e.version not in first_seen or e.at < first_seen[e.version]):
            first_seen[e.version] = e.at
    releases = sorted(((at.astimezone(TABLE_TIME).date() - day0).days, at.astimezone(TABLE_TIME).strftime("%b %-d"))
                      for v, at in first_seen.items() if at >= start)
    uses, was, who = Counter(e.feature for e in here), Counter(e.feature for e in prev), defaultdict(set)
    for e in here:
        who[e.feature].add(e.user_id)
    # the people at the table: a player by their character's name, the DM as "The DM"
    members = list(db.execute(select(User, CampaignMember.role).join(CampaignMember, CampaignMember.user_id == User.id)
                              .where(CampaignMember.campaign_id == campaign_id, CampaignMember.left_on.is_(None)))) if campaign_id else []
    left_out = {u.id for u in db.scalars(select(User)) if _left_out(u.email)}
    people = []
    for u, role in members:
        if u.id in left_out:
            continue
        ch = db.scalar(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                       .where(Character.owner_id == u.id, CampaignCharacter.campaign_id == campaign_id, CampaignCharacter.left_on.is_(None),
                              Character.copy_of_id.is_(None)).order_by(Character.id))
        people.append({"id": u.id, "name": "The DM" if role == Role.DM else (ch.name if ch else u.name.split()[0])})
    people.sort(key=lambda p: (p["name"] == "The DM", p["name"]))
    rows = []
    for f, n in uses.items():
        p = was.get(f, 0)
        rows.append({"feature": f, "uses": n, "who": who[f], "trend": None if not p else round((n - p) / p * 100)})
    used_families = {_family(f) for f in uses}
    never = sorted({f for _, f in FEATURES} - ADMIN_ONLY - {"Rolls"} - used_families)
    unknown = "Not kept (rolls before Nov 9)"
    pages = Counter(e.page or unknown for e in here)
    page_top = defaultdict(Counter)
    for e in here:
        page_top[e.page or unknown][e.feature] += 1
    grid_features = [r["feature"] for r in sorted(rows, key=lambda r: -r["uses"])[:12]]
    grid = {(e.feature, e.user_id): 0 for e in here}
    for e in here:
        grid[(e.feature, e.user_id)] += 1
    nights = len({d for d, n in enumerate(daily) if n >= 20})
    total, total_prev = len(here), len(prev)
    return {
        "days": days, "daily": daily, "releases": releases, "start": day0, "rows": rows, "people": people, "never": never,
        "pages": [{"page": p, "uses": n, "top": page_top[p].most_common(3)} for p, n in pages.most_common()],
        "grid_features": grid_features, "grid": grid, "nights": nights, "total": total,
        "change": None if not total_prev else round((total - total_prev) / total_prev * 100),
        "active": len({e.user_id for e in here} & {p["id"] for p in people}), "table": len(people),
        "families": len(used_families - ADMIN_ONLY), "all_families": len({f for _, f in FEATURES} - ADMIN_ONLY - {"Rolls"}) + 1,
    }


def _left_out(email: str) -> bool:
    """Admins (building and trying askdnd). Test accounts play in the test campaign, which is left out as a whole: the
    feedback switch doesn't mark them (players have it too)."""
    from app import access

    return access.level(email) == access.ADMIN


# ------------------------------------------------------------------ Admin › Features

def chart(daily: list[int], releases: list[tuple[int, str]], start, w: int = 640, h: int = 190) -> dict:
    """One line of uses by day (the admin blue), the days marked where a deploy first ran; each day a hover target."""
    from datetime import timedelta

    left, right, top, bottom = 36, 10, 14, 24
    n, peak = len(daily), max(daily or [0]) or 1
    peak = int(peak * 1.1) + 1
    x = lambda i: left + (w - left - right) * (i / max(1, n - 1))  # noqa: E731
    y = lambda v: top + (h - top - bottom) * (1 - v / peak)  # noqa: E731
    line = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for i, v in enumerate(daily))
    return {"w": w, "h": h, "line": line, "area": f"{line} L{x(n - 1):.1f} {h - bottom} L{left} {h - bottom} Z",
            "ticks": [(round(y(t), 1), t) for t in (0, peak // 2, peak)], "left": left, "right": w - right, "base": h - bottom, "top": top,
            "days": [{"x": round(x(i), 1), "y": round(y(v), 1), "n": v, "on": (start + timedelta(days=i)).strftime("%a %b %-d")} for i, v in enumerate(daily)],
            "step": round((w - left - right) / max(1, n - 1), 1),
            "releases": [{"x": round(x(i), 1), "label": f"Deploy {label}", "end": x(i) > w - 120} for i, label in releases]}


from fastapi import APIRouter, Depends, Request  # noqa: E402

from app.db import get_db  # noqa: E402

router = APIRouter()


@router.get("/manage/features")
def features_page(request: Request, days: int = 30, campaign: int = 0, sort: str = "uses", db=Depends(get_db)):
    """Which features get used (admins): by feature, by page, never touched, by person, against the period before."""
    from sqlalchemy import select

    from app import web
    from app.auth import is_admin
    from app.models import Campaign
    from app.templating import templates

    user, denied = web.require(request, is_admin, "Only admins can see which features get used.")
    if denied:
        return denied
    days = days if days in (7, 30, 90) else 30
    campaigns = list(db.scalars(select(Campaign).where(Campaign.is_test.is_(False)).order_by(Campaign.id)))
    here = next((c for c in campaigns if c.id == campaign), None) or web.campaign(db)
    s = summary(db, here.id if here else None, days)
    key = {"uses": lambda r: -r["uses"], "growing": lambda r: -(r["trend"] if r["trend"] is not None else 10**6),
           "falling": lambda r: (r["trend"] if r["trend"] is not None else 10**6)}.get(sort, lambda r: -r["uses"])
    rows = sorted(s["rows"], key=key)
    top = max([r["uses"] for r in rows] or [1])
    return templates.TemplateResponse(request, "admin_features.html", {
        "s": s, "rows": rows, "top": top, "days": days, "sort": sort, "campaigns": campaigns, "here": here,
        "chart": chart(s["daily"], s["releases"], s["start"]), "page_top": max([p["uses"] for p in s["pages"]] or [1]),
        "step": lambda v: 0 if not v else 1 if v < 5 else 2 if v < 20 else 3})
