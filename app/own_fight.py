"""askdnd runs the fight (VTT slice 2, docs/plans/2026-11-02-vtt-build-plan.md; mockup docs/mockups/askdnd-runs-the-fight/).

On askdnd's table the DM starts a fight, adds creatures from the campaign's books or the SRD (hidden ones only the DM
sees), players roll their own Initiative into it (from Battle, as with Initiative from askdnd), and the DM presses
Next turn. The fight and its fighters are rows of their own (`Fight`, `Fighter`), changed one step at a time under the
campaign's fight lock (fight.lock), each step kept with the fight as it was (`FightStep`) for the DM's Undo.

What every page shows is published to `Campaign.fight` in the shape of a fight heard from D&D Beyond's VTT (fight.take),
marked `own`: the band, Party's Rows, reminders, conditions that end and Concentration follow askdnd's turns unchanged,
and while it runs what D&D Beyond's VTT reports is set aside. A creature's numbers ride along for the DM only: each
person's copy is cut by fight.shown, so a player's page never receives what the DM's battle settings keep from them
(by default an enemy's Hit Points are Healthy, Bloodied or Down)."""

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fight as heard_fight
from app import rules_data
from app.models import Campaign, Character, Fight, Fighter, FightStep

# The DM's battle settings (Campaign.battle; mockup board 3): what players see of an enemy's Hit Points ("words":
# Healthy, Bloodied or Down; "numbers"; "nothing"), whether a group added together rolls one Initiative, whether new
# creatures start hidden
SETTINGS = {"hp": "words", "group": True, "hidden": False}
HP_SHOWN = ("words", "numbers", "nothing")
MAX_ADD = 20  # (creatures of one kind added at once)
KEY = "askdnd:"  # a fighter's key in the published fight: "askdnd:<Fighter.id>"


def settings(campaign: Campaign) -> dict:
    return {**SETTINGS, **{k: v for k, v in (campaign.battle or {}).items() if k in SETTINGS}}


def current(db: Session, campaign: Campaign) -> Fight | None:
    """The campaign's askdnd fight that hasn't ended, or None."""
    return db.scalar(select(Fight).where(Fight.campaign_id == campaign.id, Fight.state != "ended").order_by(Fight.id.desc()).limit(1))


def health(hp: int, hp_max: int) -> str:
    """What players see of a creature's Hit Points by default: Healthy, Bloodied (half or less) or Down."""
    return "Down" if hp <= 0 else "Bloodied" if hp_max and hp * 2 <= hp_max else "Healthy"


# ------------------------------------------------------------------ one step at a time, with Undo

def _snapshot(f: Fight) -> dict:
    cols = ("character_id", "name", "monster", "group", "initiative", "bonus", "hidden", "hp", "hp_max", "temp", "ac", "conditions")
    return {"state": f.state, "round": f.round, "turn": f.turn,
            "fighters": [{"id": x.id, **{c: getattr(x, c) for c in cols}} for x in f.fighters]}


def step(db: Session, f: Fight, what: str) -> None:
    """Before a change: the fight as it is, kept for Undo."""
    db.add(FightStep(fight_id=f.id, what=what[:120], before=_snapshot(f)))


