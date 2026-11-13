"""A session's story beyond the recap (Session Story, Brett Nov 7; docs/mockups/session-story/): the cleaned transcript
kept for drafting, who talked, the share of fights and story, the night's dice and the awards.

The cleaned transcript (the Processor's game talk, every cut reviewed by Brett) is kept in file storage, never in the
database, shown on no page and read only by Claude when drafting the recap (`text`). The raw recording stays on Brett's
Mac. Who talked comes from the Processor too: seconds per speaker name, counted on the Mac (`GameSession.talk`); a
name is matched to someone at the table by their account's name, or once by an admin on the review page
(`Campaign.speakers`). Fights and story come from the full tale's chapters and the times they started. The dice and
the dice awards (Hardest Luck, Damage King) come from Table rolls on the night everyone could see.
"""

import re
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import files
from app.characters import campaign_characters, character_summary
from app.config import TABLE_TIME
from app.extraction import DM_AWARD
from app.models import Campaign, CampaignMember, Character, GameSession, Recap, Role, TableRoll

KINDS = {"fight": "Fights", "story": "Story", "exploring": "Exploring", "rest": "Rest and shopping"}
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI"]
DICE_AWARDS = ("Hardest Luck", "Damage King")  # (Brett's list, Nov 7: from Table rolls, never from Claude)
NOT_HERE = 0  # Campaign.speakers: a name that's no one at the table ("Claude AI", a guest)


# ---------------------------------------------------------------- the cleaned transcript


def keep(db: Session, session: GameSession, text: str, talk: dict | None = None) -> None:
    """Keep what the Processor sent: the cleaned transcript in file storage, and who talked (a start set on the review
    page stays when the Processor didn't send one)."""
    session.transcript_key = files.put(db, session.campaign_id, text.encode(), "text/plain")
    if talk:
        start = (session.talk or {}).get("start")
        session.talk = {**({"start": start} if start else {}), **talk}


def text(session: GameSession) -> str | None:
    """The cleaned transcript, for Claude; None when it isn't kept (sent before Nov 7, or let go)."""
    data = files.read(session.transcript_key)
    return data.decode() if data is not None else None


def forget(session: GameSession) -> None:
    """Let the transcript go: nothing uses it now, and the nightly sweep deletes it once no kept backup needs it."""
    session.transcript_key = None


START = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")  # "18:32", the recording's start at the table's time


def clean_talk(raw) -> dict:
    """The Processor's who-talked numbers, checked: {"speakers": {name: seconds}, "length": seconds, "start": "HH:MM"}
    (when the recording began, at the table's time: Brett, Nov 10, so a session's numbers count only its own rolls)."""
    if not isinstance(raw, dict):
        return {}
    speakers = {" ".join(str(k).split())[:120]: round(float(v), 1) for k, v in (raw.get("speakers") or {}).items()
                if str(k).strip() and isinstance(v, int | float) and 0 < v < 24 * 3600}
    length = raw.get("length")
    out = {"speakers": speakers} if speakers else {}
    if isinstance(length, int | float) and 0 < length < 24 * 3600:
        out["length"] = round(float(length))
    start = raw.get("start")
    if isinstance(start, str) and START.match(start.strip()):
        out["start"] = start.strip().zfill(5)
    return out


def set_start(session: GameSession, start: str) -> None:
    """When the recording began ("HH:MM", "" to forget it): from the Processor, or the review page for a session sent
    before it asked (Brett, Nov 10)."""
    talk = dict(session.talk or {})
    start = (start or "").strip()
    if not start:
        talk.pop("start", None)
    elif START.match(start):
        talk["start"] = start.zfill(5)
    else:
        raise ValueError("A time like 18:30.")
    session.talk = talk


# ---------------------------------------------------------------- who talked


