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
6. **Asleep unless the game is on** (Brett, 2026-10-27: don't waste D&D Beyond's resources). The bridge sleeps by
   default: no reads of D&D Beyond on saves, no pulls, no hourly check; the extension only asks the local askdnd
   whether it's awake. Game Mode, a change made in askdnd, or the check wakes it; it sleeps again after IDLE_SECONDS
   without play (a change on a sheet or in askdnd; pulls don't count), after MAX_SECONDS however it was woken, or when
   Game Mode is switched off, and never while a change is still waiting. The state is in tool_settings (bridge_awake).
7. **Health.** The extension reports in every minute; askdnd reads the test character every hour (no sign-in needed);
   a round trip on the test character (1 hit point and a Candle out and back) runs from the status pill before a game;
   every page's menu bar shows how it stands.

States for a change: waiting (and sending), live (D&D Beyond has it), not_yet (can't be made; the end state is listed
to make by hand), plus seen in the log (changed on D&D Beyond itself). The outbox, the batches, the log and the
extension's key are in the database (BridgeIntent, BridgeBatch, BridgeLog, BridgeKey), so a restart, a crash or a
second copy of the app loses and doubles nothing; each character's row is locked while its batch is built or settled,
so two copies never build two batches for one character. Only the extension's heartbeat is kept in memory (it comes
back within 30 seconds). Local only: on where DDB_BRIDGE=1, never in production.

The extension makes only the two requests it knows (OPS), so a page can't ask it to change anything else; it calls
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
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, config, ddb, picks, table_rolls
from app import characters as chars
from app.auth import current_user
from app.db import get_db
from app.models import BridgeBatch, BridgeIntent, BridgeKey, BridgeLog, Character, ToolSetting
from app.templating import templates

router = APIRouter()

HP_PATH = "/character/v5/life/hp/damage-taken"
ITEM_PATH = "/character/v5/inventory/item/quantity"
OPS = {HP_PATH: ("characterId", "removedHitPoints", "temporaryHitPoints"), ITEM_PATH: ("characterId", "id", "quantity")}
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
IDLE_SECONDS = 30 * 60  # asleep again after this long without play
MAX_SECONDS = 6 * 3600  # and after this long however it was woken
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


def awake(db: Session) -> dict:
    """{"awake": bool, ...}: asleep unless something woke it recently; puts it to sleep when its time is up (never while
    a change is still waiting: that's play too)."""
    row, w = _wake_row(db)
    now = time.time()
    if not w.get("on"):
        return {"awake": False, "why": w.get("why", "Asleep until the game starts.")}
    open_changes = db.scalar(select(BridgeIntent.id).where(BridgeIntent.state.in_(("waiting", "sending"))).limit(1))
    why = ""
    if now - w["since"] > MAX_SECONDS:
        why = f"Asleep: on for {MAX_SECONDS // 3600} hours."
        _stop_waiting(db, "The bridge went to sleep before D&D Beyond had it.")  # listed to make by hand, never kept quietly
    elif not open_changes and (w.get("then_sleep") or now - w["last"] > IDLE_SECONDS):
        why = "Asleep: Game Mode switched off." if w.get("then_sleep") else f"Asleep: {IDLE_SECONDS // 60} minutes without play."
    if why:
        row.value = json.dumps({"on": False, "why": why, "slept_at": now})
        return {"awake": False, "why": why}
    return {"awake": True, "reason": w.get("reason", ""), "since": w["since"], "until": min(w["since"] + MAX_SECONDS, w["last"] + IDLE_SECONDS)}


def _stop_waiting(db: Session, why: str) -> None:
    for b in db.scalars(select(BridgeBatch).where(BridgeBatch.state.in_(("sending", "ready")))):
        b.state, b.error = "stopped", why
    for it in db.scalars(select(BridgeIntent).where(BridgeIntent.state.in_(("waiting", "sending")))):
        it.state, it.error = "not_yet", why