def undo(db: Session, campaign: Campaign) -> str | None:
    """The DM's Undo: the fight as it was before its last step. What was undone, or None."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    last = db.scalar(select(FightStep).where(FightStep.fight_id == f.id).order_by(FightStep.id.desc()).limit(1)) if f else None
    if last is None:
        return None
    was = last.before
    f.state, f.round, f.turn = was["state"], was["round"], was["turn"]
    keep = {x["id"]: x for x in was["fighters"]}
    for x in list(f.fighters):
        if x.id not in keep:
            f.fighters.remove(x)
    have = {x.id for x in f.fighters}
    for fid, x in keep.items():
        row = db.get(Fighter, fid) if fid in have else None
        if row is None:
            row = Fighter(fight=f)
            db.add(row)
        for k, v in x.items():
            if k != "id":
                setattr(row, k, v)
    db.delete(last)
    db.flush()
    publish(db, campaign, f)
    return last.what


# ------------------------------------------------------------------ the order

def order(f: Fight) -> list[Fighter]:
    """Highest Initiative first; a tie goes to the higher bonus (then who was added first); no Initiative yet: last."""
    return sorted(f.fighters, key=lambda x: (x.initiative is None, -(x.initiative or 0), -x.bonus, x.id))


def _bonus(text) -> int:
    try:
        return int(str(text or "0").replace("−", "-").replace("+", ""))
    except ValueError:
        return 0


def start(db: Session, campaign: Campaign) -> Fight:
    """A new fight, waiting for Initiative, with the party in it (each character at the table)."""
    from app import characters as chars

    heard_fight.lock(db, campaign)
    if (f := current(db, campaign)) is not None:
        return f
    f = Fight(campaign_id=campaign.id, state="waiting", round=0)
    db.add(f)
    for ch in chars.campaign_characters(db, campaign.id):
        if ch.copy_of_id is None or campaign.is_test:
            sheet = chars.character_summary(ch) or {}
            db.add(Fighter(fight=f, character_id=ch.id, name=ch.name[:80], bonus=_bonus(sheet.get("initiative"))))
    db.flush()
    publish(db, campaign, f)
    return f


def _roll(bonus: int) -> int:
    from app.table_rolls import die

    return die(20) + bonus


def add(db: Session, campaign: Campaign, monster: str, count: int = 1, hidden: bool | None = None,
        init: str | int | None = None, user_id: int | None = None) -> list[Fighter]:
    """Creatures of one kind from the campaign's books or the SRD, named "Goblin Warrior 1" on; their Initiative rolled
    once for the group or each its own (the DM's battle settings, or `init`: "group", "each" or a number). Their rolls go
    to Table rolls for the DM only."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    m = rules_data.find("monster", monster, db, campaign.id)
    if f is None or m is None or not 1 <= count <= MAX_ADD:
        raise ValueError("That creature isn't in the campaign's books or the SRD.")
    s = settings(campaign)
    step(db, f, f"+ Add {count} {m['name']}")
    bonus = _bonus(m.get("initiative")) if m.get("initiative") is not None else math.floor(((m.get("abilities") or {}).get("dex", 10) - 10) / 2)
    taken = {x.name for x in f.fighters}
    n, made = 1, []
    group = f"g{len({x.group for x in f.fighters if x.group}) + 1}"
    mode = init if init in ("group", "each") else ("group" if s["group"] else "each")
    shared = int(init) if isinstance(init, int) or (isinstance(init, str) and init.lstrip("-").isdigit()) else None
    once = shared if shared is not None else (_roll(bonus) if mode == "group" else None)
    for _ in range(count):
        while f"{m['name']} {n}" in taken:
            n += 1
        name = f"{m['name']} {n}" if count > 1 or any(x.monster == m["key"] for x in f.fighters) else m["name"]
        taken.add(name)
        initiative = once if once is not None else _roll(bonus)
        x = Fighter(fight=f, name=name[:80], monster=m["key"], group=group if count > 1 else "", initiative=initiative, bonus=bonus,
                    hidden=s["hidden"] if hidden is None else bool(hidden), hp=int(m.get("hp") or 0), hp_max=int(m.get("hp") or 0),
                    ac=int(m.get("ac") or 0))
        db.add(x)
        made.append(x)
    db.flush()
    _initiative_rolls(db, campaign, made, user_id, shared is None)
    publish(db, campaign, f)
    return made


def _initiative_rolls(db: Session, campaign: Campaign, made: list[Fighter], user_id: int | None, rolled: bool) -> None:
    """The creatures' Initiative in Table rolls, only for the DM (one row for a group that rolled once)."""
    from app.models import TableRoll

    if not rolled or user_id is None:
        return
    seen = set()
    for x in made:
        if x.group and x.group in seen:
            continue
        seen.add(x.group)
        die = int(x.initiative) - x.bonus
        who = x.name if not x.group else f"{x.name.rsplit(' ', 1)[0]} ×{sum(1 for y in made if y.group == x.group)}"
        db.add(TableRoll(campaign_id=campaign.id, character_id=None, user_id=user_id, label="Initiative", kind="check", mode="normal",
                         visibility="dm", damage="", spec=None, extras=[], who=who[:80], parts=[], dice=[die], kept=die,
                         modifier=x.bonus, total=int(x.initiative), formula=f"d20{x.bonus:+d}"))


def set_initiative(db: Session, campaign: Campaign, fighter_id: int, value: float, what: str = "") -> Fighter:
    """A fighter's Initiative: a player's roll from Battle, or the DM typing one."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    x = db.get(Fighter, fighter_id)
    if f is None or x is None or x.fight_id != f.id:
        raise ValueError("They aren't in this fight.")
    step(db, f, what or f"{x.name}: Initiative {value:g}")
    x.initiative = float(value)
    db.flush()
    publish(db, campaign, f)
    return x


def rolled(db: Session, campaign: Campaign, ch: Character, total) -> bool:
    """A character's Initiative rolled in askdnd (app/table_rolls.py): its number in askdnd's fight. True when taken."""
    f = current(db, campaign)
    x = next((y for y in f.fighters if y.character_id == ch.id), None) if f else None
    if x is None:
        return False
    set_initiative(db, campaign, x.id, float(total), f"{x.name} rolled Initiative: {total}")
    return True


def begin(db: Session, campaign: Campaign) -> Fight:
    """Round 1: the first in the order has the turn."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    if f is None or not f.fighters:
        raise ValueError("There's no fight to begin.")
    step(db, f, "Round 1")
    f.state, f.round, f.turn = "running", 1, order(f)[0].id
    db.flush()
    publish(db, campaign, f)
    return f


def next_turn(db: Session, campaign: Campaign) -> Fight:
    """The next in the order has the turn; after the last, the next round begins."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    if f is None or f.state != "running":
        raise ValueError("The fight hasn't begun.")
    ranked = order(f)
    i = next((n for n, x in enumerate(ranked) if x.id == f.turn), -1)
    step(db, f, "Next turn")
    if i + 1 >= len(ranked):
        f.round, f.turn = f.round + 1, ranked[0].id
    else:
        f.turn = ranked[i + 1].id
    db.flush()
    publish(db, campaign, f)
    return f


def end(db: Session, campaign: Campaign) -> None:
    """The fight is over: every page's band goes."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    if f is None:
        return
    f.state = "ended"
    campaign.fight, campaign.fight_at = None, None
    db.flush()


def change_hp(db: Session, campaign: Campaign, fighter_id: int, amount: int) -> Fighter:
    """Damage (negative) or healing for a creature: Temporary Hit Points take damage first; 0 to its maximum."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    x = db.get(Fighter, fighter_id)
    if f is None or x is None or x.fight_id != f.id or x.character_id:
        raise ValueError("Only a creature's Hit Points are kept in the fight (a character's are its sheet's).")
    step(db, f, f"{x.name}: {'took' if amount < 0 else 'regained'} {abs(amount)}")
    if amount < 0:
        soak = min(x.temp, -amount)
        x.temp, x.hp = x.temp - soak, max(0, x.hp - (-amount - soak))
    else:
        x.hp = min(x.hp_max, x.hp + amount)
    db.flush()
    publish(db, campaign, f)
    return x


def show(db: Session, campaign: Campaign, fighter_id: int, hidden: bool) -> Fighter:
    """A hidden creature shown to the players (or hidden again)."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    x = db.get(Fighter, fighter_id)
    if f is None or x is None or x.fight_id != f.id:
        raise ValueError("They aren't in this fight.")
    step(db, f, f"{x.name}: {'hidden' if hidden else 'shown'}")
    x.hidden = bool(hidden)
    db.flush()
    publish(db, campaign, f)
    return x


def remove(db: Session, campaign: Campaign, fighter_id: int) -> None:
    """Out of the fight (fled, or added by mistake); its turn passes to the next."""
    heard_fight.lock(db, campaign)
    f = current(db, campaign)
    x = db.get(Fighter, fighter_id)
    if f is None or x is None or x.fight_id != f.id:
        raise ValueError("They aren't in this fight.")
    step(db, f, f"{x.name}: out of the fight")
    if f.turn == x.id:
        ranked = order(f)
        i = next(n for n, y in enumerate(ranked) if y.id == x.id)
        rest = ranked[i + 1:] + ranked[:i]
        f.turn = rest[0].id if rest else None
    f.fighters.remove(x)
    db.flush()
    publish(db, campaign, f)


# ------------------------------------------------------------------ what every page shows

def publish(db: Session, campaign: Campaign, f: Fight) -> None:
    """The fight as pages read it (Campaign.fight, the shape fight.heard keeps), through fight.take: turns that begin
    make their reminders and count conditions and Concentration, as D&D Beyond's VTT's do."""
    pics = rules_data.pictures()
    ranked = order(f)
    entries = []
    for x in ranked:
        entries.append({"key": f"{KEY}{x.id}", "name": x.name, "kind": "character" if x.character_id else "monster", "monster": None,
                        "character": x.character_id, "initiative": x.initiative, "hidden": x.hidden,
                        "active": f.state == "running" and x.id == f.turn,
                        "image": (pics.get(x.monster) or {}).get("image") if x.monster else None, "group": None, "gkey": None,
                        **({"own": {"hp": x.hp, "hp_max": x.hp_max, "temp": x.temp, "ac": x.ac, "monster": x.monster}} if not x.character_id else {})})
    turn = next((n + 1 for n, x in enumerate(ranked) if x.id == f.turn), 0)
    now = {"round": f.round, "turn": turn, "order": entries, "own": True, "battle": settings(campaign)}
    if f.state == "waiting":
        now["waiting"] = True
    heard_fight.take(db, campaign, now)


def cut(entry: dict, hp_shown: str) -> dict:
    """A creature's entry as a player receives it: its numbers kept from them as the DM's settings say."""
    own = entry.get("own")
    if not own:
        return entry
    out = {k: v for k, v in entry.items() if k != "own"}
    if hp_shown == "numbers":
        out["health"] = f"{own['hp']} / {own['hp_max']}"
    elif hp_shown == "words":
        out["health"] = health(own["hp"], own["hp_max"])
    return out
