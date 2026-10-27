"""The D&D Beyond bridge, a proof (Brett, 2026-10-27; docs/mockups/ddb-overlay.html, docs/plans/2026-10-27-data-strategy.md).

askdnd's browser extension (extension/askdnd-bridge/) runs in a person's own signed-in D&D Beyond tab. It tells askdnd
the moment the sheet saves a change, and makes askdnd's changes there, as that person, with the same requests the
sheet itself sends. The rule: **D&D Beyond confirms every change.** askdnd shows a number as changed only after it has
read the change back from D&D Beyond (characters.refresh); until then the change is "waiting", and if it can't be made
it's "not on D&D Beyond yet". Four states, everywhere: live, waiting, not_yet, seen (changed on D&D Beyond itself).

The proof covers one action, drinking a Potion of Healing (its count and hit points), for the character's own player.
It's local only (refused in production) and keeps its changes and log in this process's memory: a restart forgets
them, and a second copy of the app wouldn't see them. Built for real, both go in the database (play log, VTT 0.4).

askdnd decides the D&D Beyond requests (`ops`), and the extension makes only the two it knows (OPS), so a page can't
ask it to change anything else.
"""

import itertools
import threading
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, picks, table_rolls
from app import characters as chars
from app.auth import current_user
from app.db import get_db
from app.models import Character
from app.templating import templates

router = APIRouter()

# The D&D Beyond requests the extension may make (character-service.dndbeyond.com), and what each body holds. Learned
# from the sheet's own saves (2026-10-27): both send new totals, not +1/-1, so repeating one can't double it.
OPS = {
    "/character/v5/life/hp/damage-taken": ("characterId", "removedHitPoints", "temporaryHitPoints"),
    "/character/v5/inventory/item/quantity": ("characterId", "id", "quantity"),
}
HEALING = {"Potion of Healing": "2d4+2", "Potion of Greater Healing": "4d4+4", "Potion of Superior Healing": "8d4+8",
           "Potion of Supreme Healing": "10d4+20"}  # SRD 5.2.1
WAIT_SECONDS = 20  # a change D&D Beyond hasn't confirmed by then is "not on D&D Beyond yet"
MIN_REFRESH_SECONDS = 2  # the sheet saves in bursts; one read of D&D Beyond per burst

_lock = threading.Lock()
_ids = itertools.count(1)
_changes: dict[int, dict] = {}  # change id -> {character_id, state, label, expect, ops, at, error}
_logs: dict[int, list[dict]] = {}  # character id -> newest first: {text, state, at}
_seen: dict[int, dict] = {}  # character id -> the numbers last read from D&D Beyond
_refreshed: dict[int, float] = {}


def _local_only():
    if config.IS_PRODUCTION:
        raise HTTPException(404)


def _numbers(summary: dict | None) -> dict:
    """The numbers the proof follows: hit points and each item's count."""
    if not summary:
        return {}
    hp = summary["hit_points"]
    return {"hp": hp["current"], "max": hp["max"], "temp": hp["temp"], "removed": hp["damage"],
            "items": {it["key"]: it["quantity"] for it in summary["inventory"] if it["key"].startswith("item:")}}


def _log(character_id: int, text: str, state: str) -> None:
    _logs.setdefault(character_id, []).insert(0, {"text": text, "state": state, "at": datetime.now(UTC).isoformat()})
    del _logs[character_id][20:]


def _diff(name: str, before: dict, after: dict, summary: dict) -> list[str]:
    names = {it["key"]: it["name"] for it in summary["inventory"]}
    out = []
    if before.get("hp") != after.get("hp"):
        out.append(f"hit points {before.get('hp')} → {after.get('hp')}")
    for key, n in after.get("items", {}).items():
        if key in before.get("items", {}) and before["items"][key] != n:
            out.append(f"{names.get(key, 'an item')} ×{before['items'][key]} → ×{n}")
    return out


