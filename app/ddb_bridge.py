"""The D&D Beyond bridge, a proof (Brett, 2026-10-27; docs/mockups/ddb-overlay.html, docs/plans/2026-10-27-data-strategy.md).

askdnd's browser extension (extension/askdnd-bridge/) runs in a person's own signed-in D&D Beyond tab. It tells askdnd
the moment the sheet saves, and makes askdnd's changes there, as that person, with the requests the sheet itself sends.
It works like middleware between askdnd and D&D Beyond, and repairs itself:

1. **What you did, not numbers.** askdnd keeps intents ("drank a Potion of Healing, rolled 7"). The D&D Beyond totals
   are worked out from a fresh read of D&D Beyond when they're sent, so a sheet that changed meanwhile is built on, not
   written over.
2. **One outbox per character, end state only.** Everything waiting for a character goes as one batch of final totals
   (the newest absolute value is the only one that matters), one batch at a time per character.
3. **Delivered on its own.** Whenever the extension has the character's sheet open it collects the outbox: when the
   sheet opens, after every save, and every 30 seconds. A batch that fails is tried again later, by itself.
4. **Read back, field by field.** D&D Beyond can drop a write and still answer OK (DDB Importer, src/updater/
   syncQueue.ts), so a change counts only once askdnd reads it back. A field still at its old value is sent again, up to
   MAX_ATTEMPTS times. Just before writing, the extension reads the sheet itself: a field already at its new value is
   skipped (no double drink), and if D&D Beyond changed in the moment since askdnd read it, the batch is worked out
   again from the new numbers.
5. **Never a guess.** A field D&D Beyond holds at a value askdnd can't explain after writing to it isn't written over:
   the change stops as "not on D&D Beyond yet", with the end state to make by hand.
6. **Awake whenever someone is using it, with no switch** (Brett, 2026-10-27: always active when it needs to be,
   without wasting D&D Beyond's resources). Anyone opening or using an askdnd page or a D&D Beyond sheet wakes it for
   the idle timer (30 minutes); a save on a D&D Beyond sheet is always read and recorded, awake or not; an askdnd
   character page re-reads that character when askdnd's copy is older than live.AUTO_MIN_AGE. A running fight keeps it
   awake however quiet the table is.
   Asleep, only the extension's background pull and the hourly check stop. **A change from askdnd only while its sheet
   can be reached** (decided 2026-10-28; `reachable`: its extension heard the sheet in the last live.REACH): otherwise
   it's refused, saying how, and nothing is queued. A change still waiting keeps it awake until its sheet has gone
   quiet for the wait timer (3 minutes); then it's listed to make by hand (`_give_up`), and made by itself on the
   sheet's next read if D&D Beyond still holds what it did, or ticked off if it was made there by hand (`_catch_up`). Admins set the timers on
   Manage › askdnd › D&D Beyond bridge (TIMERS); the state is in tool_settings (bridge_awake).
7. **Health.** The extension reports in every minute; askdnd reads the test character every hour (no sign-in needed);
   a round trip on the test character (1 hit point and a Candle out and back) runs from the status pill before a game,
   and Check everything (Manage › askdnd › D&D Beyond bridge) runs every kind of change out and back; every page's
   menu bar shows how it stands.
8. **Everything a player changes in play** (ddb_fields: what each field is, where D&D Beyond keeps it, the request
   that writes it): hit points, death saves, Heroic Inspiration, conditions, Exhaustion, Hit Dice (as a Short Rest),
   spell and Pact Magic slots, limited uses, an item's count, equipped, attuned, charges, container,
   coins, adding and removing an item. A roll made on the sheet is only heard, into Table rolls ("on D&D Beyond").
   After a change, every open copy of the sheet shows D&D Beyond's numbers in place (ddb-page.js `show`).
9. **The DM as a backup** (the VTT piece "dm_backup"; DM Backup Option A, Brett 2026-11-02, docs/mockups/dm-backup/).
   A D&D Beyond campaign's DM can change its players' sheets (tested on the real D&D Beyond, 2026-11-01 and 11-02, from
   the campaign page and the VTT with the sheet closed). So when a character's own sheet is closed, a browser of its
   campaign's DM with any D&D Beyond page open makes its changes on its own (`carried`: the extension says so through
   `/bridge/carry` every few seconds). The player's own open sheet always goes first, the same one batch at a time per
   character keeps two browsers from doubling a change, askdnd's log says which were made through the DM (D&D Beyond
   doesn't say who), and the Live pill keeps asking the player to open their sheet: only it sends rolls to the Game Log.

States for a change: waiting (and sending), live (D&D Beyond has it), not_yet (can't be made; the end state is listed
to make by hand), plus seen in the log (changed on D&D Beyond itself). The outbox, the batches, the log and the
extension's key are in the database (BridgeIntent, BridgeBatch, BridgeLog, BridgeKey), so a restart, a crash or a
second copy of the app loses and doubles nothing; each character's row is locked while its batch is built or settled,
so two copies never build two batches for one character. Only the extension's heartbeat is kept in memory (it comes
back within 30 seconds). Local only: on where DDB_BRIDGE=1, never in production.

The extension makes only the requests it knows (ddb_fields.WRITES), so a page can't ask it to change anything else; it calls
askdnd with a key from an askdnd page you're signed in to (`/bridge/connect`), since to Chrome it's a third party and a
browser blocking third-party cookies sends it no cookie.
"""

import copy
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app import access, config, ddb, ddb_fields, ddb_sheet, live, picks, realtime, table_rolls, web
from app import conditions as cond
from app import characters as chars
from app.auth import current_user, is_admin, is_dm
from app.db import get_db
from app.models import BridgeBatch, BridgeIntent, BridgeKey, BridgeLog, Campaign, Character, TableRoll, ToolSetting
from app.templating import templates

router = APIRouter()

HEALING = {"Potion of Healing": "2d4+2", "Potion of Greater Healing": "4d4+4", "Potion of Superior Healing": "8d4+8",
           "Potion of Supreme Healing": "10d4+20"}  # SRD 5.2.1
TEST_DDB_ID = "172836541"  # Vi, Brett's test character on D&D Beyond (not in the table's campaign)
TEST_ITEM = "Candle"  # the round trip takes one and puts it back
MAX_ATTEMPTS = 3
RETRY_SECONDS = (0, 5, 20)  # how long a batch that didn't land waits before it's sent again
SENDING_SECONDS = 30  # a batch the extension took but never answered for is offered again
# A batch may build on askdnd's copy of the sheet this recent instead of reading it first (Brett, 2026-10-29: a second
# faster): the extension checks every number it writes against D&D Beyond right before writing and writes nothing if
# one changed (askdnd works it out again), so an older copy only costs a retry. What that check doesn't cover is read
# fresh first: a hit down to 0 (worked out from maximum hit points) and a change the copy says can't be made.
COPY_SECONDS = 60
EXTENSION_FRESH_SECONDS = 90  # the extension reports every 30 seconds
READ_CHECK_SECONDS = 3600
OPEN = ("waiting", "sending", "not_yet")
AWAKE_KEY = "bridge_awake"
TIMERS_KEY = "bridge_timers"  # admins change these on Manage › askdnd › D&D Beyond bridge; askdnd's own below
# (key, label, what it's for, unit in seconds, unit's name, default, lowest, highest)
TIMERS = (
    ("idle", "Stays awake after anyone was here", "After someone last opened or used askdnd or a D&D Beyond sheet.", 60, "minutes", 30, 5, 240),
    ("wait", "A waiting change gives up after", "Its D&D Beyond sheet not heard by the extension for this long (closed, or the extension stopped); then it's listed to make by hand.", 60, "minutes", 3, 1, 30),
)
_health = {"extension_at": 0.0, "sheets": [], "heard_at": 0.0, "read_check": None, "round_trip": None}  # a heartbeat, in memory


def _allowed():
    if not config.DDB_BRIDGE:  # (only where DDB_BRIDGE=1: app/config.py)
        raise HTTPException(404)


def plays(db: Session, character: Character | None) -> bool:
    """Whether the bridge's live state works here (the VTT piece "live_state": casting, resources, rests)."""
    from app import vtt
    from app.models import Campaign

    return on_for(db, character) and vtt.on(db.get(Campaign, character.campaign_id), "live_state")


def on_for(db: Session, character: Character | None) -> bool:
    """Whether the bridge works on this character: it may run here, its campaign has it switched on (the VTT piece
    "ddb_bridge": Sync with D&D Beyond, app/vtt.py), and it's a character of its own. Never a test copy: a copy shares a
    real character's D&D Beyond sheet, so a change to it would land on the real one."""
    from app import vtt
    from app.models import Campaign

    if not config.DDB_BRIDGE or character is None or character.copy_of_id is not None or not character.campaign_id:
        return False
    return vtt.on(db.get(Campaign, character.campaign_id), "ddb_bridge")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lock(db: Session, character_id: int) -> None:
    """Hold this character's row until the transaction ends: one copy of the app at a time builds or settles its batch.
    FOR NO KEY UPDATE, never FOR UPDATE (Sentry ASKDND-V2-5, 2026-10-29): a request saving a bridge change holds the
    light hold its new row's character link takes; FOR UPDATE waited on it while that request waited on this one's own
    update of the row (sheet heard), and the two deadlocked. This still keeps out every other writer of the row."""
    db.execute(select(Character.id).where(Character.id == character_id).with_for_update(key_share=True))


def _log(db: Session, character_id: int, text: str, state: str) -> None:
    db.add(BridgeLog(character_id=character_id, text=text[:400], state=state))


# ------------------------------------------------------------------ awake only while playing


def _wake_row(db: Session) -> tuple[ToolSetting, dict]:
    row = db.get(ToolSetting, AWAKE_KEY)
    if not row:
        row = ToolSetting(key=AWAKE_KEY, value="{}")
        db.add(row)
    try:
        value = json.loads(row.value or "{}")
    except ValueError:
        value = {}
    return row, value


def timers(db: Session) -> dict:
    """Each timer in seconds: an admin's setting where there is one, else askdnd's own."""
    row = db.get(ToolSetting, TIMERS_KEY)
    try:
        saved = json.loads(row.value) if row and row.value else {}
    except ValueError:
        saved = {}
    out = {}
    for key, _, _, unit, _, default, lo, hi in TIMERS:
        v = saved.get(key, default)
        out[key] = (v if isinstance(v, int | float) and lo <= v <= hi else default) * unit
    return out


def _fight_on(db: Session) -> bool:
    """A fight is running somewhere (app/fight.py), heard within its STALE time."""
    from app import fight

    return db.scalar(select(Campaign.id).where(Campaign.fight.is_not(None), Campaign.fight_at > datetime.now(UTC) - fight.STALE).limit(1)) is not None


