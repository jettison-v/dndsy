"""The fight, as heard from D&D Beyond's VTT (Brett, 2026-10-29: docs/mockups/turn-conditions.html; DECISIONS).

The table runs its fights in D&D Beyond's VTT, where the DM presses Next. askdnd only listens: the extension, on any
open VTT page (extension/askdnd-bridge/vtt-page.js; the DM's at least), passes on the order, the round and whose turn
it is whenever they change (`POST /bridge/fight/<game>`, app/ddb_bridge.py). It's kept on the campaign
(`Campaign.fight`) and every page there hears it (realtime.CAMPAIGN_SEES), where the **fight band** above the name on
every character page and on Party shows it (`_fight_band.html`).

- **Which campaign**: the one whose D&D Beyond campaign is that game (Manage › Settings), else the ones whose own
  characters' sheets are in it (never a test copy's: it shares its original's game).
- **Who sees what**: everyone at the table sees the order, as D&D Beyond's VTT shows it; a token the DM hid is the
  DM's only.
- **When it's gone**: the fight ends when the VTT says so, and a fight not heard for `STALE` isn't shown (a VTT closed
  mid-fight leaves its last word behind).
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.models import Campaign, CampaignCharacter, Character

STALE = timedelta(hours=3)


def campaigns_for(db: Session, game_id: str) -> list[Campaign]:
    """The askdnd campaigns a D&D Beyond game is."""
    named = list(db.scalars(select(Campaign).where(Campaign.ddb_campaign_id == str(game_id))))
    if named:
        return named
    ids = db.scalars(select(CampaignCharacter.campaign_id).join(Character, Character.id == CampaignCharacter.character_id)
                     .where(Character.ddb_campaign_id == str(game_id), Character.copy_of_id.is_(None),
                            CampaignCharacter.left_on.is_(None)).distinct())
    return [db.get(Campaign, i) for i in ids]


def games_for(db: Session, user: dict, may) -> list[str]:
    """The D&D Beyond games askdnd follows for this person (`may(campaign)`: at that table, with the bridge on), so the
    extension tells askdnd about those only and nothing about any other game they open."""
    games: set[str] = set()
    for campaign in db.scalars(select(Campaign)):
        if not may(campaign):
            continue
        if campaign.ddb_campaign_id:
            games.add(campaign.ddb_campaign_id)
            continue
        games |= set(db.scalars(select(Character.ddb_campaign_id).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                                .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None),
                                       Character.copy_of_id.is_(None), Character.ddb_campaign_id.is_not(None))))
    return sorted(games)


def _picture(url) -> str | None:
    """A token's picture as the VTT draws it, kept only when it's D&D Beyond's own (an image askdnd's pages load)."""
    if not isinstance(url, str) or len(url) > 1000:
        return None
    u = urlparse(url)
    return url if u.scheme == "https" and (u.hostname or "").endswith(".dndbeyond.com") else None


def _clean(heard: dict | None, characters: dict[str, int]) -> dict | None:
    """What the extension heard, kept as askdnd shows it: each entry's name, kind, askdnd character (by its D&D Beyond
    id, in this campaign), initiative, hidden and whose turn; the round and the turn."""
    if not heard or not isinstance(heard.get("order"), list):
        return None
    order = []
    for x in heard["order"][:60]:
        if not isinstance(x, dict):
            continue
        ddb_id = str(x.get("ddb_id") or "") or None
        init = x.get("initiative")
        monster = str(x.get("monster_id") or "")
        order.append({"key": str(x.get("key") or "")[:80], "name": str(x.get("name") or "?")[:80],
                      "kind": x.get("kind") if x.get("kind") in ("character", "companion") else "monster",
                      "monster": monster if monster.isdigit() else None,
                      "character": characters.get(ddb_id) if ddb_id else None,
                      "initiative": init if isinstance(init, (int, float)) else None,
                      "hidden": bool(x.get("hidden")), "active": bool(x.get("active")), "image": _picture(x.get("image"))})
    return {"round": _int(heard.get("round")), "turn": _int(heard.get("turn")), "order": order}


def _int(v) -> int:
    """A round or turn number as the extension says it (1 when it says something else)."""
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return 1


def heard(db: Session, campaign: Campaign, fight: dict | None) -> bool:
    """The VTT's fight now (None: no fight). True when it changed."""
    characters = {c.ddb_id: c.id for c in db.scalars(
        select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
        .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None), Character.ddb_id.is_not(None)))}
    now, prev = _clean(fight, characters), campaign.fight
    fresh = campaign.fight_at is None or datetime.now(UTC) - campaign.fight_at > timedelta(minutes=10)
    if _order(now) == _order(prev) and not fresh:
        return False
    if now is not None:  # (its reminders carry on through the fight)
        now["reminders"], now["seq"] = list((prev or {}).get("reminders") or []), (prev or {}).get("seq", 0)
        ended, began = turn_begun(prev, now)
        if began:
            follow(db, campaign, ended, began, now)
    campaign.fight, campaign.fight_at = now, datetime.now(UTC)
    return True


