"""Coins: where a character keeps them, and every change to them in one place (feedback 51–53, Nov 7;
docs/mockups/coins/, Brett chose A, Spend · Gain · Move, and making change).

A character's coins are in **places**: carried ("me") and each of its containers (a Bag of Holding, a Backpack), as D&D
Beyond keeps them. A change is a set of **deltas** by bridge field ("coin:gp" carried, "bagcoin:<bag>:gp" in a bag,
app/ddb_fields.py), made as one bridge change of kind "coins": the planner makes every place's part or none of them, so
a move never takes coins out of one place without putting them in the other. Spending a coin a place hasn't got makes
change from its other coins, as paying in the item browser does (`pay_from`: largest coins first, change in gold,
silver and copper).
"""

import json
import re

from sqlalchemy.orm import Session

from app import ddb_bridge
from app.models import Character

COINS = ("cp", "sp", "ep", "gp", "pp")  # (D&D Beyond's order; people read them largest first, LARGEST)
LARGEST = ("pp", "gp", "ep", "sp", "cp")
CP = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}
MOST = 100000  # coins in one change, as the window allows
CARRIED = "me"


def money(cp: int) -> str:
    """Copper pieces in coins as the books write them: 150 → "1 gp 5 sp"."""
    out = []
    for coin in ("gp", "sp", "cp"):
        n, cp = divmod(cp, CP[coin])
        if n:
            out.append(f"{n:,} {coin}")
    return " ".join(out) or "0 gp"


def words(coins: dict) -> str:
    """"654 gp, 68 sp, 92 cp": some coins in words, largest first (the templates' `coins_text`)."""
    return ", ".join(f"{coins[c]:,} {c}" for c in LARGEST if coins.get(c)) or "none"


def parse_money(text: str) -> int | None:
    """What a player typed to pay, in copper: "2 gp 1 sp", "21 sp", "2.5 gp", "3" (gold), "" (nothing). None: not money."""
    text = (text or "").strip().lower().replace(",", "")
    if not text:
        return 0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return round(float(text) * 100)
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(pp|gp|ep|sp|cp)", text)
    if not parts or re.sub(r"(\d+(?:\.\d+)?)\s*(pp|gp|ep|sp|cp)", "", text).strip():
        return None
    return round(sum(float(n) * CP[c] for n, c in parts))


def worth(coins: dict) -> int:
    """What some coins are worth, in copper."""
    return sum(int(coins.get(c) or 0) * CP[c] for c in COINS)


def pay_from(purse: dict, cp: int) -> dict | None:
    """The purse after paying `cp` copper, or None when it holds too little. Counted out as you would, the largest
    coins that fit first; when what's left is less than any coin still there, the smallest of them is broken and the
    change comes back in gold, silver and copper."""
    have = {c: int(purse.get(c) or 0) for c in COINS}
    if worth(have) < cp:
        return None
    left = cp
    for c in LARGEST:
        use = min(have[c], left // CP[c])
        have[c] -= use
        left -= use * CP[c]
    if left:  # (every coin left is worth more than what's still owed)
        c = next(c for c in reversed(LARGEST) if have[c])
        have[c] -= 1
        change = CP[c] - left
        for k in ("gp", "sp", "cp"):
            n, change = divmod(change, CP[k])
            have[k] += n
    return have


def places(sheet: dict) -> list[dict]:
    """Carried, then each of the character's containers, with the coins in each (every coin, 0 where there are none):
    [{"key": "me" or the bag's inventory id, "name", "coins", "has": any coins at all}]."""
    held = {b["id"]: b.get("coins") or {} for b in sheet.get("bag_coins") or []}
    out = [{"key": CARRIED, "name": "Carried", "coins": dict(sheet.get("currency") or {})}]
    out += [{"key": b["key"][5:], "name": b["name"], "coins": dict(held.get(b["key"][5:], {}))}
            for b in sheet.get("inventory") or [] if b.get("bag") and b.get("key", "").startswith("item:")]
    for p in out:
        p["coins"] = {c: int(p["coins"].get(c) or 0) for c in COINS}
        p["has"] = any(p["coins"].values())
    return out


def place(sheet: dict, key: str) -> dict | None:
    return next((p for p in places(sheet) if p["key"] == str(key)), None)


def field(key: str, coin: str) -> str:
    return f"coin:{coin}" if key == CARRIED else f"bagcoin:{key}:{coin}"


def spend(where: dict, coin: str, n: int) -> dict | None:
    """The deltas that spend `n` of `coin` from a place: those coins if it has them, else change made from its others
    (None: it hasn't that much in all)."""
    if where["coins"][coin] >= n:
        return {field(where["key"], coin): -n}
    after = pay_from(where["coins"], n * CP[coin])
    if after is None:
        return None
    return {field(where["key"], c): after[c] - where["coins"][c] for c in COINS if after[c] != where["coins"][c]}


def made_change(deltas: dict, coin: str) -> str:
    """": paid 1 gp, 5 sp back": what spending took and gave back when it made change ("" when it paid in `coin` itself)."""
    paid = {f.rpartition(":")[2]: -d for f, d in deltas.items() if d < 0}
    back = {f.rpartition(":")[2]: d for f, d in deltas.items() if d > 0}
    if not back and set(paid) == {coin}:
        return ""
    return f": paid {words(paid)}" + (f", {words(back)} back" if back else "")


def undo_of(deltas: dict) -> dict:
    return {"to": "undo", "deltas": json.dumps({f: -d for f, d in deltas.items()})}


def checked(sheet: dict, raw: str) -> dict | None:
    """Deltas sent back (an Undo), checked: only this character's places and coins, whole numbers in range."""
    try:
        deltas = json.loads(raw)
    except (TypeError, ValueError):
        return None
    keys = {p["key"] for p in places(sheet)}
    ok = isinstance(deltas, dict) and deltas and all(
        isinstance(d, int) and not isinstance(d, bool) and 0 < abs(d) <= MOST * 10
        and ((f.startswith("coin:") and f[5:] in COINS)
             or (f.startswith("bagcoin:") and f.count(":") == 2 and f.split(":")[1] in keys - {CARRIED} and f.split(":")[2] in COINS))
        for f, d in deltas.items())
    return deltas if ok else None


def make(db: Session, ch: Character, deltas: dict, said: str) -> int:
    """One change for D&D Beyond: every place's coins or none of them (ddb_bridge's planner, kind "coins")."""
    return ddb_bridge.add(db, ch, "coins", {"deltas": deltas, "said": said}, f"{ch.name}: {said}")