def awake(db: Session) -> dict:
    """{"awake": bool, "until", "why"}: awake while someone used askdnd or a sheet in the last idle timer, while a fight
    runs, or while a change is still waiting (until its sheet has gone quiet for the wait timer)."""
    _, w = _wake_row(db)
    tm = timers(db)
    now, last = time.time(), w.get("last", 0)
    _give_up(db)
    open_changes = db.scalar(select(BridgeIntent.id).where(BridgeIntent.state.in_(("waiting", "sending"))).limit(1))
    if now - last <= tm["idle"] or open_changes or _fight_on(db):
        return {"awake": True, "until": last + tm["idle"]}
    return {"awake": False, "why": f"Asleep: no fight, and no one has opened askdnd or a D&D Beyond sheet for {_span(tm['idle'])}."}


def _span(seconds: float) -> str:
    return f"{seconds / 3600:g} hours" if seconds >= 3600 else f"{seconds / 60:g} minutes"


def _fresh(at: datetime | None) -> bool:
    return bool(at) and time.time() - at.timestamp() <= live.REACH.total_seconds()  # (the bridge's one clock, time.time)


def own_sheet(character: Character) -> bool:
    """Its own D&D Beyond sheet is open: its player's extension heard it in the last live.REACH."""
    return _fresh(character.sheet_heard_at)


def backup_on(campaign: Campaign | None) -> bool:
    """The campaign has the bridge and the DM as a backup (the piece "dm_backup": Sync with D&D Beyond, app/vtt.py)."""
    from app import vtt

    return bool(config.DDB_BRIDGE and campaign is not None and vtt.on(campaign, "ddb_bridge") and vtt.on(campaign, "dm_backup"))


def dm_here(campaign: Campaign | None) -> bool:
    """A browser of this campaign's DM with a D&D Beyond page open was heard in the last live.REACH (`/bridge/carry`)."""
    return backup_on(campaign) and _fresh(campaign.backup_heard_at)


def _campaign_of(character: Character) -> Campaign | None:
    db = object_session(character)
    return db.get(Campaign, character.campaign_id) if db is not None and character.campaign_id else None


def in_its_game(campaign: Campaign, ddb_game: str | None) -> bool:
    """A character in this D&D Beyond game is in the campaign's own: the DM's rights on D&D Beyond reach only there, so
    a campaign that doesn't say which is its own carries no one (review, 2026-11-02)."""
    return bool(ddb_game) and campaign.ddb_campaign_id == ddb_game


def carried(character: Character, campaign: Campaign | None = None) -> bool:
    """The DM's browser can make this character's changes now: the DM is here (`dm_here`) and the character is in that
    campaign's D&D Beyond game (only its DM may change it there). Never a test copy, as with the bridge itself."""
    if character.copy_of_id is not None:
        return False
    campaign = campaign or _campaign_of(character)
    return dm_here(campaign) and in_its_game(campaign, character.ddb_campaign_id)


def how(character: Character) -> str | None:
    """How a change reaches its D&D Beyond sheet now: "sheet" (its own open sheet, always first), "dm" (the DM's
    browser, `carried`) or None (it can't)."""
    return "sheet" if own_sheet(character) else "dm" if carried(character) else None


def reachable(character: Character) -> bool:
    """Its D&D Beyond sheet can be reached now, through its own open sheet or the DM's browser. askdnd takes a change for
    D&D Beyond only then (decided 2026-10-28: a change with no way there isn't accepted)."""
    return how(character) is not None


def sheet_is_open(db: Session, character: Character) -> None:
    """The extension heard this sheet: it can be reached now. Open pages hear when that starts, so the pill and the roll
    window say so at once; hearing it every 30 seconds after that isn't news."""
    was = own_sheet(character)
    character.sheet_heard_at = datetime.fromtimestamp(time.time(), UTC)
    if not was:
        realtime.announce(db, character.campaign_id, "character", id=character.id)


def reach(character: Character, what: str = "") -> None:
    """Refuse a change whose sheet can't be reached, saying how (app.js shows the message where it was pressed)."""
    if not reachable(character):
        raise HTTPException(409, what or f"{character.name}'s D&D Beyond sheet can't be reached: open it in Chrome with the askdnd "
                                         "bridge to change it from askdnd, or make the change on D&D Beyond (askdnd shows it within seconds).")


def _give_up(db: Session) -> None:
    """A change still waiting whose sheet hasn't been heard for the wait timer gives up (decided 2026-10-28): it's listed
    to make by hand, with its batch stopped, instead of waiting all evening at a busy table."""
    wait, now = timers(db)["wait"], time.time()
    quiet = {cid: name for cid, name, heard in db.execute(
        select(Character.id, Character.name, Character.sheet_heard_at).join(BridgeIntent, BridgeIntent.character_id == Character.id)
        .where(BridgeIntent.state.in_(("waiting", "sending"))).distinct()) if heard is None or now - heard.timestamp() > wait}
    quiet = {cid: name for cid, name in quiet.items() if not carried(db.get(Character, cid))}  # (the DM's browser makes it)
    if not quiet:
        return
    for b in db.scalars(select(BridgeBatch).where(BridgeBatch.character_id.in_(quiet), BridgeBatch.state.in_(("sending", "ready")))):
        b.state, b.error = "stopped", "Its D&D Beyond sheet went quiet."
    for cid, name in quiet.items():
        its = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cid, BridgeIntent.state.in_(("waiting", "sending")))
                              .order_by(BridgeIntent.id)))
        for it in its:
            it.state, it.error = "not_yet", f"{name}'s D&D Beyond sheet wasn't heard for {_span(wait)}; askdnd makes it as soon as the sheet is open again."
        _note_stopped(numbers(db.get(Character, cid)), its, quiet=True)


def active(db: Session) -> None:
    """Someone opened or used an askdnd page or a D&D Beyond sheet (or made a change, or ran the check): awake now,
    and for the idle timer more. Never waited for (Sentry ASKDND-V2-4, 2026-10-29: ending a condition marked this
    first and its character second, while the extension's check-in did the reverse, and the two deadlocked): a request
    finding another one marking it right now skips it, as that one is saying the same thing, and one marked in the last
    15 seconds isn't marked again (the timers run in minutes)."""
    if time.time() - _wake_row(db)[1].get("last", 0) < 15:
        return
    row = db.scalars(select(ToolSetting).where(ToolSetting.key == AWAKE_KEY)
                     .with_for_update(skip_locked=True).execution_options(populate_existing=True)).first()
    if row is None:
        if db.get(ToolSetting, AWAKE_KEY) is not None:
            return  # (being marked by another request now)
        row = _wake_row(db)[0]
    w = _wake_row(db)[1]
    w["last"] = time.time()
    row.value = json.dumps(w)


def page_opened(db: Session, character: Character | None) -> None:
    """An askdnd page opened (a character's, when `character`): awake, and that character re-read from D&D Beyond when
    askdnd's copy is older than the party's refresh, so what the page shows is current."""
    active(db)
    if character is not None and character.ddb_id:
        snap = character.snapshot
        last = snap.attempted_at if snap else None
        if last is None or datetime.now(UTC) - last >= live.AUTO_MIN_AGE:
            heard(db, character, saved=False)
    db.commit()


# ------------------------------------------------------------------ the numbers askdnd follows


def numbers(character: Character) -> dict:
    """What D&D Beyond has for this character, from askdnd's last read of it (its saved copy, not askdnd's display
    summary, which shows a count of 0 as 1): every field the bridge follows (`fields`, app/ddb_fields.py), and hit
    points (as D&D Beyond keeps them: damage taken and temporary) and each item's count for working out changes."""
    summary = chars.character_summary(character)
    raw = character.snapshot.raw if character.snapshot else None
    if not summary or not raw:
        return {}
    now = ddb_fields.tracked(raw)
    items = {int(f[5:]): v or 0 for f, v in now.items() if f.startswith("item:")}
    return {"max": ddb_fields.max_hp(summary), "removed": now["hp"]["removedHitPoints"], "temp": now["hp"]["temporaryHitPoints"],
            "items": items, "names": {i: ddb_fields.item_name(raw, i) for i in items}, "raw": raw, "fields": now}


def fields(n: dict) -> dict:
    """The values askdnd follows, keyed as a batch's ops are: "hp", "item:<id>", …"""
    return n.get("fields") or {}


def _value(n: dict, field: str):
    """A field's value on D&D Beyond, also one the log doesn't follow (how many of an item there are in all)."""
    return fields(n)[field] if field in fields(n) else ddb_fields.value(n["raw"], field)