def reconcile(db: Session, character: Character) -> None:
    """Read the character from D&D Beyond, then settle every change that was waiting on it: confirmed when D&D Beyond
    now has what askdnd asked for, and anything else that changed there is "seen" (changed on D&D Beyond itself)."""
    chars.refresh(db, character)  # announces the character when it changed (app/realtime.py), so open pages update
    summary = chars.character_summary(character)
    now = _numbers(summary)
    with _lock:
        before = _seen.get(character.id)
        confirmed = False
        for ch in _changes.values():
            if ch["character_id"] == character.id and ch["state"] in ("waiting", "not_yet") and _matches(now, ch["expect"]):
                ch["state"] = "live"
                _log(character.id, ch["label"], "live")
                confirmed = True
        if before and not confirmed:
            changed = _diff(character.name, before, now, summary) if summary else []
            if changed:
                _log(character.id, f"{character.name} (on D&D Beyond): " + ", ".join(changed), "seen")
        _seen[character.id] = now


def _matches(now: dict, expect: dict) -> bool:
    return now.get("hp") == expect["hp"] and all(now.get("items", {}).get(k) == v for k, v in expect["items"].items())


def _expire() -> None:
    for ch in _changes.values():
        if ch["state"] == "waiting" and time.time() - ch["at"] > WAIT_SECONDS:
            ch["state"], ch["error"] = "not_yet", "D&D Beyond didn't confirm it in time."


def state(db: Session, character: Character, user: dict | None) -> dict:
    """What the panel and the page show: the numbers as D&D Beyond last had them, every change still open, the log."""
    summary = chars.character_summary(character)
    with _lock:
        _expire()
        if character.id not in _seen and summary:
            _seen[character.id] = _numbers(summary)
        open_changes = [{"id": i, **{k: c[k] for k in ("state", "label", "lines", "ops", "error")}}
                        for i, c in sorted(_changes.items(), reverse=True)
                        if c["character_id"] == character.id and c["state"] in ("waiting", "not_yet")]
        log = list(_logs.get(character.id, []))
    hp = (summary or {}).get("hit_points") or {}
    items = [{"id": int(it["key"].split(":")[1]), "key": it["key"], "name": it["name"], "quantity": it["quantity"],
              "heals": HEALING.get(it["name"], "")}
             for it in (summary or {}).get("inventory", []) if it["name"] in HEALING]
    snap = character.snapshot
    return {"character": {"id": character.id, "name": character.name, "ddb_id": character.ddb_id},
            "can_act": picks.can_edit(db, user, character),
            "hp": {"current": hp.get("current"), "max": hp.get("max"), "temp": hp.get("temp")},
            "items": items, "changes": open_changes, "log": log,
            "read_at": snap.fetched_at.isoformat() if snap and snap.fetched_at else None}


def drink(db: Session, character: Character, item_id: int, roll=None) -> dict:
    """Drink a healing potion: roll it, then ask D&D Beyond for one fewer and the hit points it restores. Nothing in
    askdnd changes until D&D Beyond confirms both (reconcile)."""
    summary = chars.character_summary(character)
    item = next((it for it in (summary or {}).get("inventory", []) if it["key"] == f"item:{item_id}"), None)
    if not item or item["name"] not in HEALING or item["quantity"] < 1:
        raise HTTPException(400, "That isn't a healing potion this character has.")
    hp = summary["hit_points"]
    rolled = table_rolls.roll_formula(HEALING[item["name"]], roll=roll)
    heal = rolled["total"]
    removed = max(0, hp["damage"] - heal)
    new_hp = hp["max"] - removed
    ddb_id = int(character.ddb_id)
    ops = [{"path": "/character/v5/inventory/item/quantity", "body": {"characterId": ddb_id, "id": item_id, "quantity": item["quantity"] - 1}},
           {"path": "/character/v5/life/hp/damage-taken", "body": {"characterId": ddb_id, "removedHitPoints": removed, "temporaryHitPoints": hp["temp"]}}]
    lines = [f"{item['name']} ×{item['quantity']} → ×{item['quantity'] - 1}",
             f"Hit points {hp['current']} → {new_hp} (rolled {heal}: {rolled['formula']})"]
    change = {"character_id": character.id, "state": "waiting", "ops": ops, "lines": lines, "at": time.time(), "error": "",
              "label": f"{character.name} drank a {item['name']}: hit points {hp['current']} → {new_hp}, ×{item['quantity']} → ×{item['quantity'] - 1}",
              "expect": {"hp": new_hp, "items": {item["key"]: item["quantity"] - 1}}}
    with _lock:
        cid = next(_ids)
        _changes[cid] = change
    return {"id": cid, "ops": ops, "lines": lines}