def wake(db: Session, reason: str) -> None:
    """Game Mode switched on, a change made in askdnd, or the check: awake now, and for IDLE_SECONDS after the last play."""
    row, w = _wake_row(db)
    now = time.time()
    since = w["since"] if w.get("on") and now - w["since"] <= MAX_SECONDS else now
    row.value = json.dumps({"on": True, "since": since, "last": now, "reason": reason})


def played(db: Session) -> None:
    """Something happened in the game (a change made or seen): stay awake."""
    row, w = _wake_row(db)
    if w.get("on"):
        w["last"] = time.time()
        row.value = json.dumps(w)


def sleep(db: Session, why: str) -> None:
    row, _ = _wake_row(db)
    row.value = json.dumps({"on": False, "why": why, "slept_at": time.time()})


# ------------------------------------------------------------------ the numbers askdnd follows


def numbers(character: Character) -> dict:
    """Hit points (as D&D Beyond keeps them: damage taken and temporary) and each item's count, exactly as D&D Beyond
    has them, from its saved copy (not askdnd's display summary, which shows a count of 0 as 1)."""
    summary = chars.character_summary(character)
    raw = character.snapshot.raw if character.snapshot else None
    if not summary or not raw:
        return {}
    inv = [i for i in raw.get("inventory") or [] if isinstance(i, dict) and i.get("id") is not None]
    return {"max": summary["hit_points"]["max"], "removed": raw.get("removedHitPoints") or 0, "temp": raw.get("temporaryHitPoints") or 0,
            "items": {i["id"]: i.get("quantity") or 0 for i in inv}, "names": {i["id"]: (i.get("definition") or {}).get("name", "Item") for i in inv}}


def fields(n: dict) -> dict:
    """The values askdnd writes, keyed as a batch's ops are: "hp" and "item:<id>"."""
    return {"hp": [n["removed"], n["temp"]], **{f"item:{i}": q for i, q in n["items"].items()}}


def plan(intents: list[dict], n: dict) -> tuple[dict, list[str], list[tuple[dict, str]]]:
    """The end state of these intents built on what D&D Beyond has now (`n`): the final value of each field they touch,
    one line per field to show, and any intent that can't happen any more (with why)."""
    removed, temp, items = n["removed"], n["temp"], dict(n["items"])
    impossible, touched = [], []
    for it in intents:
        d = it["data"]
        if it["kind"] == "drink":
            if items.get(d["item"], 0) < 1:
                impossible.append((it, f"No {d['name']} left on D&D Beyond."))
                continue
            items[d["item"]] -= 1
            removed = max(0, removed - d["heal"])
            touched += ["hp", f"item:{d['item']}"]
        elif it["kind"] == "hp":  # + heals, - damage; temporary hit points take damage first (2024 rules)
            if d["amount"] >= 0:
                removed = max(0, removed - d["amount"])
            else:
                soak = min(temp, -d["amount"])
                temp, removed = temp - soak, min(n["max"], removed + (-d["amount"] - soak))
            touched.append("hp")
        elif it["kind"] == "item":
            if items.get(d["item"]) is None or items[d["item"]] + d["delta"] < 0:
                impossible.append((it, f"D&D Beyond doesn't have enough {d['name']}."))
                continue
            items[d["item"]] += d["delta"]
            touched.append(f"item:{d['item']}")
    target, lines = {}, []
    for f in dict.fromkeys(touched):
        if f == "hp":
            target[f] = [removed, temp]
            lines.append(f"Hit points {n['max'] - removed}" + (f" + {temp} temporary" if temp else "")
                         + f" (D&D Beyond has {n['max'] - n['removed']})")
        else:
            i = int(f[5:])
            target[f] = items[i]
            lines.append(f"{n['names'].get(i, 'Item')} ×{items[i]} (D&D Beyond has ×{n['items'].get(i)})")
    return target, lines, impossible