def plan(intents: list[dict], n: dict, every: bool = False) -> tuple[dict, list[str], list[tuple[dict, str]], dict]:
    """The end state of these intents built on what D&D Beyond has now (`n`): the final value of each field they touch,
    one line per field to show, any intent that can't happen any more (with why), and what an added item needs. A
    field D&D Beyond already holds at that value is left out, unless `every` (which fields an intent touches at all)."""
    vals, impossible, touched, extra = {}, [], [], {}

    def get(f):
        return vals[f] if f in vals else _value(n, f)

    def no(it, why):
        impossible.append((it, why))

    for it in intents:
        d, kind = it["data"], it["kind"]
        if kind == "drink":
            f = f"item:{d['item']}"
            if (get(f) or 0) < 1:
                no(it, f"No {d['name']} left on D&D Beyond.")
                continue
            hp = get("hp")
            vals[f] = get(f) - 1
            vals["hp"] = {**hp, "removedHitPoints": max(0, hp["removedHitPoints"] - d["heal"])}
            touched += ["hp", f]
        elif kind == "hp":  # + heals, - damage; temporary hit points take damage first (2024 rules)
            hp = get("hp")
            removed, temp = hp["removedHitPoints"], hp["temporaryHitPoints"]
            if d["amount"] >= 0:
                removed = max(0, removed - d["amount"])
            else:
                soak = 0 if d.get("undo") else min(temp, -d["amount"])  # (taking back a heal: Hit Points only)
                temp, removed = temp - soak, min(n["max"], removed + (-d["amount"] - soak))
            vals["hp"] = {"removedHitPoints": removed, "temporaryHitPoints": temp}
            touched.append("hp")
        elif kind == "temp":  # Temporary Hit Points don't add up: the hit points window chose keep or take (app/hit_points.py)
            vals["hp"] = {**get("hp"), "temporaryHitPoints": max(0, int(d["value"]))}
            touched.append("hp")
        elif kind == "item":
            f = f"item:{d['item']}"
            if get(f) is None or get(f) + d["delta"] < 0:
                no(it, f"D&D Beyond doesn't have enough {d['name']}.")
                continue
            vals[f] = get(f) + d["delta"]
            touched.append(f)
        elif kind == "set":  # an absolute value: on or off, a level, where an item is, or back as it was
            f = d["field"]
            if get(f) is None and not f.startswith("item:"):
                no(it, f"{ddb_fields.name(n['raw'], f)} isn't on D&D Beyond any more.")
                continue
            vals[f] = d["value"]
            touched.append(f)
        elif kind == "use":  # a count used or spent: a slot, a use, a charge, Hit Dice, coins
            f, cur = d["field"], get(d["field"])
            if cur is None:
                no(it, f"{ddb_fields.name(n['raw'], f)} isn't on D&D Beyond any more.")
                continue
            new = cur + d["delta"]
            if new < 0 or (d.get("max") is not None and new > d["max"]):
                no(it, f"D&D Beyond has {ddb_fields.show(n['raw'], f, cur)}: there's no room for that.")
                continue
            vals[f] = new
            touched.append(f)
        elif kind == "death":  # a success or a failure (at most 3 of each), or back to none
            ds = get("death")
            if d.get("reset"):
                vals["death"] = {"failCount": 0, "successCount": 0}
            else:
                vals["death"] = {"failCount": min(3, ds["failCount"] + d.get("fail", 0)),
                                 "successCount": min(3, ds["successCount"] + d.get("success", 0))}
            touched.append("death")
        elif kind == "short_rest":  # D&D Beyond spends Hit Dice only as part of a Short Rest
            for cls, spend in d["spend"].items():
                f, level = f"hitdice:{cls}", (ddb_fields.pick(n["raw"], ["classes", {"id": cls}]) or {}).get("level") or 0
                if get(f) is None or get(f) + spend > level:
                    no(it, f"D&D Beyond doesn't have {spend} Hit Dice left for that class.")
                    break
                vals[f] = get(f) + spend
                touched.append(f)
        elif kind == "remove_item":
            f = f"item:{d['item']}"
            if get(f) is None:
                no(it, f"{d['name']} isn't on D&D Beyond any more.")
                continue
            vals[f] = None
            touched.append(f)
        elif kind == "prepare":  # a spell prepared or not: what preparing it names comes with it (D&D Beyond's ids)
            f = f"prep:{d['cls']}:{d['entry']}"
            vals[f] = bool(d["value"])
            extra[f] = {"spellId": d["def"], "entityTypeId": d["etype"]}
            touched.append(f)
        elif kind == "add_item":
            f = f"add:{d['definition']}"
            vals[f] = (get(f) or 0) + d["quantity"]
            before = extra.get(f, {}).get("quantity", 0)
            extra[f] = {"entityTypeId": d["entityTypeId"], "quantity": before + d["quantity"], "container": d.get("container")}
            touched.append(f)
    target, lines = {}, []
    for f in dict.fromkeys(touched):
        if vals[f] == _value(n, f) and not every:
            continue  # (a change and its undo in one batch, or D&D Beyond has it already: nothing to write)
        target[f] = vals[f]
        lines.append(_line(n, f, vals[f]))
    return target, lines, impossible, extra


def _line(n: dict, f: str, v) -> str:
    """One number to make on D&D Beyond: "Hit points 34 (D&D Beyond has 37)"."""
    line = ddb_fields.show(n["raw"], f, v, n["max"])
    return f"{line[:1].upper()}{line[1:]} (D&D Beyond has {ddb_fields.text(n['raw'], f, _value(n, f), n['max'])})"


# ------------------------------------------------------------------ catching up (decided 2026-10-28)
# A change that stops short of D&D Beyond keeps what D&D Beyond held then (`was`) and its own end result (`want`), in the
# order the changes were made. On each read of that sheet afterwards (`_catch_up`): D&D Beyond holds the end result (it
# was made by hand) → ticked off; it gave up only because the sheet went quiet and D&D Beyond still holds `was` → made
# now, by itself; anything else → it stays, saying D&D Beyond changed since. So nothing waits for a button, and "Make
# these on D&D Beyond" shows the fixed end results, never asking for the same change twice.
STOPPED_KEYS = ("was", "want", "quiet")


def _note_stopped(n: dict | None, intents: list[BridgeIntent], quiet: bool) -> None:
    if not n:
        return
    done: list[dict] = []
    for it in intents:
        d = _as_dict(it)
        fields = list(plan([d], n, every=True)[0])
        before = plan(done, n, every=True)[0] if done else {}
        after, _, impossible, _ = plan(done + [d], n, every=True)
        if impossible and impossible[-1][0] is d or not fields:
            continue  # (one that can't happen any more has no end result: it stays until Try again or Undo)
        it.data = {**it.data, "was": {f: before.get(f, _value(n, f)) for f in fields}, "want": {f: after[f] for f in fields}, "quiet": quiet}
        done.append(d)


def _for_sheet(it: BridgeIntent) -> bool:
    """Stopped only because its sheet went quiet: it waits for the sheet, not for a person."""
    return it.state == "not_yet" and bool(it.data.get("quiet"))


def _clean(it: BridgeIntent) -> None:
    it.data = {k: v for k, v in it.data.items() if k not in STOPPED_KEYS}


def _catch_up(db: Session, character: Character, n: dict) -> None:
    pending: set[str] = set()  # fields an earlier change is now being made on: later ones follow it
    for it in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state == "not_yet")
                         .order_by(BridgeIntent.id)):
        want, was, quiet = it.data.get("want"), it.data.get("was"), it.data.get("quiet")
        if not want:
            continue
        if set(want) & pending:
            if quiet:
                it.state, it.error = "waiting", ""
                _clean(it)
                pending |= set(want)
            continue
        if all(_value(n, f) == v for f, v in want.items()):  # D&D Beyond has it: made there by hand
            it.state = "live"
            _clean(it)
            _log(db, character.id, f"{it.label} (made on D&D Beyond)", "seen")
        elif quiet and all(_value(n, f) == v for f, v in was.items()):  # its sheet is back and nothing changed: make it now
            it.state, it.error = "waiting", ""
            _clean(it)
            pending |= set(want)
        elif quiet:  # it needs a person now: listed to make by hand like any other
            it.error = "D&D Beyond changed since; check it there, then Try again or Undo in askdnd."
            it.data = {**it.data, "quiet": False}


def describe(kind: str, d: dict, n: dict) -> str:
    """A change in words, for the log and the list of what's waiting: "Heroic Inspiration on", "1st-level slots: 1 more
    used", "a Death Saving Throw failure"."""
    raw = n.get("raw")
    if kind == "set":
        return ddb_fields.show(raw, d["field"], d["value"], n.get("max", 0))
    if kind == "use":
        what, many = ddb_fields.name(raw, d["field"]), abs(d["delta"])
        if d["field"].startswith("coin:"):
            return f"{many} {what} {'gained' if d['delta'] > 0 else 'spent'}"
        return f"{what}: {many} more used" if d["delta"] > 0 else f"{what}: {many} back"
    if kind == "death":
        return "Death Saving Throws back to none" if d.get("reset") else \
            f"a Death Saving Throw {'failure' if d.get('fail') else 'success'}" + (" (×2)" if max(d.get("fail", 0), d.get("success", 0)) > 1 else "")
    if kind == "short_rest":
        spent = sum(d["spend"].values())
        return f"a Short Rest, spending {spent} Hit {'Die' if spent == 1 else 'Dice'}"
    if kind == "remove_item":
        return f"{d['name']} removed"
    if kind == "add_item":
        return f"{d['name']} ×{d['quantity']} added"
    if kind == "prepare":
        return f"{d['name']} {'prepared' if d['value'] else 'unprepared'}"
    return kind


def _ops(character: Character, target: dict, n: dict, extra: dict | None = None) -> list[dict]:
    """Each field's request, with where to read it (`read`) and the value it should go from and to: the extension reads
    the sheet just before writing and compares (app/ddb_fields.py). A Short Rest goes first: it restores what a Short
    Rest restores, and the rest is built on top of it."""
    did = int(character.ddb_id)
    order = sorted(target, key=lambda f: not f.startswith("hitdice:"))
    return [{"field": f, **ddb_fields.write(did, f, target[f], n["raw"], (extra or {}).get(f), n["max"]),
             "read": ddb_fields.steps(f), "from": _value(n, f), "to": target[f]} for f in order]


# ------------------------------------------------------------------ the outbox


def add(db: Session, character: Character, kind: str, data: dict, label: str) -> int:
    active(db)  # making a change is using it
    it = BridgeIntent(character_id=character.id, kind=kind, data=data, label=label[:300])
    db.add(it)
    db.flush()
    return it.id


def _as_dict(it: BridgeIntent) -> dict:
    return {"kind": it.kind, "data": it.data}


# ------------------------------------------------------------------ what's on its way, as the page shows it


def _mark(field: str) -> str:
    """Which mark on a page shows this field (the `mark` macro's kind: "hp", "cond:Poisoned"), else the field itself."""
    kind, _, arg = field.partition(":")
    if kind == "hp":
        return "hp"
    if kind == "condition":
        return "cond:" + ddb_fields.CONDITIONS.get(int(arg), "")
    return "cond:Exhaustion" if kind == "exhaustion" else field


def as_shown(db: Session, character: Character, summary: dict | None) -> dict | None:
    """The character's sheet as askdnd shows it (Brett, 2026-10-29: the page shows a change at once, marked until D&D
    Beyond has it): D&D Beyond's, with the changes on their way already made, and "sync" saying which marks are on
    their way ("on") or were given up to make by hand ("failed"); "ending" names conditions on their way off. Without
    any, `summary` as it is."""
    if not summary or not character.id:
        return summary
    rows = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state.in_(OPEN))
                           .order_by(BridgeIntent.id)))
    n = numbers(character) if rows else {}
    if not n:
        return summary
    going = [_as_dict(it) for it in rows if it.state != "not_yet"]
    vals = plan(going, n)[0] if going else {}
    sync = {_mark(f): "failed" for it in rows if it.state == "not_yet" for f in plan([_as_dict(it)], n, every=True)[0]}
    sync |= {_mark(f): "on" for f in vals}
    if not sync:
        return summary
    shown = summary
    if vals:
        raw = copy.deepcopy(n["raw"])
        for f, v in vals.items():
            ddb_fields.put(raw, f, v)
        try:
            shown = ddb.parse_character(raw)
        except ddb.DdbError:
            shown = summary
    # Conditions keep their places: one on its way off stays where it is (marked ending) until D&D Beyond has it gone
    real, planned = summary.get("conditions") or [], {c["name"]: c for c in shown.get("conditions") or []}
    had = {c["name"] for c in real}
    ending = [c["name"] for c in real if c["name"] not in planned]
    conditions = [planned.get(c["name"], c) for c in real] + [c for n, c in planned.items() if n not in had]
    return {**shown, "conditions": conditions, "sync": sync, "ending": ending}


