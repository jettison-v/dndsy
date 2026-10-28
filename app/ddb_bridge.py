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
   character page re-reads that character when askdnd's copy is older than live.AUTO_MIN_AGE. Game Mode keeps it awake
   for the game timer (6 hours) however quiet the table is, with a warning before, and Keep going. Asleep, only the
   extension's background pull and the hourly check stop. A change still waiting keeps it awake up to the wait timer
   (6 hours) after anyone last used it; then it's listed to make by hand. Admins set the timers on Manage › askdnd ›
   D&D Beyond bridge (TIMERS); the state is in tool_settings (bridge_awake).
7. **Health.** The extension reports in every minute; askdnd reads the test character every hour (no sign-in needed);
   a round trip on the test character (1 hit point and a Candle out and back) runs from the status pill before a game,
   and Check everything (Manage › askdnd › D&D Beyond bridge) runs every kind of change out and back; every page's
   menu bar shows how it stands.
8. **Everything a player changes in play** (ddb_fields: what each field is, where D&D Beyond keeps it, the request
   that writes it): hit points, death saves, Heroic Inspiration, conditions, Exhaustion, Hit Dice (as a Short Rest),
   spell and Pact Magic slots, prepared spells, limited uses, an item's count, equipped, attuned, charges, container,
   coins, adding and removing an item. A roll made on the sheet is only heard, into Table rolls ("on D&D Beyond").
   After a change, every open copy of the sheet shows D&D Beyond's numbers in place (ddb-page.js `show`).

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

import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, config, ddb, ddb_fields, live, picks, realtime, table_rolls, web
from app import characters as chars
from app.auth import current_user, is_admin
from app.db import get_db
from app.models import BridgeBatch, BridgeIntent, BridgeKey, BridgeLog, Character, TableRoll, ToolSetting
from app.templating import templates

router = APIRouter()

HEALING = {"Potion of Healing": "2d4+2", "Potion of Greater Healing": "4d4+4", "Potion of Superior Healing": "8d4+8",
           "Potion of Supreme Healing": "10d4+20"}  # SRD 5.2.1
TEST_DDB_ID = "172836541"  # Vi, Brett's test character on D&D Beyond (not in the table's campaign)
TEST_ITEM = "Candle"  # the round trip takes one and puts it back
MAX_ATTEMPTS = 3
RETRY_SECONDS = (0, 5, 20)  # how long a batch that didn't land waits before it's sent again
SENDING_SECONDS = 30  # a batch the extension took but never answered for is offered again
EXTENSION_FRESH_SECONDS = 90  # the extension reports every 30 seconds
READ_CHECK_SECONDS = 3600
OPEN = ("waiting", "sending", "not_yet")
AWAKE_KEY = "bridge_awake"
TIMERS_KEY = "bridge_timers"  # admins change these on Manage › askdnd › D&D Beyond bridge; askdnd's own below
# (key, label, what it's for, unit in seconds, unit's name, default, lowest, highest)
TIMERS = (
    ("idle", "Stays awake after anyone was here", "After someone last opened or used askdnd or a D&D Beyond sheet.", 60, "minutes", 30, 5, 240),
    ("game", "Game Mode keeps it on for", "However quiet the table is, from when Game Mode is switched on (or Keep going).", 3600, "hours", 6, 1, 12),
    ("warn", "Warning before Game Mode's time is up", "A message on every page, with Keep going.", 60, "minutes", 10, 1, 60),
    ("wait", "A waiting change gives up after", "With no one using askdnd or D&D Beyond; then it's listed to make by hand.", 3600, "hours", 6, 1, 24),
)
_health = {"extension_at": 0.0, "sheets": [], "heard_at": 0.0, "read_check": None, "round_trip": None}  # a heartbeat, in memory


def _local_only():
    if not config.DDB_BRIDGE:  # (never in production: app/config.py)
        raise HTTPException(404)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lock(db: Session, character_id: int) -> None:
    """Hold this character's row until the transaction ends: one copy of the app at a time builds or settles its batch."""
    db.execute(select(Character.id).where(Character.id == character_id).with_for_update())


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