# ------------------------------------------------------------------ routes


def _mine(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    _local_only()
    user = current_user(request)
    character = db.get(Character, character_id)
    if not user or not character or not picks.can_view(db, user, character):
        raise HTTPException(404)
    return character, user


def _json(body: dict, status: int = 200) -> JSONResponse:
    # The extension's panel on dndbeyond.com reads these through its own background page, so no CORS is opened
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@router.get("/bridge/state/{character_id:int}")
def bridge_state(character_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    return _json(state(db, character, user))


@router.get("/bridge/by-ddb/{ddb_id}")
def bridge_by_ddb(ddb_id: str, request: Request, db: Session = Depends(get_db)):
    """The extension knows a sheet by its D&D Beyond number; askdnd says which character that is here."""
    _local_only()
    user = current_user(request)
    if not user:
        return _json({"error": "Sign in to askdnd in this browser."}, 401)
    character = db.scalar(select(Character).where(Character.ddb_id == ddb_id, Character.copy_of_id.is_(None)))
    if not character or not picks.can_view(db, user, character):
        return _json({"error": "askdnd doesn't know this character."}, 404)
    return _json(state(db, character, user))


@router.post("/bridge/changed/{character_id:int}")
def bridge_changed(character_id: int, request: Request, db: Session = Depends(get_db)):
    """The extension saw the sheet save a change: read the character from D&D Beyond and settle what was waiting."""
    character, user = _mine(db, request, character_id)
    last = _refreshed.get(character.id, 0)
    if time.time() - last >= MIN_REFRESH_SECONDS:
        _refreshed[character.id] = time.time()
        reconcile(db, character)
        db.commit()
    return _json(state(db, character, user))


@router.post("/bridge/drink/{character_id:int}/{item_id:int}")
def bridge_drink(character_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    character, user = _mine(db, request, character_id)
    if not picks.can_edit(db, user, character):
        raise HTTPException(403, "Only the character's player drinks their potions.")
    return _json(drink(db, character, item_id))


@router.post("/bridge/result/{change_id:int}")
async def bridge_result(change_id: int, request: Request, db: Session = Depends(get_db)):
    """The extension's answer: it made the requests (askdnd then reads them back), or it couldn't and why."""
    _local_only()
    body = await request.json()
    with _lock:
        ch = _changes.get(change_id)
        if not ch:
            raise HTTPException(404)
        if not body.get("ok"):
            ch["state"], ch["error"] = "not_yet", str(body.get("error") or "The change couldn't be made.")[:200]
    character, user = _mine(db, request, ch["character_id"])
    if body.get("ok"):
        _refreshed[character.id] = time.time()
        reconcile(db, character)
        db.commit()
    return _json(state(db, character, user))


@router.post("/bridge/dismiss/{change_id:int}")
def bridge_dismiss(change_id: int, request: Request, db: Session = Depends(get_db)):
    """Undo: drop a change that never reached D&D Beyond (nothing to put back: askdnd never applied it)."""
    _local_only()
    with _lock:
        ch = _changes.get(change_id)
        if not ch or ch["state"] == "live":
            raise HTTPException(404)
        ch["state"] = "dismissed"
    character, user = _mine(db, request, ch["character_id"])
    return _json(state(db, character, user))


@router.get("/characters/{character_id:int}/bridge")
def bridge_page(character_id: int, request: Request, db: Session = Depends(get_db)):
    """askdnd's own tab for the proof: the same panel as beside the D&D Beyond sheet."""
    character, user = _mine(db, request, character_id)
    return templates.TemplateResponse(request, "bridge.html", {"c": character, "state": state(db, character, user)})