def outbox(db: Session, character: Character, by: str = "sheet", got: chars.Read | None = None) -> dict | None:
    """The batch the extension should make on this character's sheet now, or None. A new batch is built on askdnd's
    copy of the sheet when it's recent (COPY_SECONDS), else on a fresh read; either way the extension checks each total
    against what D&D Beyond has the moment before writing it. `by` "dm": the DM's browser makes it (`carried`), and
    its log line says so. The batch names its sheet (`ddb`): the page making it checks every request is for that one.
    A fresh read is made with the database let go (`chars.read_released`, which ends this lock), then everything here
    is looked at again under the lock with it (`got`), since another copy of the app may have moved on meanwhile."""
    _lock(db, character.id)
    if not awake(db)["awake"]:
        return None
    now = time.time()
    live = db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id,
                                                BridgeBatch.state.in_(("ready", "sending"))).order_by(BridgeBatch.id)).first()
    if live:
        if (live.state == "sending" and now - live.sent_at < SENDING_SECONDS) or now < live.next_at:
            return None  # the extension is on it, or it waits before trying again
        if live.state == "sending":  # taken but never answered for: that was a try too
            if live.attempts >= MAX_ATTEMPTS:
                _stop(db, live, f"No D&D Beyond sheet answered. Tried {MAX_ATTEMPTS} times.")
                return None
            live.attempts += 1
        live.state, live.sent_at = "sending", now
        for i in _intents_of(db, live):
            i.data = {**i.data, "by": by}
        return {"id": live.id, "ops": live.ops, "ddb": character.ddb_id}
    waiting = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state == "waiting")
                              .order_by(BridgeIntent.id)))
    if not waiting:
        return None
    if got is not None:
        chars.store(db, character, got)
    else:
        snap = character.snapshot
        if not (snap and snap.status != "error" and snap.fetched_at and now - snap.fetched_at.timestamp() < COPY_SECONDS):
            return outbox(db, character, by, chars.read_released(db, character))
    n = numbers(character)
    if not n:
        return None
    dicts = [_as_dict(i) for i in waiting]
    target, _lines, impossible, extra = plan(dicts, n)
    left_out = set(plan(dicts, n, every=True)[0]) - set(target)  # the copy has these already, so nothing checks them
    if got is None and (impossible or left_out or (target.get("hp") or {}).get("removedHitPoints", 0) >= n["max"]):
        # what the extension's check doesn't cover: read fresh and work it out again (Nov 2: a copy a moment behind
        # D&D Beyond had no death save mark yet, so clearing the marks looked made already and was never sent)
        return outbox(db, character, by, chars.read_released(db, character))
    for d, why in impossible:  # (by identity: two drinks of the same potion are equal dicts)
        it = waiting[next(k for k, x in enumerate(dicts) if x is d)]
        it.state, it.error = "not_yet", why
    keep = [i for i in waiting if i.state == "waiting"]
    if keep and not target:  # D&D Beyond has the end state already (a change and its undo): nothing to write
        for i in keep:
            i.state = "live"
            _log(db, character.id, i.label, "live")
        return None
    if not keep:
        return None
    snap = character.snapshot
    age = None if got is not None or not (snap and snap.fetched_at) else round(max(0.0, now - snap.fetched_at.timestamp()), 1)
    batch = BridgeBatch(character_id=character.id, intents=[i.id for i in keep], ops=_ops(character, target, n, extra), copy_age=age,
                        before={f: _value(n, f) for f in target}, target=target, state="sending", attempts=1, sent_at=now,
                        next_at=0, check=keep[0].data.get("check", ""), names={f: ddb_fields.name(n["raw"], f) for f in target})
    db.add(batch)
    for i in keep:  # (each intent's own fields: a batch stopped part way settles the ones D&D Beyond has)
        i.state, i.data = "sending", {**i.data, "fields": sorted(plan([_as_dict(i)], n, every=True)[0]), "by": by}
    db.flush()
    return {"id": batch.id, "ops": batch.ops, "ddb": character.ddb_id}


def _intents_of(db: Session, b: BridgeBatch) -> list[BridgeIntent]:
    return list(db.scalars(select(BridgeIntent).where(BridgeIntent.id.in_(b.intents)).order_by(BridgeIntent.id)))


THROUGH_DM = " (made through the DM)"  # a log line's end, when the DM's browser made it (D&D Beyond doesn't say who)


def _log_line(it: BridgeIntent) -> str:
    return it.label + (THROUGH_DM if it.data.get("by") == "dm" else "")


def made_through(db: Session, campaign: Campaign, hours: int = 6, limit: int = 5) -> list[dict]:
    """The newest changes the DM's browser made for this campaign's characters (the Live window's "Made through you")."""
    from app.models import CampaignCharacter

    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = db.execute(select(Character.name, BridgeLog.text, BridgeLog.at).join(Character, Character.id == BridgeLog.character_id)
                      .join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                      .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None),
                             BridgeLog.at >= since, BridgeLog.text.endswith(THROUGH_DM))
                      .order_by(BridgeLog.id.desc()).limit(limit))
    return [{"name": name, "text": text.removesuffix(THROUGH_DM), "at": at} for name, text, at in rows]


def _settle(db: Session, b: BridgeBatch) -> None:
    b.state = "done"
    for it in _intents_of(db, b):
        it.state = "live"
        _log(db, b.character_id, _log_line(it), "live")
    _check_step(db, b, True)


# What an extension says of a request it doesn't know (ddb-page.js `WRITES`): one older than the change, e.g. preparing
# spells before 0.9.8 (Nov 3: Brett's own Chrome hadn't updated, and askdnd tried 3 times and said to make it by hand)
TOO_OLD = "That isn't a change askdnd may make"
OUT_OF_DATE = ("The askdnd extension in the browser making it is older than this change needs. Update it (chrome://extensions › "
               "Developer mode › Update; Chrome also does it within a few hours), then Try again.")


def delivered(db: Session, batch_id: int, ok: bool, error: str = "", conflicts: list[str] | None = None) -> None:
    """The extension's answer for a batch, then the read-back that decides it, field by field."""
    b = db.get(BridgeBatch, batch_id)
    if not b:
        return
    _lock(db, b.character_id)
    db.refresh(b)
    if b.state != "sending":
        return  # settled already (a pull got there first), or offered again
    character = db.get(Character, b.character_id)
    if conflicts:  # D&D Beyond changed in the moment since askdnd read it, and the extension wrote nothing
        replans = max((it.data.get("replans", 0) for it in _intents_of(db, b)), default=0)
        if b.attempts == 1 and replans < MAX_ATTEMPTS:  # nothing of it was written: work it out again from the new numbers
            # (read now: the next batch mustn't build on the copy that was out of date)
            if not _reread(db, b, character):
                return
            b.state = "replanned"
            for it in _intents_of(db, b):
                it.state, it.data = "waiting", {**it.data, "replans": it.data.get("replans", 0) + 1}
        else:
            _stop(db, b, f"D&D Beyond's {_say(conflicts, b)} changed while askdnd was writing it.")
        return
    if not ok and error.startswith(TOO_OLD):  # an older extension refuses a change it doesn't know: trying again can't help
        _stop(db, b, OUT_OF_DATE)
        return
    if not ok:  # couldn't reach the sheet or D&D Beyond: try again later, on its own
        _again(db, b, error or "The change couldn't be made.")
        return
    now = {}
    for attempt in range(4):  # D&D Beyond can take a moment to serve what it just saved
        if attempt:
            time.sleep(1)
        if not _reread(db, b, character):
            return
        n = numbers(character)
        now = {f: _value(n, f) for f in b.target} if n else {}
        missing = [f for f, v in b.target.items() if now.get(f) != v]
        if not missing:
            break
    if not missing:
        _settle(db, b)
    elif any(now.get(f) != b.before.get(f) for f in missing):
        _stop(db, b, f"D&D Beyond's {_say(missing, b)} isn't what askdnd wrote or what it had before.", missing)
    else:
        # The first time, at once, while the extension is here to take it: D&D Beyond is often just slow to show it, and the
        # extension then finds it there and writes nothing (Oct 30: a Short Rest's Hit Point Die waited 5 seconds, then the
        # extension's next check, over 30 in all)
        _again(db, b, "D&D Beyond answered OK but didn't keep it.", at_once=b.attempts == 1)


def _reread(db: Session, b: BridgeBatch, character: Character) -> bool:
    """Read the sheet with the database let go, then hold the character again and keep the read. False when the batch
    was settled meanwhile (a pull or another copy of the app got there first): nothing more to do with it."""
    got = chars.read_released(db, character)
    _lock(db, b.character_id)
    db.refresh(b)
    if b.state != "sending":
        return False
    chars.store(db, character, got)
    return True


def _say(fs: list[str], b: BridgeBatch) -> str:
    return " and ".join(dict.fromkeys(b.names.get(f, "numbers") for f in fs))


def _again(db: Session, b: BridgeBatch, why: str, at_once: bool = False) -> None:
    if b.attempts >= MAX_ATTEMPTS:
        _stop(db, b, f"{why} Tried {MAX_ATTEMPTS} times.")
        return
    b.state, b.error = "ready", why[:400]
    b.next_at = 0 if at_once else time.time() + RETRY_SECONDS[min(b.attempts, len(RETRY_SECONDS) - 1)]
    b.attempts += 1


def _stop(db: Session, b: BridgeBatch, why: str, missing: list[str] | None = None) -> None:
    """The batch stops. With `missing` (the read-back's fields D&D Beyond doesn't hold as written), the rest landed: an
    intent all of whose fields D&D Beyond has is made (never listed to make again), the others wait to be made by hand."""
    b.state, b.error = "stopped", why[:400]
    bad = set(b.target if missing is None else missing)
    left = []
    for it in _intents_of(db, b):
        if missing is not None and not bad.intersection(it.data.get("fields", b.target)):
            it.state = "live"
            _log(db, b.character_id, _log_line(it), "live")
        else:
            it.state, it.error = "not_yet", (why + " Nothing was written over.")[:400]
            left.append(it)
    _note_stopped(numbers(db.get(Character, b.character_id)), left, quiet=False)
    _check_step(db, b, False, why, [f for f in b.target if f not in bad])


def heard(db: Session, character: Character, saved: bool = True) -> None:
    """A read of the sheet, after the extension heard it save (`saved`) or on its every-30-seconds pull: it settles any
    batch D&D Beyond now holds the totals of (so a lost "done" from the extension still gets confirmed). What D&D
    Beyond changed itself is logged by the read (`seen`)."""
    if saved:  # a person saved something on D&D Beyond: always read and recorded, and it counts as using it
        _health["heard_at"] = time.time()
        active(db)
    elif not awake(db)["awake"]:
        return  # asleep: the background pull reads nothing from D&D Beyond
    got = chars.read_released(db, character)  # (with the database let go: D&D Beyond can take 15 seconds)
    _lock(db, character.id)
    chars.store(db, character, got)
    n = numbers(character)
    if not n:
        return
    _catch_up(db, character, n)
    open_batches = list(db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id, BridgeBatch.state.in_(("sending", "ready")))))
    for b in open_batches:
        if all(_value(n, f) == v for f, v in b.target.items()):
            _settle(db, b)


