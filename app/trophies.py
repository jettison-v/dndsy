"""Trophy Case (Brett's notes on docs/mockups/player-page/, Nov 7; built Nov 10): what the recaps gave each person at the
table and what their dice did, across the campaign. A Trophies tab on Party, one row per character and one for the
DM; a row opens that person's own view (the mockup's A: the shelf of awards, their numbers, every d20 they rolled, their
awards newest first). For fun, never a ranking: facts only, no verdicts, rows by name.

What counts (Manage › Settings › Trophy Case, `Campaign.table_settings["trophies"]`): by default only what happened
during a published session (`session_story.night`: the recording's own time, or that evening); "all" counts every roll
the table saw, for a table that doesn't record its sessions. Rolls are the table-visible ones in Table rolls (askdnd's
own and D&D Beyond's game log): a DM-only or private roll never counts. The DM's are the rolls with no character (the
monsters'). Drops to 0 come from `CharacterDown`, recorded since Nov 10; the DM's row shows the party's.
"""

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import review, session_story, web
from app.auth import can_edit_settings, current_user
from app.db import get_db
from app.characters import campaign_characters, character_summary
from app.extraction import session_label
from app.models import Campaign, CharacterDown, GameSession, Status, StoryEvent, TableRoll
from app.templating import templates

MODES = {"sessions": "Only what happened during sessions", "all": "Every roll the table saw"}


def mode(campaign: Campaign) -> str:
    m = (campaign.table_settings or {}).get("trophies")
    return m if m in MODES else "sessions"


def set_mode(campaign: Campaign, value: str) -> None:
    if value not in MODES:
        raise ValueError("Pick one of the two.")
    campaign.table_settings = {**(campaign.table_settings or {}), "trophies": value}


def _sessions(db: Session, campaign: Campaign) -> list[tuple[GameSession, object]]:
    """The published sessions with their published recap, oldest first."""
    out = []
    for s in db.scalars(select(GameSession).where(GameSession.campaign_id == campaign.id).order_by(GameSession.played_on, GameSession.id)):
        recap = review.published_recap(s)
        if recap is not None:
            out.append((s, recap))
    return out


def moments(s: GameSession) -> list[StoryEvent]:
    """A session's published key moments that name only published entries (a hidden entry is as if it didn't exist)."""
    return [e for e in s.events if e.status == Status.PUBLISHED and all(x.status == Status.PUBLISHED for x in e.entities)]