def table(db: Session, campaign: Campaign) -> dict[int, dict]:
    """Everyone at the table now, by user id: how they show in Who talked (a player as their character, the DM as
    "The DM") and the entry whose picture stands for them."""
    chars = {}
    for ch in campaign_characters(db, campaign.id):
        if ch.owner_id and ch.owner_id not in chars and ch.copy_of_id is None:
            chars[ch.owner_id] = ch
    out = {}
    for m in db.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign.id, CampaignMember.left_on.is_(None))):
        ch = chars.get(m.user_id)
        name = ch.name if ch else "The DM" if m.role == Role.DM else (m.user.name or "Someone")
        out[m.user_id] = {"user_id": m.user_id, "person": m.user.name or "", "name": name, "dm": m.role == Role.DM,
                          "entity_id": ch.entity.id if ch and ch.entity else None}
    return out


def match(db: Session, campaign: Campaign, names) -> dict[str, int | None]:
    """Each speaker name's person: the one an admin chose (0: no one at the table), else the person whose account has
    that name, else the one person whose first name it starts with; None when it can't tell."""
    people = table(db, campaign)
    users = {uid: (p["person"] or "").casefold() for uid, p in people.items()}
    out = {}
    for name in names:
        if name in (campaign.speakers or {}):
            out[name] = campaign.speakers[name]
            continue
        n = name.casefold().strip()
        exact = [uid for uid, u in users.items() if u and u == n]
        first = [uid for uid, u in users.items() if u and n and u.split()[0] == n.split()[0]]
        out[name] = exact[0] if len(exact) == 1 else first[0] if len(first) == 1 else None
    return out


def who_talked(db: Session, session: GameSession, campaign: Campaign) -> dict:
    """{"rows": [{name, entity_id, dm, seconds, share}], "unmatched": [names], "names": [{name, seconds, user_id}]}:
    the table's share of the talking, most first. Names no one has matched aren't counted until they are."""
    speakers = (session.talk or {}).get("speakers") or {}
    if not speakers:
        return {"rows": [], "unmatched": [], "names": []}
    people = table(db, campaign)
    matched = match(db, campaign, speakers)
    totals: dict[int, float] = {}
    for name, secs in speakers.items():
        uid = matched.get(name)
        if uid and uid in people:
            totals[uid] = totals.get(uid, 0) + secs
    whole = sum(totals.values()) or 1
    rows = sorted(({**people[uid], "seconds": secs, "share": round(100 * secs / whole)} for uid, secs in totals.items()),
                  key=lambda r: -r["seconds"])
    return {"rows": rows,
            "unmatched": sorted(n for n, uid in matched.items() if uid is None or (uid and uid not in people)),
            "names": sorted(({"name": n, "seconds": s, "user_id": matched.get(n)} for n, s in speakers.items()), key=lambda r: -r["seconds"])}


def set_speaker(campaign: Campaign, name: str, user_id: int) -> None:
    """An admin's match of a speaker name to someone at the table (0: no one), kept for every later session."""
    campaign.speakers = {**(campaign.speakers or {}), " ".join(name.split())[:120]: int(user_id)}


# ---------------------------------------------------------------- fights and story


def clock(secs: int | None) -> str:
    """Seconds into the recording as "1:05" (hours and minutes)."""
    if secs is None:
        return ""
    return f"{secs // 3600}:{secs % 3600 // 60:02d}"


def chapters(recap: Recap | None) -> list[dict]:
    """The full tale's chapters, numbered, with their clock time."""
    return [{**c, "n": ROMAN[i] if i < len(ROMAN) else str(i + 1), "clock": clock(c.get("at")), "kind_label": KINDS.get(c.get("kind"), "Story")}
            for i, c in enumerate(recap.tale if recap else [])]