def seen(db: Session, character: Character, before: dict | None, after: dict, summary: dict | None) -> None:
    """Every read of a character from D&D Beyond (the bridge's, the party's refresh, a page opening) passes through
    here with askdnd's last copy (`before`) and the new one: whatever D&D Beyond changed itself goes in the log as
    "On D&D Beyond", whichever read saw it first. What askdnd is writing (or just wrote) isn't D&D Beyond's change."""
    _drop_ended(db, character, summary)
    if not before:
        return
    was, now = ddb_fields.tracked(before), ddb_fields.tracked(after)
    recent = db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id, BridgeBatch.sent_at > time.time() - 60)).all()
    ours = {f for b in recent for f in b.target}
    rested = any(f.startswith("hitdice:") for f in ours)  # askdnd's Short Rest restored what a Short Rest restores
    ours |= {f for f in now if rested and f.split(":")[0] in ("uses", "pact", "slot", "charges")}
    hp_max = ddb_fields.max_hp(summary)
    lines = [ddb_fields.changed(after, f, was[f], v, hp_max) for f, v in now.items()
             if f in was and was[f] is not None and v != was[f] and f not in ours]
    for i in after.get("inventory") or []:  # a new row: added on D&D Beyond, unless askdnd just added one of these
        if isinstance(i, dict) and f"item:{i.get('id')}" not in was and f"add:{(i.get('definition') or {}).get('id')}" not in ours:
            lines.append(f"{ddb_fields.item_name(after, i.get('id'))} added (×{i.get('quantity')})")
    lines += [f"{ddb_fields.item_name(before, f[5:])} removed" for f in was if f.startswith("item:") and f not in now and f not in ours]
    if lines:
        _log(db, character.id, f"{character.name} (on D&D Beyond): " + ", ".join(lines), "seen")


def _drop_ended(db: Session, character: Character, summary: dict | None) -> None:
    """askdnd's own entry for a condition D&D Beyond holds (where it came from, how long it lasts) goes once D&D Beyond
    doesn't have it and no change askdnd is sending (or gave up to make by hand) is about it (review, 2026-10-29: one
    ended on D&D Beyond kept its reminders coming)."""
    if not character.conditions or summary is None:
        return
    there = {c["name"] for c in summary.get("conditions") or []}
    there |= {cond.from_field((it.data or {}).get("field", "")) for it in db.scalars(
        select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state.in_(OPEN), BridgeIntent.kind == "set"))}
    keep = [c for c in character.conditions if c.get("name") not in cond.ON_DDB or c.get("name") in there]
    if len(keep) != len(character.conditions):
        character.conditions = keep or None


def check(character: Character) -> list[dict]:
    """What askdnd just read from D&D Beyond, field by field, for the extension to compare with each open copy of the
    sheet: a copy holding anything else shows D&D Beyond's numbers (extension/askdnd-bridge/ddb-page.js `check`)."""
    return [{"read": ddb_fields.steps(f), "value": v} for f, v in fields(numbers(character)).items()]


def retry(db: Session, intent_id: int) -> None:
    it = db.get(BridgeIntent, intent_id)
    if it and it.state == "not_yet":
        it.state, it.error = "waiting", ""
        _clean(it)


def dismiss(db: Session, intent_id: int) -> None:
    it = db.get(BridgeIntent, intent_id)
    if it and it.state in ("waiting", "not_yet"):
        it.state = "dismissed"


# ------------------------------------------------------------------ health


def round_trip(db: Session, character: Character, full: bool = False) -> None:
    """The pre-game check on the test character: 1 hit point and one Candle out, then back, each confirmed by
    read-back. `full` (Manage › askdnd › D&D Beyond bridge, after D&D Beyond changes its sheet): every kind of change
    the bridge makes that the test character can take, out and back. Queued like any change; the extension delivers it
    from the test character's open sheet. Putting it back depends only on the batch (its `check` and `before`), so a
    restart mid-check still puts Vi back as she was."""
    n = numbers(character) or {}
    item = next((i for i, name in (n.get("names") or {}).items() if name == TEST_ITEM and n["items"][i] > 0), None)
    _health["round_trip"] = {"state": "running", "at": _now(), "error": "", "full": full}
    add(db, character, "hp", {"amount": -1, "check": "out"}, "Check: 1 hit point taken")
    if item:
        add(db, character, "item", {"item": item, "delta": -1, "name": TEST_ITEM, "check": "out"}, f"Check: one {TEST_ITEM} taken")
    for kind, data in _every_change(n) if full and n else []:
        add(db, character, kind, {**data, "check": "out"}, "Check: " + describe(kind, data, n))


def _every_change(n: dict) -> list[tuple[str, dict]]:
    """One of each kind of change, on whatever the test character has (each goes back after)."""
    raw, now = n["raw"], fields(n)
    out = [("death", {"fail": 1}), ("set", {"field": "inspiration", "value": not now["inspiration"]}),
           ("set", {"field": "condition:1", "value": not now["condition:1"]}),
           ("set", {"field": "exhaustion", "value": 0 if now["exhaustion"] else 1}), ("use", {"field": "coin:gp", "delta": 1})]
    cls = next((c for c in raw.get("classes") or [] if (c.get("hitDiceUsed") or 0) < (c.get("level") or 0)), None)
    out += [("short_rest", {"spend": {str(cls["id"]): 1}})] if cls else []

    def first(prefix, ok=lambda f, v: True):
        return next((f for f, v in now.items() if f.startswith(prefix) and v is not None and ok(f, v)), None)
    for f in (first("slot:"), first("pact:", lambda f, v: (ddb_fields.pick(raw, ["pactMagic", {"level": f[5:]}]) or {}).get("available")),
              first("uses:", lambda f, v: ((ddb_fields.pick(raw, ["actions", "*", {"id": f[5:]}]) or {}).get("limitedUse") or {}).get("maxUses")),
              first("charges:", lambda f, v: ((ddb_fields.pick(raw, ["inventory", {"id": f[8:]}]) or {}).get("limitedUse") or {}).get("maxUses", 0) > 1)):
        if f:
            out.append(("use", {"field": f, "delta": -1 if now[f] else 1}))
    canequip = lambda f, v: ((ddb_fields.pick(raw, ["inventory", {"id": f[9:]}]) or {}).get("definition") or {}).get("canEquip")  # noqa: E731
    for f in (first("equipped:", canequip), first("attuned:")):
        if f:
            out.append(("set", {"field": f, "value": not now[f]}))
    box = next((i for i in raw.get("inventory") or [] if (i.get("definition") or {}).get("isContainer")), None)
    thing = first("container:", lambda f, v: str(v) == str(raw.get("id")) and box and f[10:] != str(box["id"]))
    if box and thing:
        out.append(("set", {"field": thing, "value": box["id"]}))
    return out


def _check_step(db: Session, b: BridgeBatch, ok: bool, why: str = "", landed: list[str] = ()) -> None:
    if not b.check:
        return
    rt = _health.get("round_trip") or {"state": "running", "at": _now(), "error": ""}
    _health["round_trip"] = rt
    if not ok:
        rt.update(state="failed", error=why, done_at=_now())
        if b.check == "out":  # what the check did change goes back (the stopped field waits to be made by hand)
            character = db.get(Character, b.character_id)
            for f in landed:
                add(db, character, "set", {"field": f, "value": b.before[f]}, f"Check: {b.names.get(f, f)} back")
        b.check = ""
        return
    if b.check == "out":  # each field back as D&D Beyond had it before the check
        character = db.get(Character, b.character_id)
        for f, was in b.before.items():
            add(db, character, "set", {"field": f, "value": was, "check": "back"}, f"Check: {b.names.get(f, f)} back")
    elif b.check == "back":
        rt.update(state="passed", done_at=_now())


def read_check() -> dict:
    """Server-side, no sign-in: D&D Beyond still serves the test character with every field the bridge relies on."""
    try:
        d = ddb.fetch_character_json(TEST_DDB_ID)
        missing = [k for k in ("removedHitPoints", "temporaryHitPoints", "inventory") if k not in d]
        if "inventory" in d and not all({"id", "quantity"} <= set(i) for i in d["inventory"]):
            missing.append("each item's id and quantity")
        result = {"ok": not missing, "error": ("missing " + ", ".join(missing)) if missing else "", "at": _now(), "t": time.time()}
    except ddb.DdbError as e:
        result = {"ok": False, "error": str(e), "at": _now(), "t": time.time()}
    _health["read_check"] = result
    return result


def health(db: Session) -> dict:
    """One status for every page."""
    a = awake(db)
    rc = _health["read_check"]
    if a["awake"] and (not rc or time.time() - rc["t"] > READ_CHECK_SECONDS):
        rc = read_check()  # hourly, and only while awake
    rc = rc or {"ok": True, "error": "", "at": None, "t": 0}
    rt = _health["round_trip"]
    extension = time.time() - _health["extension_at"] < EXTENSION_FRESH_SECONDS
    rows = db.execute(select(BridgeIntent.state, BridgeIntent.data).where(BridgeIntent.state.in_(OPEN))).all()
    stuck = sum(1 for s, d in rows if s == "not_yet" and not d.get("quiet"))
    waiting = sum(1 for s, d in rows if (s != "not_yet" or d.get("quiet")) and not d.get("check"))  # (waiting for its sheet counts as waiting)
    if not a["awake"]:
        state, text = "asleep", "D&D Beyond bridge · asleep"
    elif not rc["ok"]:
        state, text = "off", "D&D Beyond · problem: " + rc["error"]
    elif rt and rt["state"] == "failed":
        state, text = "off", "D&D Beyond · check failed"
    elif stuck:
        state, text = "off", f"D&D Beyond · {stuck} to make by hand"
    elif rt and rt["state"] == "running":
        state, text = "wait", "D&D Beyond · checking…"
    elif waiting:
        state, text = "wait", f"D&D Beyond · {waiting} waiting"
    elif not extension:
        state, text = "wait", "D&D Beyond · extension not connected"
    elif rt and rt["state"] == "passed":
        state, text = "live", "D&D Beyond · working"  # (and when it was checked: checked_at, in the reader's own time)
    else:
        state, text = "live", "D&D Beyond · connected, not checked yet"
    return {"state": state, "text": text, "checked_at": rt["done_at"] if text == "D&D Beyond · working" else None, "awake": a, "read_check": {k: rc[k] for k in ("ok", "error", "at")}, "round_trip": rt,
            "extension": extension, "sheets": _health["sheets"] if extension else [], "test_ddb_id": TEST_DDB_ID,
            "heard_at": datetime.fromtimestamp(_health["heard_at"], UTC).isoformat() if _health["heard_at"] else None}


# ------------------------------------------------------------------ what pages show