def awake(db: Session) -> dict:
    """{"awake": bool, "until", "game_until", "why"}: awake while someone used askdnd or a sheet in the last idle timer,
    while Game Mode's time runs, or while a change is still waiting (up to the wait timer after anyone was last here)."""
    row, w = _wake_row(db)
    tm = timers(db)
    now, last, game_until = time.time(), w.get("last", 0), w.get("game_until") or 0
    open_changes = db.scalar(select(BridgeIntent.id).where(BridgeIntent.state.in_(("waiting", "sending"))).limit(1))
    if open_changes and now - last > tm["wait"]:
        _stop_waiting(db, f"No one used askdnd or D&D Beyond for {_span(tm['wait'])}, so the bridge went to sleep before D&D Beyond had it.")
        open_changes = None
    game = game_until > now
    if game or now - last <= tm["idle"] or open_changes:
        return {"awake": True, "until": max(game_until, last + tm["idle"]), "game_until": game_until if game else None,
                "warn": tm["warn"]}
    return {"awake": False, "game_until": None, "warn": tm["warn"],
            "why": f"Asleep: no one has opened askdnd or a D&D Beyond sheet for {_span(tm['idle'])}."}


def _span(seconds: float) -> str:
    return f"{seconds / 3600:g} hours" if seconds >= 3600 else f"{seconds / 60:g} minutes"


def _stop_waiting(db: Session, why: str) -> None:
    for b in db.scalars(select(BridgeBatch).where(BridgeBatch.state.in_(("sending", "ready")))):
        b.state, b.error = "stopped", why
    for it in db.scalars(select(BridgeIntent).where(BridgeIntent.state.in_(("waiting", "sending")))):
        it.state, it.error = "not_yet", why


def active(db: Session) -> None:
    """Someone opened or used an askdnd page or a D&D Beyond sheet (or made a change, or ran the check): awake now,
    and for the idle timer more."""
    row, w = _wake_row(db)
    w["last"] = time.time()
    row.value = json.dumps(w)


def game(db: Session, on: bool) -> None:
    """Game Mode switched on (or Keep going): awake for the game timer however quiet. Off: back to following activity."""
    row, w = _wake_row(db)
    w["last"] = time.time()
    w["game_until"] = w["last"] + timers(db)["game"] if on else None
    row.value = json.dumps(w)


def page_opened(db: Session, character: Character | None) -> None:
    """An askdnd page opened (a character's, when `character`): awake, and that character re-read from D&D Beyond when
    askdnd's copy is older than Game Mode's refresh, so what the page shows is current."""
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


def plan(intents: list[dict], n: dict) -> tuple[dict, list[str], list[tuple[dict, str]], dict]:
    """The end state of these intents built on what D&D Beyond has now (`n`): the final value of each field they touch,
    one line per field to show, any intent that can't happen any more (with why), and what an added item needs."""
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
                soak = min(temp, -d["amount"])
                temp, removed = temp - soak, min(n["max"], removed + (-d["amount"] - soak))
            vals["hp"] = {"removedHitPoints": removed, "temporaryHitPoints": temp}
            touched.append("hp")
        elif kind == "item":
            f = f"item:{d['item']}"
            if get(f) is None or get(f) + d["delta"] < 0:
                no(it, f"D&D Beyond doesn't have enough {d['name']}.")
                continue
            vals[f] = get(f) + d["delta"]
            touched.append(f)
        elif kind == "set":  # an absolute value: on or off, a level, prepared, where an item is, or back as it was
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
        elif kind == "add_item":
            f = f"add:{d['definition']}"
            vals[f] = (get(f) or 0) + d["quantity"]
            before = extra.get(f, {}).get("quantity", 0)
            extra[f] = {"entityTypeId": d["entityTypeId"], "quantity": before + d["quantity"], "container": d.get("container")}
            touched.append(f)
    target, lines = {}, []
    for f in dict.fromkeys(touched):
        if vals[f] == _value(n, f):
            continue  # (a change and its undo in one batch, or D&D Beyond has it already: nothing to write)
        target[f] = vals[f]
        line = ddb_fields.show(n["raw"], f, vals[f], n["max"])
        lines.append(f"{line[:1].upper()}{line[1:]} (D&D Beyond has {ddb_fields.text(n['raw'], f, _value(n, f), n['max'])})")
    return target, lines, impossible, extra


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