def mix(session: GameSession, recap: Recap | None) -> dict | None:
    """The night by kind of scene, from when each chapter started: {"parts": [{kind, label, seconds, share}],
    "length"}. None when the chapters have no times (notes), or they don't run in order."""
    times = [c.get("at") for c in (recap.tale if recap else [])]
    if not times or any(t is None for t in times) or times != sorted(times):
        return None
    length = (session.talk or {}).get("length") or 0
    end = max(length, times[-1])
    if end <= times[0]:
        return None
    spans: dict[str, int] = dict.fromkeys(KINDS, 0)
    for i, c in enumerate(recap.tale):
        stop = times[i + 1] if i + 1 < len(times) else end
        spans[c.get("kind") if c.get("kind") in KINDS else "story"] += max(0, stop - times[i])
    whole = sum(spans.values()) or 1
    return {"parts": [{"kind": k, "label": KINDS[k], "seconds": v, "share": round(100 * v / whole)} for k, v in spans.items()],
            "length": length if length else end - times[0]}


# ---------------------------------------------------------------- the night's dice


MARGIN = timedelta(minutes=15)  # (Initiative rolled just before the recording starts, a last roll after it stops)


def night(session: GameSession) -> tuple[datetime, datetime] | None:
    """When the session was played, at the table's time: the recording, from its start (`talk["start"]`) for its length,
    with MARGIN either side (Brett, Nov 10: only the session's own rolls); without a start, the evening: noon to six the
    next morning."""
    if session.played_on is None:
        return None
    talk = session.talk or {}
    if talk.get("start") and talk.get("length"):
        h, m = (int(x) for x in talk["start"].split(":"))
        begin = datetime.combine(session.played_on, time(h, m), tzinfo=TABLE_TIME)
        return begin - MARGIN, begin + timedelta(seconds=talk["length"]) + MARGIN
    start = datetime.combine(session.played_on, time(12), tzinfo=TABLE_TIME)
    return start, start + timedelta(hours=18)


def window_says(session: GameSession) -> str:
    """Which rolls a session's numbers count, in words, for the page's note."""
    talk = session.talk or {}
    if session.played_on and talk.get("start") and talk.get("length"):
        a, b = night(session)
        f = lambda t: t.strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")
        return f"during the session ({f(a + MARGIN)} to {f(b - MARGIN)}, with 15 minutes either side)"
    return "that evening (no recording start time, so noon to 6 am)"


def _rolls(db: Session, session: GameSession) -> list[TableRoll]:
    window = night(session)
    if window is None:
        return []
    return list(db.scalars(select(TableRoll).where(TableRoll.campaign_id == session.campaign_id, TableRoll.visibility == "table",
                                                    TableRoll.created_at >= window[0], TableRoll.created_at < window[1])))


CAST_KINDS = ("attack", "damage", "heal", "temp", "dice")  # (a save is the target's roll, never a cast)
SAME_CAST = timedelta(minutes=2)  # (D&D Beyond's to-hit and damage arrive as two rolls: one cast)


def spells_known(ch: Character) -> list[str]:
    """The spells on a character's D&D Beyond sheet (its spell list and spellbook), longest name first, so a roll's
    label is matched to the whole name ("Raulothim's Psychic Lance" before any shorter one it starts with)."""
    s = character_summary(ch) or {}
    names = {x.get("name") for x in s.get("spells") or [] if isinstance(x, dict)}
    names |= {e.get("name") for c in s.get("spellbook") or [] for e in c.get("spells") or [] if isinstance(e, dict)}
    return sorted((n for n in names if n), key=lambda n: (-len(n), n))


def spell_of(label: str, names: list[str]) -> str | None:
    """The spell a roll was made for, by its label: the spell's name itself or followed by more ("Fire Bolt (2nd
    level)", "Magic Missile: Dart 2")."""
    low = " ".join(label.split()).casefold()
    for n in names:
        f = n.casefold()
        if low == f or (low.startswith(f) and low[len(f)] in " :(-·"):
            return n
    return None