def state(db: Session, character: Character, user: dict | None) -> dict:
    asleep = not awake(db)["awake"]  # (time to sleep settles what's waiting first, so the page shows it)
    summary = chars.character_summary(character)
    n = numbers(character)
    mine = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state.in_(OPEN))
                           .order_by(BridgeIntent.id.desc())))
    # A change that only waits for its sheet to be open again shows as waiting: it's made by itself then (_catch_up), so
    # it isn't one to make by hand (that would make it twice)
    changes = [{"id": i.id, "label": i.label, "state": "waiting" if _for_sheet(i) else i.state, "error": i.error} for i in mine]
    stuck = [i for i in reversed(mine) if i.state == "not_yet" and not _for_sheet(i)]
    to_make = []
    if stuck and n:  # the end state only, one line per number
        final = {}
        for i in stuck:
            final.update(i.data.get("want") or {})
        to_make = [_line(n, f, v) for f, v in final.items() if _value(n, f) != v]
        older = [_as_dict(i) for i in stuck if not i.data.get("want")]  # (from before the end results were kept)
        to_make += plan(older, n)[1] if older else []
    log = [{"text": r.text, "state": r.state, "at": r.at.isoformat() if r.at else _now()}
           for r in db.scalars(select(BridgeLog).where(BridgeLog.character_id == character.id).order_by(BridgeLog.id.desc()).limit(30))]
    hp = (summary or {}).get("hit_points") or {}
    items = [{"id": i, "name": name, "quantity": n["items"][i], "heals": HEALING[name]}
             for i, name in (n.get("names") or {}).items() if name in HEALING]  # exact counts (0 is 0)
    snap = character.snapshot
    return {"character": {"id": character.id, "name": character.name, "ddb_id": character.ddb_id, "test": character.ddb_id == TEST_DDB_ID},
            "can_act": picks.can_edit(db, user, character),
            "hp": {"current": hp.get("current"), "max": hp.get("max"), "temp": hp.get("temp")},
            "items": items, "changes": changes, "to_make": to_make, "log": log, "asleep": asleep,
            "read_at": snap.fetched_at.isoformat() if snap and snap.fetched_at else None}


# ------------------------------------------------------------------ routes


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _who(request: Request, db: Session) -> dict | None:
    """askdnd's own pages by their cookie, the extension by its key (checked again each time)."""
    user = current_user(request)
    if user:
        return user
    key = request.headers.get("x-askdnd-bridge", "")
    row = db.get(BridgeKey, _hash(key)) if key else None
    return {"email": row.email, "name": ""} if row and access.level(row.email) else None


def _signed_in(request: Request, db: Session) -> dict:
    _allowed()
    user = _who(request, db)
    if not user:
        raise HTTPException(401, "Open askdnd once in this browser, signed in, to connect the extension.")
    return user