def turn_begun(prev: dict | None, now: dict) -> tuple[str | None, str | None]:
    """(ended, began): whose turn ended and whose began, the first time this fight reaches that turn; else (None, None).
    Every open VTT page tells askdnd each change (the DM's and each player's), and their word can arrive late or out of
    order, and the DM can press Previous and Next again (review, 2026-10-29): so each turn (its round and whose it is)
    counts once in a fight, remembered in `now` ("done", and "last": whose turn began last)."""
    kept = prev if prev and prev.get("order") else None  # (a fight that ended: the next one counts afresh)
    if kept is not None and "done" not in kept:  # (a fight heard before turns were remembered)
        last = active_key(kept)
        kept = {**kept, "done": [f"{kept['round']}:{last}"] if last else [], "last": last}
    done, last = list((kept or {}).get("done") or []), (kept or {}).get("last")
    began = active_key(now)
    mark = f"{now['round']}:{began}" if began else None
    now["done"], now["last"] = done, last
    if not mark or mark in done:
        return None, None
    now["done"], now["last"] = (done + [mark])[-300:], began
    return (last if last != began else None), began


def _order(f: dict | None):
    return None if f is None else (f.get("round"), f.get("turn"), f.get("order"))


def active_key(f: dict | None) -> str | None:
    """Whose turn it is in a fight: their key."""
    return next((x["key"] for x in f["order"] if x.get("active")), None) if f else None


def remind(f: dict, character: Character, kind: str, name: str, text: str, **more) -> None:
    # Ids only grow, also from one fight to the next (each browser shows a reminder once: those above the last it saw)
    f["seq"] = max(f.get("seq", 0) + 1, int(time.time() * 1000))
    f["reminders"] = (f.get("reminders") or [])[-19:] + [{"id": f["seq"], "at": datetime.now(UTC).isoformat(), "character": character.id,
                                                           "who": character.name, "kind": kind, "name": name, "text": text, **more}]


def _save_label(character: Character, ability: str) -> str:
    from app import characters as chars

    saves = (chars.character_summary(character) or {}).get("saves") or []
    return next((s.get("label", "") for s in saves if s.get("short") == ability), "")


def follow(db: Session, campaign: Campaign, ended: str | None, began: str | None, now: dict) -> None:
    """A turn ended or began (app/conditions.py, how long it lasts): each condition timed by it moves on; one that ran
    out is marked due, and its player and the DM are reminded (nothing ends by itself: Brett, 2026-10-29); a save at
    the end of someone's turn is a reminder as that turn begins, to roll it at its end; a dying character's turn starts
    with a reminder to roll its death save; Concentration counts its rounds on the caster's own turns."""
    if not ended and not began:
        return
    from app import characters as chars  # (they read the fight too)
    from app import ddb_bridge, death_saves

    keys = {x["character"]: x["key"] for x in now["order"] if x.get("character")}
    members = db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                         .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None)))
    for ch in members:
        mine = keys.get(ch.id)
        if ch.conditions and any(c.get("lasts") for c in ch.conditions):
            out = []
            for c in ch.conditions:
                c, la = dict(c), c.get("lasts") or {}
                if la and not c.get("due"):
                    of = mine if (la.get("of") or {}).get("self") else (la.get("of") or {}).get("key")
                    kind = la.get("kind")
                    if kind == "endnext":
                        if ended and ended == of and c.get("armed"):
                            c["due"] = True
                        if began and began == of:
                            c["armed"] = True
                    elif kind == "startnext" and began and began == of:
                        c["due"] = True
                    elif kind == "rounds" and began:
                        if not c.get("began"):
                            c["began"], c["left"] = began, la["n"]  # (begun outside a heard fight: counted from now)
                        elif began == c["began"]:
                            c["left"] = c.get("left", la["n"]) - 1
                            c["due"] = c["left"] <= 0
                    elif kind == "save" and began and began == of:  # rolled at its end, said as it begins (Brett, 2026-10-29)
                        remind(now, ch, "save", c["name"], f"{la['ability']} save, DC {la['dc']}, at the end of this turn, to end {c['name']}",
                                ability=la["ability"], dc=la["dc"], mod=_save_label(ch, la["ability"]))
                    if c.get("due"):
                        remind(now, ch, "ends", c["name"], f"{c['name']} ends now" + (f": its {la['n']} rounds are up" if kind == "rounds" else ""))
                out.append(c)
            ch.conditions = out
        if mine and began == mine:  # dying: a death save starts the turn (app/death_saves.py)
            st = death_saves.state(ddb_bridge.as_shown(db, ch, chars.character_summary(ch)))
            if death_saves.rolling(st):
                remind(now, ch, "death", "Death save", f"roll your death save ({st['success']} ✓ · {st['fail']} ✗)")
        conc = dict(ch.concentration or {})
        if conc.get("rounds") and mine and began == mine and not conc.get("due"):
            conc["round"] = int(conc.get("round") or 1) + 1
            if conc["round"] > conc["rounds"]:
                conc["round"], conc["due"] = conc["rounds"], True
                remind(now, ch, "conc", "Concentration", f"{conc.get('spell') or 'Concentration'}: its time is up")
            ch.concentration = conc


