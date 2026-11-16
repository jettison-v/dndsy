"""One-time clean-up (Nov 16): the key moments and theories a redraft doubled.

A session drafted again after it was published, then published again, should show only the redraft's moments. Two
ways it didn't: before Nov 7 publishing kept every moment; from Nov 7 it told a redraft by the published recap's
updated_at, which Listen moves when it measures an older narration (the fix: `StoryEvent.by_hand` and `.superseded`,
`review.redrafted`). Either way a session's published moments came from two of Claude's drafts at once, in pairs on
Story, an entry, a quest's steps and the review page.

Claude writes a draft's moments in the same transaction as its recap version, so they share that recap's created_at:
that's a draft batch. In each session, Claude's published moments from every batch but the newest are the doubled ones,
and go, except that every entry an older moment links keeps one moment of the session: when no moment that stays links
it, the newest older moment linking it stays (an entry's moments and a quest's steps are its links, `event_entities`;
awards point at no moment). A session whose newest batch is much smaller than an older one looks cleaned up by hand:
it's reported and left alone. A moment a person wrote or edited is never touched, nor a draft waiting for review, nor
one a redraft waiting for review already replaces. Deleted one at a time through the app's models, so Manage › History
keeps each (with its links) and can bring it back.

Prints counts per session and kind, never a moment's words. Dry run unless --apply; apply only after a backup:

    uv run python scripts/moment_pairs.py [--url postgresql://…]           # what it would remove
    uv run python scripts/moment_pairs.py [--url …] --apply                # remove them (logs each id)
"""

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

FIND = """
SELECT e.id, e.session_id, s.number, e.kind, e.created_at, e.position,
       ARRAY(SELECT x.entity_id FROM event_entities x WHERE x.event_id = e.id ORDER BY x.entity_id) AS links
FROM story_events e JOIN game_sessions s ON s.id = e.session_id
WHERE e.status = 'published'
  AND EXISTS (SELECT 1 FROM recaps r WHERE r.session_id = e.session_id AND r.author = 'ai' AND r.created_at = e.created_at)
  {mine}
ORDER BY e.session_id, e.created_at, e.position, e.id
"""
SMALLER = 0.5  # a newest batch under half an older one's size: someone cleaned the session up by hand


@dataclass
class Plan:
    remove: list[dict] = field(default_factory=list)  # {"id", "session_id", "number", "kind", "drafted"}
    kept_for_links: list[dict] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)  # {"session_id", "number", "newest", "older", "skipped"}


def _columns(conn) -> set[str]:
    return {c["name"] for c in inspect(conn).get_columns("story_events")}


def find(conn) -> Plan:
    """The doubled moments: Claude's published ones from an older draft batch than the session's newest."""
    have = _columns(conn)
    mine = " ".join(f"AND NOT e.{c}" for c in ("by_hand", "superseded") if c in have)
    rows = [dict(r._mapping) for r in conn.execute(text(FIND.format(mine=mine)))]
    others = {}  # every moment's links by session, a person's and drafts included (what stays links entries too)
    for sid, eid, links in conn.execute(text(
            "SELECT e.session_id, e.id, ARRAY(SELECT x.entity_id FROM event_entities x WHERE x.event_id = e.id) "
            "FROM story_events e")):
        others.setdefault(sid, {})[eid] = set(links)
    by_session: dict[int, list[dict]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)
    plan = Plan()
    for sid, moments in by_session.items():
        sizes = Counter(m["created_at"] for m in moments)
        newest = max(sizes)
        older = [m for m in moments if m["created_at"] != newest]
        if not older:
            continue
        summary = {"session_id": sid, "number": moments[0]["number"], "newest": sizes[newest], "older": len(older),
                   "biggest_older": max(n for at, n in sizes.items() if at != newest), "skipped": False}
        plan.sessions.append(summary)
        if sizes[newest] < SMALLER * summary["biggest_older"]:
            summary["skipped"] = True  # (reported, nothing removed)
            continue
        gone = {m["id"] for m in older}
        linked = set().union(*(links for eid, links in others.get(sid, {}).items() if eid not in gone))
        for m in sorted(older, key=lambda m: (-m["created_at"].timestamp(), m["position"], m["id"])):  # the newest first
            row = {"id": m["id"], "session_id": sid, "number": m["number"], "kind": str(m["kind"]).lower(), "drafted": m["created_at"]}
            if set(m["links"]) <= linked:
                plan.remove.append(row)
            else:
                plan.kept_for_links.append(row)  # the newest moment linking an entry nothing else that stays links
                linked |= set(m["links"])
    return plan


