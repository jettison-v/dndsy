"""One-time clean-up (Nov 16): the key moments and theories a redraft doubled.

A session drafted again after it was published, then published again, should show only the redraft's moments. Two
ways it didn't: before Nov 7 publishing kept every moment; from Nov 7 it told a redraft by the published recap's
updated_at, which Listen moves when it measures an older narration (the fix: `StoryEvent.by_hand` and
`review.redrafted`). Either way a session's published moments came from two of Claude's drafts at once, in pairs on
Story, an entry, a quest's steps and the review page.

Claude writes a draft's moments in the same transaction as its recap version, so they share that recap's created_at:
that's a draft batch. In each session, Claude's published moments from every batch but the newest are the doubled ones,
and go, unless one is the session's only moment linked to some entry (an entry's moments and a quest's steps are its
links, `event_entities`; awards point at no moment), which stays. A moment a person wrote or edited is never touched,
nor a draft waiting for review. Deleted one at a time through the app's models, so Manage › History keeps each (with
its links) and can bring it back.

Prints counts per session and kind, never a moment's words. Dry run unless --apply; apply only after a backup:

    uv run python scripts/moment_pairs.py [--url postgresql+psycopg://…]           # what it would remove
    uv run python scripts/moment_pairs.py [--url …] --apply                        # remove them (logs each id)
"""

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

FIND = """
SELECT e.id, e.session_id, s.number, e.kind, e.created_at,
       ARRAY(SELECT x.entity_id FROM event_entities x WHERE x.event_id = e.id ORDER BY x.entity_id) AS links
FROM story_events e JOIN game_sessions s ON s.id = e.session_id
WHERE e.status = 'published'
  AND EXISTS (SELECT 1 FROM recaps r WHERE r.session_id = e.session_id AND r.author = 'ai' AND r.created_at = e.created_at)
  {mine}
ORDER BY e.session_id, e.created_at, e.position, e.id
"""


@dataclass
class Plan:
    remove: list[dict] = field(default_factory=list)  # {"id", "session_id", "number", "kind", "drafted"}
    kept_for_links: list[dict] = field(default_factory=list)


def find(conn) -> Plan:
    """The doubled moments: Claude's published ones from an older draft batch than the session's newest."""
    hand = "by_hand" in {c["name"] for c in inspect(conn).get_columns("story_events")}
    rows = [dict(r._mapping) for r in conn.execute(text(FIND.format(mine="AND NOT e.by_hand" if hand else "")))]
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
        newest = max(m["created_at"] for m in moments)
        older = [m for m in moments if m["created_at"] != newest]
        if not older:
            continue
        gone = {m["id"] for m in older}
        linked = set().union(*(links for eid, links in others.get(sid, {}).items() if eid not in gone))
        for m in older:
            row = {"id": m["id"], "session_id": sid, "number": m["number"], "kind": str(m["kind"]).lower(), "drafted": m["created_at"]}
            if set(m["links"]) <= linked:
                plan.remove.append(row)
            else:
                plan.kept_for_links.append(row)  # the session's only moment linked to an entry: kept
    return plan


def report(plan: Plan, out=print) -> None:
    removing = Counter((r["session_id"], r["number"], r["kind"]) for r in plan.remove)
    keeping = Counter((r["session_id"], r["number"], r["kind"]) for r in plan.kept_for_links)
    if not removing and not keeping:
        out("No doubled key moments.")
        return
    out(f"{'session':>8} {'number':>6}  {'kind':<9} {'remove':>6} {'kept (only link)':>17}")
    for key in sorted(set(removing) | set(keeping), key=lambda k: (k[0], k[2])):
        sid, number, kind = key
        out(f"{sid:>8} {number if number is not None else '-':>6}  {kind:<9} {removing[key]:>6} {keeping[key]:>17}")
    out(f"Total: {len(plan.remove)} to remove, {len(plan.kept_for_links)} kept as the only moment linked to an entry.")


def apply(session: Session, plan: Plan, out=print) -> int:
    """Delete the planned moments one at a time (version history keeps each, with its links); returns how many."""
    from app import history
    from app.models import StoryEvent

    done = 0
    with history.source("cleanup"):
        for r in plan.remove:
            ev = session.get(StoryEvent, r["id"])
            if ev is None or ev.by_hand or ev.status.value != "published":
                continue  # (changed since it was found)
            session.delete(ev)
            done += 1
            out(f"removed key moment {r['id']} (session {r['session_id']}, {r['kind']}, drafted {r['drafted']:%Y-%m-%d %H:%M:%S})")
        session.flush()
    return done


def main(argv: list[str]) -> None:
    from app import config

    url = argv[argv.index("--url") + 1] if "--url" in argv else config.DATABASE_URL
    if not url:
        sys.exit("No database: set DATABASE_URL or give --url.")
    engine = create_engine(url)
    with engine.connect() as conn:
        plan = find(conn)
    report(plan)
    if "--apply" not in argv:
        print("Dry run: nothing changed. Add --apply (after a backup) to remove them.")
        return
    with engine.connect() as conn:
        if "by_hand" not in {c["name"] for c in inspect(conn).get_columns("story_events")}:
            sys.exit("This database isn't migrated yet (story_events.by_hand): run `alembic upgrade head` first.")
    with Session(engine) as session, session.begin():
        done = apply(session, plan)
    print(f"Removed {done} key moments (Manage › History keeps each).")


if __name__ == "__main__":
    main(sys.argv[1:])