def shown(campaign: Campaign | None, dm: bool, mine: set[int] = frozenset()) -> dict | None:
    """The fight as this person sees it, or None (no fight, or not heard for STALE): {"round", "turn", "order",
    "now" (whose turn: the entry), "next" (the entry after it), "yours" (it's one of `mine`'s turn), "next_yours",
    "reminders" (theirs: each says "mine" when it's one of their characters')}."""
    if campaign is None or not campaign.fight or not campaign.fight_at or datetime.now(UTC) - campaign.fight_at > STALE:
        return None
    f = campaign.fight
    order = [x for x in f["order"] if dm or not x["hidden"]]
    if not order:
        return None
    full = f["order"]
    i = next((n for n, x in enumerate(full) if x["active"]), 0)
    now = full[i] if full else None
    nxt = next((full[(i + k) % len(full)] for k in range(1, len(full) + 1) if dm or not full[(i + k) % len(full)]["hidden"]), None)
    seen_now = now if now and (dm or not now["hidden"]) else None
    # A reminder (follow) is for that character's player and the DM (Brett, 2026-10-29)
    reminders = [{**r, "mine": r["character"] in mine} for r in f.get("reminders") or [] if dm or r["character"] in mine]
    return {"round": f["round"], "turn": f["turn"], "order": order, "now": seen_now, "next": nxt,
            "yours": bool(seen_now and seen_now.get("character") in mine),
            "next_yours": bool(nxt and nxt.get("character") in mine and nxt is not now), "reminders": reminders}


def for_person(db: Session, campaign: Campaign | None, email: str | None) -> dict | None:
    """shown() for someone at the table: their own characters' turns are "yours"; the DM (and admins) see hidden tokens."""
    if campaign is None or not email:
        return None
    me = access.user_id(email)
    mine = set(db.scalars(select(Character.id).where(Character.owner_id == me))) if me else set()
    f = shown(campaign, access.allows("fight_hidden", access.level(email), access.role(email, campaign.id)), mine)
    if f:  # a character's picture is its portrait, as on its own page; a creature's, its token's, else its Monster
        from app import characters as chars  # Manual art (rules_data.pictures, by D&D Beyond's monster id)
        from app import rules_data

        ids = {x["character"] for x in f["order"] if x.get("character")}
        sheets = {c.id: chars.character_summary(c) or {} for c in db.scalars(select(Character).where(Character.id.in_(ids)))} if ids else {}
        art = {str(p["ddb_id"]): p["image"] for p in rules_data.pictures().values() if p.get("ddb_id") and p.get("image")}
        f["order"] = [{**x, "picture": sheets.get(x.get("character"), {}).get("portrait") or x.get("image") or art.get(x.get("monster") or ""),
                       # a character at 0 Hit Points (app/death_saves.py): its token striped, "0 HP"
                       "down": ((sheets.get(x.get("character")) or {}).get("hit_points") or {}).get("current") == 0}
                      for x in f["order"]]
        now = next((i for i, x in enumerate(f["order"]) if x.get("active")), None)
        f["next"] = f["order"][(now + 1) % len(f["order"])]["name"] if now is not None and len(f["order"]) > 1 else ""  # (those this person sees)
    return f


def _load_from_db(campaign_id: int, email: str | None) -> dict | None:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return for_person(db, db.get(Campaign, campaign_id), email)


# Character pages and Party draw the band (templating.fight_now), with their own short session like Game Mode's;
# tests point it at their session
loader: Callable[[int, str | None], dict | None] = _load_from_db


def timing(campaign: Campaign | None, character_id: int, entry: dict) -> dict:
    """How a condition's time shows on its pill and badge (app/conditions.py): {"short", "long", "soon": it ends or asks
    for its save on the turn running now, or ran out}."""
    from app import conditions as cond

    la = entry.get("lasts") or {}
    f = campaign.fight if campaign is not None and campaign.fight and shown(campaign, dm=True) else None
    active = active_key(f)
    mine = next((x["key"] for x in (f or {}).get("order", []) if x.get("character") == character_id), None)
    of = mine if (la.get("of") or {}).get("self") else (la.get("of") or {}).get("key")
    now = bool(active and active == of and ((la.get("kind") == "endnext" and entry.get("armed")) or la.get("kind") == "save"))
    return {"short": cond.lasts_short(entry, now=now and la.get("kind") == "endnext"), "long": cond.lasts_long(entry),
            "soon": bool(entry.get("due")) or now}