def outbox(db: Session, character: Character) -> dict | None:
    """The batch the extension should make on this character's sheet now, or None. A new batch is built on a fresh read
    of D&D Beyond, so its totals sit on whatever D&D Beyond has this moment."""
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
        return {"id": live.id, "ops": live.ops}
    waiting = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state == "waiting")
                              .order_by(BridgeIntent.id)))
    if not waiting:
        return None
    chars.refresh(db, character)
    n = numbers(character)
    if not n:
        return None
    dicts = [_as_dict(i) for i in waiting]
    target, _lines, impossible, extra = plan(dicts, n)
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
    batch = BridgeBatch(character_id=character.id, intents=[i.id for i in keep], ops=_ops(character, target, n, extra),
                        before={f: _value(n, f) for f in target}, target=target, state="sending", attempts=1, sent_at=now,
                        next_at=0, check=keep[0].data.get("check", ""), names={f: ddb_fields.name(n["raw"], f) for f in target})
    db.add(batch)
    for i in keep:  # (each intent's own fields: a batch stopped part way settles the ones D&D Beyond has)
        i.state, i.data = "sending", {**i.data, "fields": sorted(plan([_as_dict(i)], n)[0])}
    db.flush()
    return {"id": batch.id, "ops": batch.ops}


def _intents_of(db: Session, b: BridgeBatch) -> list[BridgeIntent]:
    return list(db.scalars(select(BridgeIntent).where(BridgeIntent.id.in_(b.intents)).order_by(BridgeIntent.id)))


def _settle(db: Session, b: BridgeBatch) -> None:
    b.state = "done"
    for it in _intents_of(db, b):
        it.state = "live"
        _log(db, b.character_id, it.label, "live")
    _check_step(db, b, True)


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
            b.state = "replanned"
            for it in _intents_of(db, b):
                it.state, it.data = "waiting", {**it.data, "replans": it.data.get("replans", 0) + 1}
        else:
            _stop(db, b, f"D&D Beyond's {_say(conflicts, b)} changed while askdnd was writing it.")
        return
    if not ok:  # couldn't reach the sheet or D&D Beyond: try again later, on its own
        _again(db, b, error or "The change couldn't be made.")
        return
    now = {}
    for attempt in range(4):  # D&D Beyond can take a moment to serve what it just saved
        if attempt:
            time.sleep(1)
        chars.refresh(db, character)
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
        _again(db, b, "D&D Beyond answered OK but didn't keep it.")


def _say(fs: list[str], b: BridgeBatch) -> str:
    return " and ".join(dict.fromkeys(b.names.get(f, "numbers") for f in fs))


def _again(db: Session, b: BridgeBatch, why: str) -> None:
    if b.attempts >= MAX_ATTEMPTS:
        _stop(db, b, f"{why} Tried {MAX_ATTEMPTS} times.")
        return
    b.state, b.error = "ready", why[:400]
    b.next_at = time.time() + RETRY_SECONDS[min(b.attempts, len(RETRY_SECONDS) - 1)]
    b.attempts += 1


def _stop(db: Session, b: BridgeBatch, why: str, missing: list[str] | None = None) -> None:
    """The batch stops. With `missing` (the read-back's fields D&D Beyond doesn't hold as written), the rest landed: an
    intent all of whose fields D&D Beyond has is made (never listed to make again), the others wait to be made by hand."""
    b.state, b.error = "stopped", why[:400]
    bad = set(b.target if missing is None else missing)
    for it in _intents_of(db, b):
        if missing is not None and not bad.intersection(it.data.get("fields", b.target)):
            it.state = "live"
            _log(db, b.character_id, it.label, "live")
        else:
            it.state, it.error = "not_yet", (why + " Nothing was written over.")[:400]
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
    _lock(db, character.id)
    chars.refresh(db, character)
    n = numbers(character)
    if not n:
        return
    open_batches = list(db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id, BridgeBatch.state.in_(("sending", "ready")))))
    for b in open_batches:
        if all(_value(n, f) == v for f, v in b.target.items()):
            _settle(db, b)