def casts(rolls: list[TableRoll], chars: dict[int, Character]) -> dict:
    """Spells cast that night, as far as the table's rolls show: a roll named for one of the roller's own spells (an
    attack, damage, healing), the same spell by the same character within two minutes counted once. A spell with no
    roll (Bless, Misty Step) isn't seen. {"count", "by": [{character, n, names}]}."""
    known = {cid: spells_known(ch) for cid, ch in chars.items()}
    last: dict[tuple[int, str], datetime] = {}
    by: dict[int, list[str]] = {}
    for r in sorted(rolls, key=lambda r: r.created_at):
        if r.parent_id is not None or r.kind not in CAST_KINDS or r.character_id not in chars:
            continue
        spell = spell_of(r.label, known[r.character_id])
        if not spell:
            continue
        key = (r.character_id, spell)
        if key in last and r.created_at - last[key] <= SAME_CAST:
            last[key] = r.created_at
            continue
        last[key] = r.created_at
        by.setdefault(r.character_id, []).append(spell)
    rows = sorted(({"character": chars[cid], "n": len(names), "names": list(dict.fromkeys(names))} for cid, names in by.items()),
                  key=lambda x: (-x["n"], x["character"].name))
    return {"count": sum(x["n"] for x in rows), "by": rows}


def dice(db: Session, session: GameSession) -> dict:
    """{"rolls", "twenties", "ones", "hardest_luck", "damage_king", "damage", "biggest", "healing", "spells"} from the
    rolls the whole table saw that night (a DM-only or private roll never counts). The two awards: {character, why} or
    None. The night's numbers (Brett chose all four, Nov 9, docs/mockups/full-tale/): damage rolled by each character,
    the biggest single damage roll, healing rolled by each, and spells cast (`casts`)."""
    rolls = _rolls(db, session)
    d20 = [r for r in rolls if r.kept is not None]
    out = {"rolls": sum(1 for r in rolls if r.parent_id is None), "twenties": sum(1 for r in d20 if r.kept == 20),
           "ones": sum(1 for r in d20 if r.kept == 1), "hardest_luck": None, "damage_king": None,
           "damage": [], "biggest": None, "healing": {"total": 0, "by": []}, "spells": {"count": 0, "by": []},
           "window": window_says(session)}
    chars = {r.character_id: r.character for r in rolls if r.character_id and r.character is not None}
    ones: dict[int, list[int]] = {}
    for r in d20:
        if r.character_id in chars:
            ones.setdefault(r.character_id, []).append(r.kept)
    luck = [(sum(1 for k in ks if k == 1), -sum(ks) / len(ks), cid) for cid, ks in ones.items() if 1 in ks]
    if luck:
        n, _, cid = max(luck)
        out["hardest_luck"] = {"character": chars[cid], "why": f"{n} natural 1{'s' if n != 1 else ''} on the d20."}
    damage: dict[int, list[int]] = {}
    for r in rolls:
        if r.kind == "damage" and r.character_id in chars and r.total > 0:
            damage.setdefault(r.character_id, []).append(r.total)
    if damage:
        cid = max(damage, key=lambda c: sum(damage[c]))
        hits = len(damage[cid])
        out["damage_king"] = {"character": chars[cid], "why": f"{sum(damage[cid])} damage rolled, in {hits} roll{'s' if hits != 1 else ''}."}
        out["damage"] = sorted(({"character": chars[c], "total": sum(v), "rolls": len(v)} for c, v in damage.items()),
                               key=lambda x: (-x["total"], x["character"].name))
        big = max((r for r in rolls if r.kind == "damage" and r.character_id in chars and r.total > 0), key=lambda r: (r.total, -r.id))
        src = next((x for x in rolls if x.id == big.parent_id), big)  # (the attack or spell it follows keeps the level cast)
        out["biggest"] = {"character": chars[big.character_id], "total": big.total, "label": big.label, "crit": big.crit,
                          "level": (src.detail or {}).get("level")}
    healing: dict[int, int] = {}
    for r in rolls:
        if r.kind == "heal" and r.character_id in chars and r.total > 0:
            healing[r.character_id] = healing.get(r.character_id, 0) + r.total
    out["healing"] = {"total": sum(healing.values()),
                      "by": sorted(({"character": chars[c], "total": t} for c, t in healing.items()), key=lambda x: (-x["total"], x["character"].name))}
    out["spells"] = casts(rolls, chars)
    return out