def _ops(character: Character, target: dict, n: dict) -> list[dict]:
    did = int(character.ddb_id)
    out = []
    for f, value in target.items():
        if f == "hp":
            out.append({"field": f, "path": HP_PATH, "body": {"characterId": did, "removedHitPoints": value[0], "temporaryHitPoints": value[1]},
                        "from": {"removedHitPoints": n["removed"], "temporaryHitPoints": n["temp"]},
                        "to": {"removedHitPoints": value[0], "temporaryHitPoints": value[1]}})
        else:
            i = int(f[5:])
            out.append({"field": f, "path": ITEM_PATH, "body": {"characterId": did, "id": i, "quantity": value},
                        "from": {"item": i, "quantity": n["items"][i]}, "to": {"item": i, "quantity": value}})
    return out


# ------------------------------------------------------------------ the outbox


def add(db: Session, character: Character, kind: str, data: dict, label: str) -> int:
    wake(db, (_wake_row(db)[1].get("reason") if awake(db)["awake"] else "") or "change")  # making a change is playing
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
    target, _lines, impossible = plan(dicts, n)
    for d, why in impossible:  # (by identity: two drinks of the same potion are equal dicts)
        it = waiting[next(k for k, x in enumerate(dicts) if x is d)]
        it.state, it.error = "not_yet", why
    keep = [i for i in waiting if i.state == "waiting"]
    if not keep or not target:
        return None
    batch = BridgeBatch(character_id=character.id, intents=[i.id for i in keep], ops=_ops(character, target, n), before=fields(n),
                        target=target, state="sending", attempts=1, sent_at=now, next_at=0, check=keep[0].data.get("check", ""),
                        names={f: ("hit points" if f == "hp" else n["names"].get(int(f[5:]), "an item")) for f in target})
    db.add(batch)
    for i in keep:
        i.state = "sending"
    db.flush()
    return {"id": batch.id, "ops": batch.ops}


def _intents_of(db: Session, b: BridgeBatch) -> list[BridgeIntent]:
    return list(db.scalars(select(BridgeIntent).where(BridgeIntent.id.in_(b.intents)).order_by(BridgeIntent.id)))


def _settle(db: Session, b: BridgeBatch) -> None:
    played(db)
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
        now = fields(numbers(character))
        missing = [f for f, v in b.target.items() if now.get(f) != v]
        if not missing:
            break
    if not missing:
        _settle(db, b)
    elif any(now.get(f) != b.before.get(f) for f in missing):
        _stop(db, b, f"D&D Beyond's {_say(missing, b)} isn't what askdnd wrote or what it had before.")
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


def _stop(db: Session, b: BridgeBatch, why: str) -> None:
    b.state, b.error = "stopped", why[:400]
    for it in _intents_of(db, b):
        it.state, it.error = "not_yet", (why + " Nothing was written over.")[:400]
    _check_step(db, b, False, why)


def heard(db: Session, character: Character, saved: bool = True) -> None:
    """A read of the sheet, after the extension heard it save (`saved`) or on its every-30-seconds pull: it settles any
    batch D&D Beyond now holds the totals of (so a lost "done" from the extension still gets confirmed), and logs what
    D&D Beyond changed itself (not what askdnd is writing)."""
    if not awake(db)["awake"]:
        return  # asleep: no read of D&D Beyond (askdnd's own Game Mode refresh still runs as it always has)
    if saved:
        _health["heard_at"] = time.time()
    _lock(db, character.id)
    before = numbers(character)  # the last copy askdnd read
    chars.refresh(db, character)
    n = numbers(character)
    if not n:
        return
    now = fields(n)
    open_batches = list(db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id, BridgeBatch.state.in_(("sending", "ready")))))
    for b in open_batches:
        if all(now.get(f) == v for f, v in b.target.items()):
            _settle(db, b)
    recent = db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == character.id,
                                                  BridgeBatch.sent_at > time.time() - 60)).all()
    ours = {f for b in recent for f in b.target}  # what askdnd is writing (or just wrote) isn't "changed on D&D Beyond"
    if before:
        changed = []
        if before["removed"] != n["removed"] and "hp" not in ours:
            changed.append(f"hit points {before['max'] - before['removed']} → {n['max'] - n['removed']}")
        for i, q in n["items"].items():
            if before["items"].get(i) not in (None, q) and f"item:{i}" not in ours:
                changed.append(f"{n['names'].get(i, 'an item')} ×{before['items'][i]} → ×{q}")
        if changed:
            _log(db, character.id, f"{character.name} (on D&D Beyond): " + ", ".join(changed), "seen")
            played(db)