def report(plan: Plan, out=print) -> None:
    if not plan.sessions:
        out("No doubled key moments.")
        return
    removing = Counter((r["session_id"], r["kind"]) for r in plan.remove)
    keeping = Counter((r["session_id"], r["kind"]) for r in plan.kept_for_links)
    for s in plan.sessions:
        number = s["number"] if s["number"] is not None else "-"
        if s["skipped"]:
            out(f"Session {s['session_id']} (number {number}): skipped, its newest draft has {s['newest']} moments beside "
                f"{s['biggest_older']} in an older one (cleaned up by hand?); nothing removed, {s['older']} older moments left.")
            continue
        out(f"Session {s['session_id']} (number {number}): the newest draft's {s['newest']} moments stay; "
            f"remove {sum(n for (sid, _), n in removing.items() if sid == s['session_id'])} of {s['older']} older, "
            f"keep {sum(n for (sid, _), n in keeping.items() if sid == s['session_id'])} (an entry's only link).")
        for kind in sorted({k for sid, k in set(removing) | set(keeping) if sid == s["session_id"]}):
            out(f"    {kind:<9} remove {removing[(s['session_id'], kind)]:>3}   keep {keeping[(s['session_id'], kind)]:>3}")
    skipped = sum(1 for s in plan.sessions if s["skipped"])
    out(f"Total: {len(plan.remove)} to remove, {len(plan.kept_for_links)} kept as an entry's only link, "
        f"{skipped} session{'' if skipped == 1 else 's'} skipped.")


def apply(session: Session, plan: Plan, out=print) -> int:
    """Delete the planned moments one at a time (version history keeps each, with its links); returns how many."""
    from app import history
    from app.models import StoryEvent

    done = 0
    with history.source("cleanup"):
        for r in plan.remove:
            ev = session.get(StoryEvent, r["id"])
            if ev is None or ev.by_hand or ev.superseded or ev.status.value != "published":
                continue  # (changed since it was found)
            session.delete(ev)
            done += 1
            out(f"removed key moment {r['id']} (session {r['session_id']}, {r['kind']}, drafted {r['drafted']:%Y-%m-%d %H:%M:%S})")
        session.flush()
    return done


def database_url(argv: list[str]) -> str:
    """--url's value (Railway's postgresql:// works too), else DATABASE_URL."""
    from app import config

    if "--url" in argv:
        at = argv.index("--url") + 1
        if at >= len(argv) or argv[at].startswith("--"):
            sys.exit("--url needs the database's address after it, e.g. --url postgresql://localhost/askdnd_beta")
        return config.sqlalchemy_url(argv[at])
    if not config.DATABASE_URL:
        sys.exit("No database: set DATABASE_URL or give --url.")
    return config.DATABASE_URL


def main(argv: list[str]) -> None:
    engine = create_engine(database_url(argv))
    with engine.connect() as conn:
        plan = find(conn)
    report(plan)
    if "--apply" not in argv:
        print("Dry run: nothing changed. Add --apply (after a backup) to remove them.")
        return
    with engine.connect() as conn:
        if not {"by_hand", "superseded"} <= _columns(conn):
            sys.exit("This database isn't migrated yet (story_events.by_hand): run `alembic upgrade head` first.")
    with Session(engine) as session, session.begin():
        done = apply(session, plan)
    print(f"Removed {done} key moments (Manage › History keeps each).")


if __name__ == "__main__":
    main(sys.argv[1:])