def night_numbers(db: Session, rolled: dict) -> dict:
    """The night's numbers from `dice()` as the page draws them: each character as a row with its picture (damage and
    healing with a bar's share of the most), the biggest hit and the spells cast."""
    def person(ch: Character) -> dict:
        return {"name": ch.name, "character_id": ch.id, "entity_id": ch.entity.id if ch.entity else None}

    def bars(rows: list[dict]) -> list[dict]:
        top = max((r["total"] for r in rows), default=0) or 1
        return [{**person(r["character"]), "total": r["total"], "share": round(100 * r["total"] / top)} for r in rows]

    big = rolled.get("biggest")
    out = {"damage": bars(rolled.get("damage") or []),
           "healing": {"total": (rolled.get("healing") or {}).get("total", 0), "rows": bars((rolled.get("healing") or {}).get("by") or [])},
           "biggest": {**person(big["character"]), "total": big["total"], "label": big["label"], "crit": big["crit"], "level": big.get("level")} if big else None,
           "spells": {"count": (rolled.get("spells") or {}).get("count", 0),
                      "rows": [{**person(r["character"]), "n": r["n"], "names": r["names"]} for r in (rolled.get("spells") or {}).get("by") or []]}}
    pictured(db, out["damage"], out["healing"]["rows"], out["spells"]["rows"], [out["biggest"]] if big else [])
    return out


# ---------------------------------------------------------------- awards


def awards(db: Session, session: GameSession, recap: Recap | None, rolled: dict | None = None) -> list[dict]:
    """Claude's awards on this version, then the dice's, each with the character's entry (for its picture and link)."""
    by_name = {}
    for ch in campaign_characters(db, session.campaign_id):
        if ch.entity is not None:
            for n in [ch.name, ch.entity.name] + [a.alias for a in ch.entity.aliases if not a.misspelling]:
                by_name.setdefault(n.casefold(), ch)
    def shown(award: str, n: dict) -> dict:
        dm = award == DM_AWARD or n["character"].casefold().strip() in ("the dm", "dm")
        ch = None if dm else by_name.get(n["character"].casefold())
        return {**n, "who": "The DM" if dm else ch.name if ch else n["character"], "dm": dm,
                "entity_id": ch.entity.id if ch and ch.entity else None, "clock": clock(n.get("at"))}

    out = []
    for i, a in enumerate(recap.awards if recap else []):
        nominees = [shown(a["award"], n) for n in nominees_of(a)]
        pick = picked(a)
        out.append({**nominees[pick], "award": a["award"], "index": i, "nominees": nominees, "pick": pick, "dice": False})
    rolled = rolled if rolled is not None else dice(db, session)
    for award, key in zip(DICE_AWARDS, ("hardest_luck", "damage_king")):
        got = rolled.get(key)
        if got:
            ch: Character = got["character"]
            out.append({"award": award, "who": ch.name, "dm": False, "entity_id": ch.entity.id if ch.entity else None, "why": got["why"], "quote": "",
                        "clock": "", "dice": True})
    return out


def nominees_of(award: dict) -> list[dict]:
    """An award's nominees (one given straight to someone, as drafts before Nov 7 did, is its only nominee)."""
    return award.get("nominees") or [{k: award.get(k) for k in ("character", "why", "quote", "at")}]


def picked(award: dict) -> int:
    """Which nominee the award goes to: the reviewer's pick, else Claude's first."""
    pick = award.get("pick") or 0
    return pick if 0 <= pick < len(nominees_of(award)) else 0


def pictured(db: Session, *lists: list[dict]) -> None:
    """Give each row with an entry its picture's small version ("picture"), for the round portraits."""
    from app import pictures

    shown = pictures.urls(db, {r["entity_id"] for rows in lists for r in rows if r.get("entity_id")})
    for rows in lists:
        for r in rows:
            r["picture"] = (shown.get(r.get("entity_id")) or {}).get("thumb", "")


def has_more(recap: Recap | None) -> bool:
    """Whether a session has a page of its own beyond the recap: a full tale."""
    return bool(recap and recap.tale)