def gather(db: Session, campaign: Campaign) -> dict:
    """Everyone's trophies: {"rows", "mode", "mode_says", "sessions"}. A row: {"key" ("c<id>" or "dm"), "name",
    "character", "dm", "entity_id", "awards" (newest first: {award, session, label, why, quote, dice, on}), "shelf"
    ({award, n, sessions, dice}, most first), "rolls", "twenties", "ones", "average", "d20" (count per face), "damage",
    "biggest", "healing", "spells", "downs", "moments", "played" (sessions with any of it)}."""
    sessions = _sessions(db, campaign)
    windows = [(s.id, w) for s, _ in sessions if (w := session_story.night(s))]
    counting = mode(campaign)

    def session_at(at: datetime) -> int | None:
        return next((sid for sid, (a, b) in windows if a <= at < b), None)

    rolls = [r for r in db.scalars(select(TableRoll).where(TableRoll.campaign_id == campaign.id, TableRoll.visibility == "table"))
             if counting == "all" or session_at(r.created_at) is not None]
    chars = campaign_characters(db, campaign.id)
    rows = {f"c{c.id}": {"name": c.name, "character": c, "dm": False, "entity_id": c.entity.id if c.entity else None} for c in chars}
    rows["dm"] = {"name": "The DM", "character": None, "dm": True, "entity_id": None}
    for key, row in rows.items():
        row.update(key=key, awards=[], rolls=0, d20=[0] * 20, damage=0, biggest=None, healing=0, spells=0, downs=0, moments=0, played=set())

    for r in rolls:
        row = rows.get(f"c{r.character_id}" if r.character_id else "dm")
        if row is None:
            continue  # (a character who has left the table)
        if (sid := session_at(r.created_at)) is not None:
            row["played"].add(sid)
        if r.parent_id is None:
            row["rolls"] += 1
        if r.kept is not None and 1 <= r.kept <= 20:
            row["d20"][r.kept - 1] += 1
        if r.kind == "damage" and r.total > 0:
            row["damage"] += r.total
            if row["biggest"] is None or r.total > row["biggest"]["total"]:
                row["biggest"] = {"total": r.total, "label": r.label}
        if r.kind == "heal" and r.total > 0:
            row["healing"] += r.total
    by_id = {c.id: c for c in chars}
    for s in session_story.casts(rolls, {r.character_id: by_id[r.character_id] for r in rolls if r.character_id in by_id})["by"]:
        rows[f"c{s['character'].id}"]["spells"] = s["n"]

    if chars:
        for d in db.scalars(select(CharacterDown).where(CharacterDown.character_id.in_(list(by_id)), CharacterDown.kind == "down")):
            if counting == "all" or session_at(d.at) is not None:
                rows[f"c{d.character_id}"]["downs"] += 1
    rows["dm"]["downs"] = sum(r["downs"] for k, r in rows.items() if k != "dm")

    # Awards (the picked nominee, and the dice's) and key moments naming a character's entry, from each published recap
    by_entity = {c.entity.id: f"c{c.id}" for c in chars if c.entity}
    by_name = {r["name"].casefold(): k for k, r in rows.items()}
    for s, recap in sessions:
        label = session_label(s)
        for a in session_story.awards(db, s, recap):
            key = "dm" if a["dm"] else by_entity.get(a.get("entity_id")) or by_name.get((a.get("who") or "").casefold())
            if key is None:
                continue
            rows[key]["awards"].append({"award": a["award"], "session": s.id, "label": label, "why": a.get("why") or "",
                                        "quote": a.get("quote") or "", "dice": a["dice"], "on": s.played_on})
            rows[key]["played"].add(s.id)
        for e in moments(s):
            for key in {by_entity[x.id] for x in e.entities if x.id in by_entity}:
                rows[key]["moments"] += 1
                rows[key]["played"].add(s.id)

    out = []
    for row in rows.values():
        d20s = sum(row["d20"])
        row["twenties"], row["ones"] = row["d20"][19], row["d20"][0]
        row["average"] = round(sum((i + 1) * n for i, n in enumerate(row["d20"])) / d20s, 1) if d20s else None
        row["played"] = len(row["played"])
        row["awards"].sort(key=lambda a: (a["on"] or date.min, a["session"]), reverse=True)
        shelf: dict[str, dict] = {}
        for a in reversed(row["awards"]):
            x = shelf.setdefault(a["award"], {"award": a["award"], "n": 0, "sessions": [], "dice": a["dice"]})
            x["n"] += 1
            x["sessions"].append(a["label"])
        row["shelf"] = sorted(shelf.values(), key=lambda x: (-x["n"], x["award"]))
        out.append(row)
    out.sort(key=lambda r: (r["dm"], r["name"].casefold()))  # (by name, the DM last: never by a number)
    return {"rows": out, "mode": counting, "mode_says": MODES[counting], "sessions": len(sessions)}


def one(db: Session, campaign: Campaign, key: str) -> dict | None:
    """One person's trophies (a row of `gather`) with their picture and their d20s as bars, or None."""
    got = gather(db, campaign)
    row = next((r for r in got["rows"] if r["key"] == key), None)
    if row is None:
        return None
    session_story.pictured(db, [row])
    row["sheet"] = character_summary(row["character"]) if row["character"] else None
    top = max(row["d20"]) or 1
    row["d20_bars"] = [{"face": i + 1, "n": n, "share": round(100 * n / top)} for i, n in enumerate(row["d20"])]
    return {**got, "row": row}


# ---------------------------------------------------------------- pages

router = APIRouter()


def _campaign(request: Request, db: Session) -> Campaign:
    if not current_user(request):
        raise HTTPException(401)
    campaign = web.campaign(db)
    if campaign is None:
        raise HTTPException(404)
    return campaign


@router.get("/party/trophies")
def table(request: Request, db: Session = Depends(get_db)):
    """Party's Trophies tab (loaded once the tab is first shown): a row each, the DM's last."""
    campaign = _campaign(request, db)
    got = gather(db, campaign)
    session_story.pictured(db, got["rows"])
    return templates.TemplateResponse(request, "_trophies.html", {**got, "can_set": can_edit_settings(current_user(request), campaign.id)})


@router.get("/party/trophies/{key}")
def view(request: Request, key: str, db: Session = Depends(get_db)):
    """One person's trophies, in a window from their row."""
    got = one(db, _campaign(request, db), key)
    if got is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "_trophy_view.html", got)


@router.post("/manage/settings/trophies")
def save_mode(request: Request, counts: str = Form(""), db: Session = Depends(get_db)):
    """What Trophy Case counts (its DM or an admin): only what happened during sessions, or every roll."""
    campaign = web.campaign(db)
    if campaign is None or not can_edit_settings(current_user(request), campaign.id):
        raise HTTPException(404)
    try:
        set_mode(campaign, counts)
    except ValueError as e:
        return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": web.notice(str(e), "warn")})})
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": f"Trophy Case counts: {MODES[counts].lower()}"})})