def retry(db: Session, intent_id: int) -> None:
    it = db.get(BridgeIntent, intent_id)
    if it and it.state == "not_yet":
        it.state, it.error = "waiting", ""


def dismiss(db: Session, intent_id: int) -> None:
    it = db.get(BridgeIntent, intent_id)
    if it and it.state in ("waiting", "not_yet"):
        it.state = "dismissed"


# ------------------------------------------------------------------ health


def round_trip(db: Session, character: Character) -> None:
    """The pre-game check on the test character: 1 hit point and one Candle out, then back, each confirmed by
    read-back. Queued like any change; the extension delivers it from the test character's open sheet. Putting them
    back depends only on the batch (its `check`), so a restart mid-check still puts Vi back."""
    n = numbers(character) or {}
    item = next((i for i, name in (n.get("names") or {}).items() if name == TEST_ITEM and n["items"][i] > 0), None)
    _health["round_trip"] = {"state": "running", "at": _now(), "error": ""}
    wake(db, "test")
    add(db, character, "hp", {"amount": -1, "check": "out"}, "Check: 1 hit point taken")
    if item:
        add(db, character, "item", {"item": item, "delta": -1, "name": TEST_ITEM, "check": "out"}, f"Check: one {TEST_ITEM} taken")


def _check_step(db: Session, b: BridgeBatch, ok: bool, why: str = "") -> None:
    if not b.check:
        return
    rt = _health.get("round_trip") or {"state": "running", "at": _now(), "error": ""}
    _health["round_trip"] = rt
    if not ok:
        rt.update(state="failed", error=why, done_at=_now())
        b.check = ""  # (nothing goes back on its own: the stopped change waits to be made by hand or undone)
        return
    if b.check == "out":
        for it in _intents_of(db, b):
            back = {"amount": -it.data["amount"]} if it.kind == "hp" else {"item": it.data["item"], "delta": -it.data["delta"], "name": it.data["name"]}
            add(db, db.get(Character, b.character_id), it.kind, {**back, "check": "back"}, it.label.replace("taken", "back"))
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


@router.post("/bridge/wake")
async def bridge_wake(request: Request, db: Session = Depends(get_db)):
    """Game Mode switched on (askdnd's page), or a person asking to test: awake now."""
    _signed_in(request, db)
    reason = (await request.json()).get("reason", "game")
    wake(db, "test" if reason == "test" else "game")
    db.commit()
    return _json(health(db))


@router.post("/bridge/sleep")
def bridge_sleep(request: Request, db: Session = Depends(get_db)):
    """Game Mode switched off: asleep now, unless a change is still waiting (it sleeps once that's settled)."""
    _signed_in(request, db)
    if db.scalar(select(BridgeIntent.id).where(BridgeIntent.state.in_(("waiting", "sending"))).limit(1)) is None:
        sleep(db, "Asleep: Game Mode switched off.")
    else:
        row, w = _wake_row(db)
        if w.get("on"):
            w["then_sleep"] = True  # sleeps as soon as the waiting change is settled
            row.value = json.dumps(w)
    db.commit()
    return _json(health(db))


@router.post("/bridge/check")
def bridge_check(request: Request, db: Session = Depends(get_db)):
    """Run the pre-game round trip on the test character (the extension delivers it from its open sheet)."""
    character, user = _by_ddb(db, request, TEST_DDB_ID)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the test character's player runs the check.")
    round_trip(db, character)
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
    return _json(state(db, character, user))


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