def seen(db: Session, character: Character, before: dict | None, after: dict, summary: dict | None) -> None:
    """Every read of a character from D&D Beyond (the bridge's, Game Mode's refresh, a page opening) passes through
    here with askdnd's last copy (`before`) and the new one: whatever D&D Beyond changed itself goes in the log as
    "On D&D Beyond", whichever read saw it first. What askdnd is writing (or just wrote) isn't D&D Beyond's change."""
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


def check(character: Character) -> list[dict]:
    """What askdnd just read from D&D Beyond, field by field, for the extension to compare with each open copy of the
    sheet: a copy holding anything else shows D&D Beyond's numbers (extension/askdnd-bridge/ddb-page.js `check`)."""
    return [{"read": ddb_fields.steps(f), "value": v} for f, v in fields(numbers(character)).items()]


def retry(db: Session, intent_id: int) -> None:
    it = db.get(BridgeIntent, intent_id)
    if it and it.state == "not_yet":
        it.state, it.error = "waiting", ""


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
    for f in (first("prepared:"), first("equipped:", canequip), first("attuned:")):
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
    stuck = sum(1 for s, _ in rows if s == "not_yet")
    waiting = sum(1 for s, d in rows if s != "not_yet" and not d.get("check"))
    when = (lambda iso: datetime.fromisoformat(iso).astimezone().strftime("%-I:%M %p"))
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
        state, text = "live", f"D&D Beyond · working (checked {when(rt['done_at'])})"
    else:
        state, text = "live", "D&D Beyond · connected, not checked yet"
    return {"state": state, "text": text, "awake": a, "read_check": {k: rc[k] for k in ("ok", "error", "at")}, "round_trip": rt,
            "extension": extension, "sheets": _health["sheets"] if extension else [], "test_ddb_id": TEST_DDB_ID,
            "heard_at": datetime.fromtimestamp(_health["heard_at"], UTC).isoformat() if _health["heard_at"] else None}


# ------------------------------------------------------------------ what pages show


def state(db: Session, character: Character, user: dict | None) -> dict:
    asleep = not awake(db)["awake"]  # (time to sleep settles what's waiting first, so the page shows it)
    summary = chars.character_summary(character)
    n = numbers(character)
    mine = list(db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == character.id, BridgeIntent.state.in_(OPEN))
                           .order_by(BridgeIntent.id.desc())))
    changes = [{"id": i.id, "label": i.label, "state": i.state, "error": i.error} for i in mine]
    by_hand = [_as_dict(i) for i in reversed(mine) if i.state == "not_yet"]
    to_make = plan(by_hand, n)[1] if by_hand and n else []  # the end state only, one line per number
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
    _local_only()
    user = _who(request, db)
    if not user:
        raise HTTPException(401, "Open askdnd (localhost:8000) once in this browser to connect the extension.")
    return user