def _mine(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    user = _signed_in(request, db)
    character = db.get(Character, character_id)
    if not character or not picks.can_view(db, user, character) or not on_for(db, character):
        raise HTTPException(404)
    return character, user


def _by_ddb(db: Session, request: Request, ddb_id: str) -> tuple[Character, dict]:
    user = _signed_in(request, db)
    character = db.scalar(select(Character).where(Character.ddb_id == ddb_id, Character.copy_of_id.is_(None)).order_by(Character.id))
    if not character or not picks.can_view(db, user, character):
        raise HTTPException(404, "askdnd doesn't know this character.")
    if not on_for(db, character):
        raise HTTPException(404, "The D&D Beyond bridge isn't switched on for this character's campaign.")
    return character, user


def _json(body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/bridge/connect")
def bridge_connect(request: Request, db: Session = Depends(get_db)):
    """An askdnd page you're signed in to hands the extension a key (askdnd.js); only its hash is stored."""
    _allowed()
    user = current_user(request)
    if not user:
        return _json({"error": "Sign in to askdnd first."}, 401)
    key, email = secrets.token_urlsafe(32), user["email"].lower()
    db.add(BridgeKey(key_hash=_hash(key), email=email))
    db.flush()
    for old in db.scalars(select(BridgeKey).where(BridgeKey.email == email).order_by(BridgeKey.created_at.desc()).offset(5)):
        db.delete(old)  # each browser's newest few; an older key stops working
    db.commit()
    return _json({"key": key})


@router.get("/bridge/links")
def bridge_links(request: Request, db: Session = Depends(get_db)):
    """What the bridge's icon in Chrome opens: your characters' sheets and pages, and the table."""
    user = _signed_in(request, db)
    me = picks.user_row(db, user)
    mine = list(db.scalars(select(Character).where(Character.owner_id == me.id, Character.ddb_id.is_not(None), Character.copy_of_id.is_(None)))) if me else []
    game = next((c.ddb_campaign_id for c in mine if c.ddb_campaign_id), None)
    return _json({"characters": [{"name": c.name, "sheet": f"https://www.dndbeyond.com/characters/{c.ddb_id}", "page": f"/characters/{c.id}/battle"} for c in mine],
                  "table": f"https://www.dndbeyond.com/games/{game}" if game else ""})


@router.post("/bridge/hello")
async def bridge_hello(request: Request, db: Session = Depends(get_db)):
    """The extension's report every 30 seconds: it's on, and which D&D Beyond sheets are open."""
    _signed_in(request, db)
    body = await request.json()
    _health["extension_at"], _health["sheets"] = time.time(), [str(s) for s in body.get("sheets", [])][:20]

    def report():  # (its hourly read reaches D&D Beyond, and only while awake)
        h = health(db)
        db.commit()
        return h
    return _json(await run_in_threadpool(report))


@router.get("/bridge/health")
def bridge_health(request: Request, db: Session = Depends(get_db)):
    _signed_in(request, db)
    body = health(db)
    db.commit()  # (putting it to sleep when its time is up)
    return _json(body)


@router.post("/bridge/active")
async def bridge_active(request: Request, db: Session = Depends(get_db)):
    """Someone opened or used an askdnd page (app.js) or a D&D Beyond sheet (the extension, with `sheet`: an opened
    sheet is read when askdnd's copy is older than the party's refresh)."""
    _signed_in(request, db)
    sheet = str((await request.json()).get("sheet") or "")

    def note():
        character = _by_ddb(db, request, sheet)[0] if sheet else None
        page_opened(db, character)
        return health(db)
    return _json(await run_in_threadpool(note))


@router.post("/bridge/check")
def bridge_check(request: Request, db: Session = Depends(get_db)):
    """Run the pre-game round trip on the test character (the extension delivers it from its open sheet)."""
    character, user = _by_ddb(db, request, TEST_DDB_ID)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the test character's player runs the check.")
    reach(character, "Open the test character's D&D Beyond sheet in Chrome with the askdnd bridge to run the check.")
    full = bool(request.query_params.get("full"))
    if full and not is_admin(user):
        raise HTTPException(403, "Checking everything is for admins.")
    round_trip(db, character, full)
    db.commit()
    return _json(health(db))


@router.get("/bridge/state/{character_id:int}")
def bridge_state(character_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    body = state(db, character, user)
    db.commit()
    return _json(body)


@router.get("/bridge/by-ddb/{ddb_id}")
def bridge_by_ddb(ddb_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        character, user = _by_ddb(db, request, ddb_id)
    except HTTPException as e:
        return _json({"error": e.detail}, e.status_code)
    return _json(state(db, character, user))


@router.post("/bridge/outbox/{ddb_id}")
def bridge_outbox(ddb_id: str, request: Request, db: Session = Depends(get_db)):
    """The extension, with this character's sheet open, collects what to make there now (or nothing)."""
    character, user = _by_ddb(db, request, ddb_id)
    if picks.can_edit(db, user, character):  # the character's own player's browser, from its open sheet
        sheet_is_open(db, character)  # (asking for work: its sheet is open)
        batch = outbox(db, character)
    elif not own_sheet(character) and carried(character) and is_dm(user, character.campaign_id):
        batch = outbox(db, character, by="dm")  # its sheet is closed: its DM's browser, from any D&D Beyond page
    else:
        return _json({"batch": None})
    db.commit()
    return _json({"batch": batch})


CARRY_EVERY = 5  # seconds between a carrying browser's checks (/bridge/carry)
CARRY_MARK = timedelta(seconds=20)  # the DM's browser is marked as here at most this often (it counts for live.REACH)
CARRY_GRACE = timedelta(seconds=10)  # after a browser's last D&D Beyond page closes: another of the DM's browsers
                                     # still carrying marks it again first (CARRY_EVERY), so pills don't flick to red
CARRY_READ = 60  # seconds: a closed sheet the DM carries is read from D&D Beyond at most this often from /bridge/carry
_carry_read: dict[int, float] = {}


def _carries_for(db: Session, user: dict) -> list[Campaign]:
    """The campaigns this person is the DM of, with the DM as a backup on (the roles askdnd keeps in memory pick them, so
    the many ticks from players' browsers read no campaign at all)."""
    ids = [c["id"] for c in access.campaigns_for(user.get("email")) if is_dm(user, c["id"])]
    return [c for c in db.scalars(select(Campaign).where(Campaign.id.in_(ids)).order_by(Campaign.id)) if backup_on(c)] if ids else []


def _party(db: Session, campaign: Campaign) -> list[Character]:
    from app.models import CampaignCharacter

    return list(db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                           .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None),
                                  Character.ddb_id.is_not(None), Character.copy_of_id.is_(None)).order_by(Character.id)))


@router.post("/bridge/carry")
def bridge_carry(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """The extension, from a browser with `pages` D&D Beyond pages open (0: the last one closed). For each campaign this
    person is the DM of with the backup on, it's here while it has a page open, and makes the changes of a character
    whose own sheet is closed (`carried`). Answers which of those sheets have a change waiting now, and how soon to ask
    again (0: it carries for no campaign; it asks again within the minute, in case that changes). When the last page
    closes, the mark runs out within CARRY_GRACE rather than at once: another of the DM's browsers may still carry."""
    user = _signed_in(request, db)
    pages = body.get("pages") if isinstance(body, dict) else 0
    pages = pages if isinstance(pages, int) and pages > 0 else 0
    sheets: list[str] = []
    campaigns = _carries_for(db, user)
    now = datetime.now(UTC)
    for campaign in campaigns:
        was = dm_here(campaign)
        if not pages:
            if was:
                campaign.backup_heard_at = min(campaign.backup_heard_at, now - live.REACH + CARRY_GRACE)
        elif not was or now - campaign.backup_heard_at >= CARRY_MARK:
            campaign.backup_heard_at = now
        party = _party(db, campaign)
        if was != dm_here(campaign):  # the party's pills change colour: yellow for each closed sheet, or back
            for ch in party:
                if not own_sheet(ch):
                    realtime.announce(db, campaign.id, "character", id=ch.id)
        if not pages:
            continue
        for ch in party:
            if own_sheet(ch) or not carried(ch, campaign):
                continue
            if db.scalar(select(BridgeIntent.id).where(BridgeIntent.character_id == ch.id, BridgeIntent.state == "not_yet",
                                                       BridgeIntent.data["quiet"].astext == "true").limit(1)) \
                    and time.time() - _carry_read.get(ch.id, 0) >= CARRY_READ:
                _carry_read[ch.id] = time.time()
                heard(db, ch, saved=False)  # (one that gave up while no one could reach the sheet is made now: _catch_up)
            if db.scalar(select(BridgeIntent.id).where(BridgeIntent.character_id == ch.id,
                                                       BridgeIntent.state.in_(("waiting", "sending"))).limit(1)):
                sheets.append(ch.ddb_id)
    db.commit()
    return _json({"sheets": sheets, "every": CARRY_EVERY if pages and campaigns else 0})


@router.post("/bridge/delivered/{batch_id:int}")
async def bridge_delivered(batch_id: int, request: Request, db: Session = Depends(get_db)):
    _signed_in(request, db)
    body = await request.json()

    def settle():  # off the event loop: the read-back waits on D&D Beyond, a second at a time
        delivered(db, batch_id, bool(body.get("ok")), str(body.get("error") or "")[:200], [str(c) for c in body.get("conflicts") or []])
        db.commit()
    await run_in_threadpool(settle)
    return _json({"ok": True})


@router.post("/bridge/heard/{ddb_id}")
def bridge_heard(ddb_id: str, request: Request, pull: int = 0, db: Session = Depends(get_db)):
    """The sheet saved a change (the extension heard it), or the extension's regular pull (`?pull=1`)."""
    character, user = _by_ddb(db, request, ddb_id)
    if picks.can_edit(db, user, character):  # (a copy open in the DM's browser isn't its own sheet: the DM carries it)
        sheet_is_open(db, character)
    heard(db, character, saved=not pull)
    db.commit()
    return _json({**state(db, character, user), "check": check(character)})


@router.post("/bridge/fight/{game_id}")
def bridge_fight(game_id: str, request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """The extension, on an open D&D Beyond VTT page, says what the fight is now (app/fight.py; it only listens).
    Taken from anyone at that campaign's table, where the campaign has the bridge."""
    from app import fight

    user = _signed_in(request, db)
    if not isinstance(body, dict):
        return _json({"ok": False, "changed": False})  # (not a report: a fight only ends when it's said to)
    told = body.get("fight")
    changed = False
    for campaign in fight.campaigns_for(db, game_id[:40]):
        if not _follows(user, campaign):
            continue
        # The last VTT tab for this game closed in that browser. Only the DM's ends the fight here: a player closing
        # theirs mid-fight leaves it on (review, 2026-10-29), and a fight nobody hears any more goes after fight.STALE
        if body.get("closed"):
            if is_dm(user, campaign.id) or is_admin(user):
                changed = fight.heard(db, campaign, None) or changed
            continue
        changed = fight.heard(db, campaign, told if isinstance(told, dict) else None) or changed
    db.commit()
    return _json({"ok": True, "changed": changed})


def _follows(user: dict, campaign) -> bool:
    from app import vtt

    return vtt.on(campaign, "ddb_bridge") and (is_admin(user) or bool(access.role(user["email"], campaign.id)))


@router.get("/bridge/games")
def bridge_games(request: Request, db: Session = Depends(get_db)):
    """The D&D Beyond games the extension may tell askdnd about: those of this person's campaigns with the bridge."""
    from app import fight

    user = _signed_in(request, db)
    return _json({"games": fight.games_for(db, user, lambda c: _follows(user, c))})


@router.post("/bridge/closed/{ddb_id}")
def bridge_closed(ddb_id: str, request: Request, db: Session = Depends(get_db)):
    """The last open copy of this character's sheet in the extension's browser closed: not in step through it now
    (the Live pill says so at once, not after live.REACH)."""
    character, user = _by_ddb(db, request, ddb_id)
    if not picks.can_edit(db, user, character):  # the DM closing their copy: its own sheet may well be open still
        return _json({"ok": True})
    character.sheet_heard_at = None
    realtime.announce(db, character.campaign_id, "character", id=character.id)  # (open pages' pills and roll windows)
    db.commit()
    return _json({"ok": True})


@router.post("/bridge/drink/{character_id:int}/{item_id:int}")
def bridge_drink(character_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the character's player drinks their potions.")
    reach(character)
    name = (numbers(character).get("names") or {}).get(item_id)
    if name not in HEALING:
        raise HTTPException(400, "That isn't a healing potion this character has.")
    rolled = table_rolls.roll_formula(HEALING[name])
    dying = _at_0(db, character)
    add(db, character, "drink", {"item": item_id, "name": name, "heal": rolled["total"]},
        f"{character.name} drank a {name} (rolled {rolled['total']}: {rolled['formula']})")
    _back_up(db, character, dying, rolled["total"])
    db.commit()
    return _made(db, character, user)


@router.post("/bridge/hp/{character_id:int}")
def bridge_hp(character_id: int, request: Request, amount: int = Form(0), db: Session = Depends(get_db)):
    """Take damage or heal (+ heals, - damage), for trying the bridge on any character."""
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403)
    reach(character)
    if amount:
        dying = _at_0(db, character)
        add(db, character, "hp", {"amount": amount}, f"{character.name} {'healed' if amount > 0 else 'took'} {abs(amount)}")
        _back_up(db, character, dying, amount)
        db.commit()
    return _made(db, character, user)


def _at_0(db: Session, character: Character) -> bool:
    from app import death_saves

    return death_saves.state(as_shown(db, character, chars.character_summary(character))) is not None


def _back_up(db: Session, character: Character, was_at_0: bool, healed: int) -> None:
    """Healing from 0 Hit Points here too, not only in the hit points window (review, 2026-10-29): Unconscious ends and
    the death save marks clear (app/death_saves.py up)."""
    from app import death_saves

    if was_at_0 and healed > 0:
        death_saves.up(db, character, 0, f"{character.name}: back up from 0")


def _made(db: Session, character: Character, user: dict) -> JSONResponse:
    """A change made from the bridge page: its state, the page and its panels told (web.changed), and the extension
    told to make it now (app.js "bridgeDeliver")."""
    out = _json(state(db, character, user))
    out.headers["HX-Trigger"] = web.changed(character, deliver=True)
    return out


# ------------------------------------------------------------------ rolls made on D&D Beyond


ROLL_KINDS = {"check": "check", "save": "save", "to hit": "attack", "damage": "damage", "heal": "heal"}


def _dice(roll: dict) -> dict | None:
    """A roll from D&D Beyond's game log as a Table rolls row's numbers, or None if it isn't one."""
    r = (roll.get("rolls") or [None])[0]
    if not isinstance(r, dict):
        return None
    try:
        sets = r["diceNotation"]["set"]
        dice = [int(d["dieValue"]) for s in sets for d in s["dice"]]
        constant, total = int(r["diceNotation"].get("constant") or 0), int(r["result"]["total"])
        formula = "+".join(f"{s['count']}{s['dieType']}" for s in sets) + (f"{constant:+d}" if constant else "")
    except (KeyError, TypeError, ValueError):
        return None
    kind = ROLL_KINDS.get(str(r.get("rollType") or "").lower(), "dice")
    how = str(r.get("rollKind") or "").lower()
    mode = "adv" if "advantage" in how and "dis" not in how else "dis" if "disadvantage" in how else "normal"
    kept = None
    if kind in table_rolls.D20_KINDS and dice:
        kept = max(dice) if mode == "adv" else min(dice) if mode == "dis" else dice[0]
    return {"label": " ".join(str(roll.get("action") or "Roll").split())[:120], "kind": kind, "formula": formula[:40], "dice": dice,
            "kept": kept, "modifier": constant, "total": total, "mode": mode, "crit": "critical" in how}


JOIN_SECONDS = 120  # a D&D Beyond damage roll joins its attack when it comes this soon after


def _attack_for(db: Session, campaign_id: int, row: dict) -> int | None:
    """The attack a damage roll from D&D Beyond belongs to, or None. D&D Beyond rolls them separately and doesn't link
    them (Brett, 2026-10-29: show them as one where that takes no guessing): the damage joins the attack only when it's
    the same roller's very next roll (the same character, or the same monster), for the same attack by name, to the
    same people, within two minutes, and the attack has no damage yet. Anything else stays a roll of its own."""
    if row.get("kind") != "damage":
        return None
    who = (TableRoll.character_id == row["character_id"]) if row.get("character_id") else \
        (TableRoll.character_id.is_(None) & (TableRoll.who == row.get("who", "")))
    last = db.scalar(select(TableRoll).where(TableRoll.campaign_id == campaign_id, TableRoll.parent_id.is_(None), who)
                     .order_by(TableRoll.id.desc()).limit(1))
    if not last or last.kind != "attack" or not last.ddb_roll_id or last.label != row.get("label") or last.visibility != row.get("visibility"):
        return None
    if not last.created_at or (datetime.now(UTC) - last.created_at).total_seconds() > JOIN_SECONDS:
        return None
    if db.scalar(select(TableRoll.id).where(TableRoll.parent_id == last.id, TableRoll.kind == "damage")):
        return None
    return last.id


def _record(db: Session, campaign_id: int | None, rid: str, row: dict) -> TableRoll | None:
    """Into Table rolls once: a roll heard on two sheets (or twice on one) is the same roll (its id on D&D Beyond). A
    damage roll right after its attack joins it, as askdnd's own attack and damage show together (_attack_for)."""
    if not rid or not campaign_id or db.scalar(select(TableRoll.id).where(TableRoll.ddb_roll_id == rid)):
        return None
    t = TableRoll(campaign_id=campaign_id, ddb_roll_id=rid, parent_id=_attack_for(db, campaign_id, row), **row)
    try:
        with db.begin_nested():
            db.add(t)
    except IntegrityError:  # (another sheet's copy got there first)
        return None
    realtime.announce(db, campaign_id, "rolls")
    return t


def heard_roll(db: Session, character: Character, user_id: int | None, roll: dict) -> TableRoll | None:
    """A roll made on the character's own D&D Beyond sheet (Brett, 2026-10-27: heard on the sheet, the way Beyond20 does)
    goes into Table rolls, marked "on D&D Beyond", so a roll made there by habit still reaches the table (askdnd's own
    rolls go the other way, app/gamelog.py, and aren't heard back). Each is recorded once (its id there); who sees it
    follows who it was rolled to on D&D Beyond (everyone, the DM, or just the roller)."""
    row = _dice(roll)
    if not row:
        return None
    # Rolled to one person on D&D Beyond: to self (the target is the roller) or to the DM (anyone else)
    to = "table" if roll.get("scope") != "userId" else "self" if str(roll.get("target") or "") in ("", str(roll.get("user") or "")) else "dm"
    return _record(db, character.campaign_id, str(roll.get("id") or "")[:60],
                   {**row, "character_id": character.id, "user_id": user_id, "visibility": to})


def heard_in_game(db: Session, hearer: Character, message: dict) -> TableRoll | None:
    """A roll someone else made in the game, heard on a player's open sheet (step 5.4, Brett 2026-10-28): D&D Beyond's game
    log brings every sheet in the game the rolls made there. The DM's for a monster go into Table rolls as that
    monster's ("Ogre"), with the damage type its attack in the campaign's rules data names (D&D Beyond's roll doesn't
    carry one), so a player can apply the hit; a roll for a character at the table made elsewhere (the encounter's
    page) goes in as that character's. Others' plain dice stay out (whose they are isn't known), and so do askdnd's own
    rolls sent to the Game Log (app/gamelog.py): Table rolls has them already."""
    if message.get("source") == "askdnd":
        return None
    d, ctx = message.get("data") or {}, (message.get("data") or {}).get("context") or {}
    roll = {"id": d.get("rollId"), "action": d.get("action"), "rolls": d.get("rolls")}
    rid, what, campaign = str(d.get("rollId") or "")[:60], str(message.get("entityType") or ""), hearer.campaign_id
    if what == "character":
        ch = db.scalar(select(Character).where(Character.ddb_id == str(message.get("entityId")), Character.copy_of_id.is_(None)))
        if not ch or ch.campaign_id != campaign or message.get("messageScope") != "gameId":
            return None
        return heard_roll(db, ch, ch.owner_id, {**roll, "scope": "gameId"})
    if what != "monster":
        return None
    row = _dice(roll)
    if not row:
        return None
    name = " ".join(str(ctx.get("name") or "A monster").split())[:80]
    if row["kind"] == "damage":
        from app import hit_points
        kind, kind_from = hit_points.attack_type(db, campaign, name, row["label"])
        row["parts"] = [{"label": row["label"], "kind": kind, "kind_from": kind_from, "formula": row["formula"], "dice": row["dice"],
                         "total": row["total"]}]
    return _record(db, campaign, rid, {**row, "who": name, "visibility": "table" if message.get("messageScope") == "gameId" else "dm"})


@router.post("/bridge/roll/{ddb_id}")
def bridge_roll(ddb_id: str, request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """The extension heard a roll on this character's D&D Beyond sheet. Only the character's own player's browser
    records it (like the outbox)."""
    character, user = _by_ddb(db, request, ddb_id)
    if not picks.can_edit(db, user, character):
        return _json({"ok": False})
    me = picks.user_row(db, user)
    row = heard_roll(db, character, me.id if me else None, body) if isinstance(body, dict) else None
    db.commit()
    return _json({"ok": row is not None})


@router.post("/bridge/others-roll/{ddb_id}")
def bridge_others_roll(ddb_id: str, request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """The extension heard someone else's roll in the game on this character's sheet (heard_in_game). Only the
    character's own player's browser passes them on."""
    character, user = _by_ddb(db, request, ddb_id)
    if not picks.can_edit(db, user, character):
        return _json({"ok": False})
    row = heard_in_game(db, character, body) if isinstance(body, dict) else None
    db.commit()
    return _json({"ok": row is not None})


# ------------------------------------------------------------------ changes from askdnd's pages


SETS = {"inspiration": bool, "condition": bool, "exhaustion": int, "equipped": bool, "attuned": bool, "container": int}
USES = ("slot", "pact", "uses", "charges", "coin", "hitdice")


def _change(n: dict, body: dict) -> tuple[str, dict] | None:
    """A change asked for by a page, checked: the intent it makes, or None. Only what the bridge can write."""
    kind, raw = body.get("kind"), n["raw"]
    field = str(body.get("field") or "")
    fk, _, arg = field.partition(":")
    if kind in ("set", "use") and field not in fields(n):
        return None  # only a field the bridge follows on this character (no item it hasn't got)
    try:
        if kind == "set" and fk in SETS:
            v = body.get("value")
            if not isinstance(v, SETS[fk]) or (fk == "condition" and int(arg) not in ddb_fields.CONDITIONS) or (fk == "exhaustion" and not 0 <= v <= 6) \
                    or (fk == "container" and str(v) != str(raw.get("id")) and not (ddb_fields.pick(raw, ["inventory", {"id": v}]) or {}).get("definition", {}).get("isContainer")):
                return None
            return "set", {"field": field, "value": v}
        if kind == "use" and fk in USES[:-1] and isinstance(body.get("delta"), int) and 0 < abs(body["delta"]) <= 100000:
            most = None if fk == "coin" else ddb_sheet.most(raw, fk, arg)  # (worked out from the sheet, never the page's)
            if fk != "coin" and most is None:
                return None
            return "use", {"field": field, "delta": body["delta"], **({"max": most} if most is not None else {})}
        if kind == "death" and (body.get("reset") is True or body.get("fail") in (1, 2) or body.get("success") in (1, 2)):
            return "death", {k: body[k] for k in ("fail", "success", "reset") if k in body}
        if kind == "short_rest" and isinstance(body.get("spend"), dict) and body["spend"] and \
                all(isinstance(v, int) and 0 < v <= 20 and ddb_fields.pick(raw, ["classes", {"id": k}]) for k, v in body["spend"].items()):
            return "short_rest", {"spend": {str(k): v for k, v in body["spend"].items()}}
        row = ddb_fields.pick(raw, ["inventory", {"id": body.get("item")}]) if body.get("item") is not None else None
        if kind == "remove_item" and row:
            return "remove_item", {"item": row["id"], "name": ddb_fields.item_name(raw, row["id"])}
        if kind == "add_item" and row and isinstance(body.get("quantity", 1), int) and 0 < body.get("quantity", 1) <= 100:
            d = row.get("definition") or {}  # another of an item the character has (D&D Beyond's own definition of it)
            return "add_item", {"definition": d["id"], "entityTypeId": d["entityTypeId"], "quantity": body.get("quantity", 1), "name": d.get("name") or "an item"}
    except (TypeError, ValueError, KeyError):
        return None
    return None


@router.post("/bridge/change/{character_id:int}")
def bridge_change(character_id: int, request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """Any change a player makes in play, as an intent (`kind`: set, use, death, short_rest, remove_item, add_item), for
    the bridge to make on D&D Beyond. What the page shows comes from D&D Beyond once it has it."""
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the character's player changes their sheet.")
    reach(character)
    n = numbers(character)
    made = _change(n, body) if n and isinstance(body, dict) else None
    if not made:
        raise HTTPException(400, "That isn't a change askdnd can make on D&D Beyond.")
    kind, data = made
    add(db, character, kind, data, f"{character.name}: {describe(kind, data, n)}")
    db.commit()
    return _json(state(db, character, user))


@router.post("/bridge/retry/{intent_id:int}")
def bridge_retry(intent_id: int, request: Request, db: Session = Depends(get_db)):
    user = _signed_in(request, db)
    it = db.get(BridgeIntent, intent_id)
    if it is not None:
        reach(db.get(Character, it.character_id))
    retry(db, intent_id)
    db.commit()
    return _for_intent(db, intent_id, user)


@router.post("/bridge/dismiss/{intent_id:int}")
def bridge_dismiss(intent_id: int, request: Request, db: Session = Depends(get_db)):
    user = _signed_in(request, db)
    dismiss(db, intent_id)
    db.commit()
    return _for_intent(db, intent_id, user)


def _for_intent(db: Session, intent_id: int, user: dict) -> JSONResponse:
    it = db.get(BridgeIntent, intent_id)
    character = db.get(Character, it.character_id) if it else None
    return _made(db, character, user) if character else _json({"ok": True})


@router.get("/characters/{character_id:int}/bridge")
def bridge_page(character_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    return templates.TemplateResponse(request, "bridge.html", {"c": character, "state": state(db, character, user)})


# ------------------------------------------------------------------ Manage › askdnd › D&D Beyond bridge (admins)
@router.get("/manage/bridge")
def manage_page(request: Request, db: Session = Depends(get_db)):
    """Whether the bridge is awake and why, and its timers."""
    _allowed()
    _, stop = web.require(request, is_admin, "The D&D Beyond bridge's settings are for admins.")
    if stop:
        return stop
    active(db)  # (opening this page is using askdnd, as on every page)
    h = health(db)
    db.commit()
    tm = timers(db)
    return templates.TemplateResponse(request, "manage_bridge.html", {
        "health": h, "a": h["awake"], "last": _wake_row(db)[1].get("last"), "timers": TIMERS,
        "now": {key: round(tm[key] / unit) for key, _, _, unit, *_ in TIMERS},
        "toast": request.session.pop("toast", None)})


@router.get("/manage/bridge/log/{character_id:int}")
def manage_log(character_id: int, request: Request, limit: int = 200, db: Session = Depends(get_db)):
    """A character's bridge log further back than its pages show (30), with the batches that made each change: when,
    how it ended, how many tries, how old askdnd's copy was (null: read fresh), what D&D Beyond held and what it should
    hold (Brett, 2026-11-02: for the live test's analysis). Admins; JSON."""
    _allowed()
    _, stop = web.require(request, is_admin, "The D&D Beyond bridge's log is for admins.")
    if stop:
        return stop
    character = db.get(Character, character_id)
    if character is None:
        return _json({"error": "No such character."}, 404)
    limit = max(1, min(limit, 500))
    log = [{"at": r.at.isoformat(), "state": r.state, "text": r.text}
           for r in db.scalars(select(BridgeLog).where(BridgeLog.character_id == character.id).order_by(BridgeLog.id.desc()).limit(limit))]
    batches = [{"id": b.id, "at": b.created_at.isoformat(), "state": b.state, "attempts": b.attempts, "copy_age": b.copy_age,
                "intents": [i.label for i in _intents_of(db, b)], "before": b.before, "target": b.target, "error": b.error}
               for b in db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id).order_by(BridgeBatch.id.desc()).limit(limit))]
    return _json({"character": {"id": character.id, "name": character.name}, "log": log, "batches": batches})


@router.post("/manage/bridge")
async def save_timers(request: Request, db: Session = Depends(get_db)):
    _allowed()
    _, stop = web.require(request, is_admin, "The D&D Beyond bridge's settings are for admins.")
    if stop:
        return stop
    form = await request.form()
    row = db.get(ToolSetting, TIMERS_KEY) or ToolSetting(key=TIMERS_KEY)
    if form.get("reset"):
        row.value = ""
        request.session["toast"] = "The bridge's timers are back to askdnd's own."
    else:
        saved = {}
        for key, *_, lo, hi in TIMERS:
            try:
                saved[key] = min(max(int(form.get(key, "")), lo), hi)
            except ValueError:
                pass
        row.value = json.dumps(saved)
        request.session["toast"] = "Saved. The bridge follows the new timers now."
    db.add(row)
    db.commit()
    return RedirectResponse("/manage/bridge", status_code=303)