def _mine(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    user = _signed_in(request, db)
    character = db.get(Character, character_id)
    if not character or not picks.can_view(db, user, character):
        raise HTTPException(404)
    return character, user


def _by_ddb(db: Session, request: Request, ddb_id: str) -> tuple[Character, dict]:
    user = _signed_in(request, db)
    character = db.scalar(select(Character).where(Character.ddb_id == ddb_id, Character.copy_of_id.is_(None)).order_by(Character.id))
    if not character or not picks.can_view(db, user, character):
        raise HTTPException(404, "askdnd doesn't know this character.")
    return character, user


def _json(body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/bridge/connect")
def bridge_connect(request: Request, db: Session = Depends(get_db)):
    """An askdnd page you're signed in to hands the extension a key (askdnd.js); only its hash is stored."""
    _local_only()
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
    sheet is read when askdnd's copy is older than Game Mode's refresh)."""
    _signed_in(request, db)
    sheet = str((await request.json()).get("sheet") or "")

    def note():
        character = _by_ddb(db, request, sheet)[0] if sheet else None
        page_opened(db, character)
        return health(db)
    return _json(await run_in_threadpool(note))


@router.post("/bridge/game")
async def bridge_game(request: Request, db: Session = Depends(get_db)):
    """Game Mode switched on (or Keep going): awake for the game. Off: back to following what people do."""
    _signed_in(request, db)
    game(db, bool((await request.json()).get("on")))
    db.commit()
    return _json(health(db))


@router.post("/bridge/check")
def bridge_check(request: Request, db: Session = Depends(get_db)):
    """Run the pre-game round trip on the test character (the extension delivers it from its open sheet)."""
    character, user = _by_ddb(db, request, TEST_DDB_ID)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the test character's player runs the check.")
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
    if not picks.can_edit(db, user, character):
        return _json({"batch": None})  # only the character's own player's browser writes their sheet
    batch = outbox(db, character)
    db.commit()
    return _json({"batch": batch})


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
    heard(db, character, saved=not pull)
    db.commit()
    return _json({**state(db, character, user), "check": check(character)})


@router.post("/bridge/drink/{character_id:int}/{item_id:int}")
def bridge_drink(character_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the character's player drinks their potions.")
    name = (numbers(character).get("names") or {}).get(item_id)
    if name not in HEALING:
        raise HTTPException(400, "That isn't a healing potion this character has.")
    rolled = table_rolls.roll_formula(HEALING[name])
    add(db, character, "drink", {"item": item_id, "name": name, "heal": rolled["total"]},
        f"{character.name} drank a {name} (rolled {rolled['total']}: {rolled['formula']})")
    db.commit()
    return _json(state(db, character, user))


@router.post("/bridge/hp/{character_id:int}")
async def bridge_hp(character_id: int, request: Request, db: Session = Depends(get_db)):
    """Take damage or heal (+ heals, - damage), for trying the bridge on any character."""
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403)
    amount = int((await request.json()).get("amount", 0))
    if amount:
        add(db, character, "hp", {"amount": amount}, f"{character.name} {'healed' if amount > 0 else 'took'} {abs(amount)}")
        db.commit()
    return _json(state(db, character, user))


# ------------------------------------------------------------------ rolls made on D&D Beyond


ROLL_KINDS = {"check": "check", "save": "save", "to hit": "attack", "damage": "damage", "heal": "heal"}


def heard_roll(db: Session, character: Character, user: dict, roll: dict) -> TableRoll | None:
    """A roll made on the character's own D&D Beyond sheet (Brett, 2026-10-27: heard on the sheet, the way Beyond20 does)
    goes into Table rolls, marked "on D&D Beyond", so a roll made there by habit still reaches the table. Only heard:
    askdnd never writes its own rolls into D&D Beyond's game log. Each is recorded once (its id there); who sees it
    follows who it was rolled to on D&D Beyond (everyone, or just the roller)."""
    rid = str(roll.get("id") or "")[:60]
    r = (roll.get("rolls") or [None])[0]
    campaign = character.campaign_id
    if not rid or not isinstance(r, dict) or not campaign or db.scalar(select(TableRoll.id).where(TableRoll.ddb_roll_id == rid)):
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
    me = picks.user_row(db, user)
    private = roll.get("scope") == "userId"  # rolled to self (or to the DM) on D&D Beyond
    row = TableRoll(campaign_id=campaign, character_id=character.id, user_id=me.id if me else None,
                    label=" ".join(str(roll.get("action") or "Roll").split())[:120], kind=kind, formula=formula[:40], dice=dice,
                    kept=kept, modifier=constant, total=total, mode=mode, visibility="self" if private else "table",
                    crit="critical" in how, ddb_roll_id=rid)
    db.add(row)
    realtime.announce(db, campaign, "rolls")
    return row


@router.post("/bridge/roll/{ddb_id}")
async def bridge_roll(ddb_id: str, request: Request, db: Session = Depends(get_db)):
    """The extension heard a roll on this character's D&D Beyond sheet. Only the character's own player's browser
    records it (like the outbox)."""
    character, user = _by_ddb(db, request, ddb_id)
    if not picks.can_edit(db, user, character):
        return _json({"ok": False})
    body = await request.json()
    row = heard_roll(db, character, user, body) if isinstance(body, dict) else None
    db.commit()
    return _json({"ok": row is not None})


# ------------------------------------------------------------------ changes from askdnd's pages


SETS = {"inspiration": bool, "condition": bool, "exhaustion": int, "equipped": bool, "attuned": bool, "prepared": bool, "container": int}
USES = ("slot", "pact", "uses", "charges", "coin", "hitdice")


def _change(n: dict, body: dict) -> tuple[str, dict] | None:
    """A change asked for by a page, checked: the intent it makes, or None. Only what the bridge can write."""
    kind, raw = body.get("kind"), n["raw"]
    field = str(body.get("field") or "")
    fk, _, arg = field.partition(":")
    if kind in ("set", "use") and field not in fields(n):
        return None  # only a field the bridge follows on this character (no cantrip's "prepared", no item it hasn't got)
    try:
        if kind == "set" and fk in SETS:
            v = body.get("value")
            if not isinstance(v, SETS[fk]) or (fk == "condition" and int(arg) not in ddb_fields.CONDITIONS) or (fk == "exhaustion" and not 0 <= v <= 6) \
                    or (fk == "container" and str(v) != str(raw.get("id")) and not (ddb_fields.pick(raw, ["inventory", {"id": v}]) or {}).get("definition", {}).get("isContainer")):
                return None
            return "set", {"field": field, "value": v}
        if kind == "use" and fk in USES[:-1] and isinstance(body.get("delta"), int) and 0 < abs(body["delta"]) <= 100000:
            return "use", {"field": field, "delta": body["delta"], **({"max": body["max"]} if isinstance(body.get("max"), int) else {})}
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
async def bridge_change(character_id: int, request: Request, db: Session = Depends(get_db)):
    """Any change a player makes in play, as an intent (`kind`: set, use, death, short_rest, remove_item, add_item), for
    the bridge to make on D&D Beyond. What the page shows comes from D&D Beyond once it has it."""
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the character's player changes their sheet.")
    body = await request.json()
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
    _signed_in(request, db)
    retry(db, intent_id)
    db.commit()
    return _json({"ok": True})


@router.post("/bridge/dismiss/{intent_id:int}")
def bridge_dismiss(intent_id: int, request: Request, db: Session = Depends(get_db)):
    _signed_in(request, db)
    dismiss(db, intent_id)
    db.commit()
    return _json({"ok": True})


@router.get("/characters/{character_id:int}/bridge")
def bridge_page(character_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    return templates.TemplateResponse(request, "bridge.html", {"c": character, "state": state(db, character, user)})


# ------------------------------------------------------------------ Manage › askdnd › D&D Beyond bridge (admins)
@router.get("/manage/bridge")
def manage_page(request: Request, db: Session = Depends(get_db)):
    """Whether the bridge is awake and why, and its timers."""
    _local_only()
    _, stop = web.require(request, is_admin, "The D&D Beyond bridge's settings are for admins.")
    if stop:
        return stop
    active(db)  # (opening this page is using askdnd, as on every page)
    h = health(db)
    db.commit()
    tm = timers(db)
    clock = lambda t: datetime.fromtimestamp(t).strftime("%-I:%M %p")  # noqa: E731
    return templates.TemplateResponse(request, "manage_bridge.html", {
        "health": h, "a": h["awake"], "last": _wake_row(db)[1].get("last"), "timers": TIMERS,
        "now": {key: round(tm[key] / unit) for key, _, _, unit, *_ in TIMERS}, "clock": clock,
        "clock_iso": lambda iso: datetime.fromisoformat(iso).astimezone().strftime("%-I:%M %p"),
        "toast": request.session.pop("toast", None)})


@router.post("/manage/bridge")
async def save_timers(request: Request, db: Session = Depends(get_db)):
    _local_only()
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
