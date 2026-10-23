"""What the Campaign page's Quests and Relationships tabs show (roadmap step 11; Brett 2026-10-22, Q1 and R1 with R2
in docs/mockups/campaign-tabs.html): the quest board, family trees, the other ties, and one entry's connections.

`visible` decides who sees which entries (hidden ones only for the DM, reviewers and admins)."""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import entities
from app.extraction import timeline
from app.models import Entity, EntityKind, EntityRelation, EventEntity, Status, StoryEvent
from app.relations import TYPES

Visible = Callable[[Entity], bool]
QUIET_AFTER = 3  # sessions without a key moment before an open quest says so


def _relations(db: Session, campaign_id: int, visible: Visible, types=None) -> list[EntityRelation]:
    q = select(EntityRelation).join(Entity, Entity.id == EntityRelation.from_entity_id).where(Entity.campaign_id == campaign_id)
    if types:
        q = q.where(EntityRelation.type.in_(types))
    return [r for r in db.scalars(q.order_by(EntityRelation.id)) if r.type in TYPES and visible(r.from_entity) and visible(r.to_entity)]


def _co_mentioned(db: Session, entity_id: int) -> list[int]:
    """Entries mentioned in the same published key moments as this one, in story order of first mention."""
    events = select(EventEntity.event_id).join(StoryEvent, StoryEvent.id == EventEntity.event_id).where(
        EventEntity.entity_id == entity_id, StoryEvent.status == Status.PUBLISHED)
    rows = db.execute(select(EventEntity.entity_id, EventEntity.event_id).where(EventEntity.event_id.in_(events),
                                                                                  EventEntity.entity_id != entity_id)).all()
    seen: list[int] = []
    for eid, _ in sorted(rows, key=lambda r: r[1]):
        if eid not in seen:
            seen.append(eid)
    return seen


# --- Quests ------------------------------------------------------------------------


def givers(db: Session, quest: Entity, visible: Visible) -> list[Entity]:
    """Who gave the quest (the "gave" relationship)."""
    rels = db.scalars(select(EntityRelation).where(EntityRelation.type == "gave", EntityRelation.to_entity_id == quest.id))
    return [r.from_entity for r in rels if visible(r.from_entity)]


def quest_card(db: Session, quest: Entity, visible: Visible, order: dict[int, int], latest_index: int | None) -> dict:
    """One quest on the board: who gave it, where it started, its key moments, who and where it involves, the
    table's facts, and whether it has gone quiet."""
    moments = entities.moments(db, quest)
    gave = givers(db, quest, visible)
    who = list(gave)
    for eid in _co_mentioned(db, quest.id):
        e = db.get(Entity, eid)
        if e is not None and visible(e) and e not in who:
            who.append(e)
    quiet = ""
    if quest.quest_open is not False and moments and latest_index is not None:
        last = moments[-1]["e"].session_id
        if latest_index - order.get(last, latest_index) >= QUIET_AFTER:
            quiet = moments[-1]["label"]
    return {"q": quest, "givers": gave, "moments": moments, "who": who, "facts": entities.merged_facts(db, quest.id), "quiet": quiet}


def quest_board(db: Session, campaign_id: int, quests: list[Entity], visible: Visible, latest: int | None) -> list[dict]:
    order = {s.id: i for i, s in enumerate(timeline(db, campaign_id))}
    return [quest_card(db, q, visible, order, order.get(latest) if latest else None) for q in quests]


def part_of(db: Session, entity: Entity, visible: Visible) -> list[Entity]:
    """The quests an entry is part of: it gave them, or it's in their key moments."""
    found = [r.to_entity for r in db.scalars(select(EntityRelation).where(EntityRelation.type == "gave", EntityRelation.from_entity_id == entity.id))]
    for eid in _co_mentioned(db, entity.id):
        e = db.get(Entity, eid)
        if e is not None and e.kind == EntityKind.QUEST and e not in found:
            found.append(e)
    return [q for q in found if q.kind == EntityKind.QUEST and visible(q)]


# --- Family trees --------------------------------------------------------------------


@dataclass
class Group:
    """People in one row of a family tree: the children of one set of parents, or (in the top row and for people
    who married in) people with no parents in the record."""

    parents: list[Entity]
    people: list[Entity]


@dataclass
class Family:
    name: str
    rows: list[list[Group]]
    spouses: dict[int, list[Entity]] = field(default_factory=dict)  # who each person is married to
    siblings: dict[int, list[Entity]] = field(default_factory=dict)  # siblings with no parents in the record


def families(db: Session, campaign_id: int, visible: Visible) -> list[Family]:
    """Everyone tied by parent, marriage or sibling links, one tree per family: generations in rows (parents
    above children; spouses and siblings in the same row), children grouped by their parents."""
    rels = _relations(db, campaign_id, visible, ("parent_of", "married_to", "sibling_of"))
    people: dict[int, Entity] = {}
    parents: dict[int, set[int]] = {}
    pairs: dict[str, list[tuple[int, int]]] = {"married_to": [], "sibling_of": []}
    for r in rels:
        people[r.from_entity_id], people[r.to_entity_id] = r.from_entity, r.to_entity
        if r.type == "parent_of":
            parents.setdefault(r.to_entity_id, set()).add(r.from_entity_id)
        else:
            pairs[r.type].append((r.from_entity_id, r.to_entity_id))
    # Families: connected by any of the three
    link: dict[int, set[int]] = {p: set() for p in people}
    for kid, ps in parents.items():
        for p in ps:
            link[kid].add(p)
            link[p].add(kid)
    for a, b in pairs["married_to"] + pairs["sibling_of"]:
        link[a].add(b)
        link[b].add(a)
    name = lambda pid: people[pid].name.casefold()  # noqa: E731
    gen: dict[int, int] = {}

    def generation(pid: int, path=()) -> int:
        if pid not in gen:
            above = [p for p in parents.get(pid, ()) if p not in path]
            gen[pid] = max((generation(p, (*path, pid)) + 1 for p in above), default=0)
        return gen[pid]

    for p in people:
        generation(p)
    # Spouses, siblings and co-parents share a row: lift the lower one (a few passes settle it)
    for _ in range(len(people)):
        changed = False
        same = pairs["married_to"] + pairs["sibling_of"] + [tuple(sorted(ps))[:2] for ps in parents.values() if len(ps) > 1]
        for a, b in same:
            m = max(gen[a], gen[b])
            if gen[a] != m or gen[b] != m:
                gen[a] = gen[b] = m
                changed = True
        for kid, ps in parents.items():  # children stay below their parents
            m = max(gen[p] for p in ps) + 1
            if gen[kid] < m:
                gen[kid], changed = m, True
        if not changed:
            break
    married = {}
    for a, b in pairs["married_to"]:
        married.setdefault(a, []).append(b)
        married.setdefault(b, []).append(a)

    def couples_together(ids: list[int]) -> list[int]:
        """Name order, but each person's spouse right after them."""
        out: list[int] = []
        for p in ids:
            if p not in out:
                out += [p] + [s for s in married.get(p, []) if s in ids and s not in out]
        return out

    out, done = [], set()
    for start in sorted(people, key=lambda p: (gen[p], name(p))):
        if start in done:
            continue
        comp, stack = {start}, [start]
        while stack:
            for n in link[stack.pop()] - comp:
                comp.add(n)
                stack.append(n)
        done |= comp
        rows = []
        for g in sorted({gen[p] for p in comp}):
            groups: dict[frozenset, list[int]] = {}
            for p in sorted((p for p in comp if gen[p] == g), key=name):
                groups.setdefault(frozenset(parents.get(p, ())), []).append(p)
            rows.append([Group(sorted((people[x] for x in key), key=lambda e: e.name.casefold()), [people[x] for x in couples_together(kids)])
                         for key, kids in sorted(groups.items(), key=lambda kv: (bool(kv[0]), min(name(x) for x in kv[1])))])
        top = rows[0][0].people
        couple = next(([people[a], people[b]] for a, b in pairs["married_to"] if a in comp and b in comp and gen[a] == gen[top[0].id]), None)
        title = f"{couple[0].name} and {couple[1].name}'s family" if couple else f"{top[0].name}'s family"
        fam = Family(title, rows)
        for a, b in pairs["married_to"]:
            if a in comp:
                fam.spouses.setdefault(a, []).append(people[b])
                fam.spouses.setdefault(b, []).append(people[a])
        for a, b in pairs["sibling_of"]:
            if a in comp and not (parents.get(a) and parents.get(a) == parents.get(b)):
                fam.siblings.setdefault(a, []).append(people[b])
                fam.siblings.setdefault(b, []).append(people[a])
        out.append(fam)
    return out


def ties(db: Session, campaign_id: int, visible: Visible) -> dict:
    """The ties that aren't family: factions and their members, who serves whom, allies, enemies, quests given."""
    rels = _relations(db, campaign_id, visible, ("member_of", "serves", "ally_of", "enemy_of", "gave"))
    members: dict[int, tuple[Entity, list[Entity]]] = {}
    for r in rels:
        if r.type == "member_of":
            members.setdefault(r.to_entity_id, (r.to_entity, []))[1].append(r.from_entity)
    return {
        "factions": sorted(members.values(), key=lambda m: m[0].name.casefold()),
        "serves": [r for r in rels if r.type == "serves"],
        "allies": [r for r in rels if r.type == "ally_of"],
        "enemies": [r for r in rels if r.type == "enemy_of"],
        "gave": [r for r in rels if r.type == "gave"],
    }


# --- One entry's connections (R2) -----------------------------------------------------------

W = 900  # the diagram's width in its own units; nodes and lines are placed in these and drawn in percent


@dataclass
class Node:
    entity: Entity
    label: str  # how this entry is tied to the one in the middle ("parent of", "ally of")
    group: str  # family, allegiance, ally, enemy, quest: the line's style
    x: float
    y: float


def _group(type_: str) -> str:
    return {"parent_of": "family", "married_to": "family", "sibling_of": "family", "member_of": "allegiance", "serves": "allegiance",
            "ally_of": "ally", "enemy_of": "enemy", "gave": "quest"}[type_]


def connections(db: Session, entity: Entity, visible: Visible) -> dict:
    """Everyone tied to one entry, laid out around it: family keeps its shape (parents above, spouse and siblings
    beside, children below); allies and enemies on the left; factions, service and quests on the right."""
    rels = [r for r in db.scalars(select(EntityRelation).where(
        or_(EntityRelation.from_entity_id == entity.id, EntityRelation.to_entity_id == entity.id))) if r.type in TYPES]
    lines = []
    for r in rels:
        mine = r.from_entity_id == entity.id
        other = r.to_entity if mine else r.from_entity
        if other.id != entity.id and visible(other):
            lines.append((r.type, mine, other, TYPES[r.type].forward if mine else TYPES[r.type].inverse))
    lines.sort(key=lambda l: l[2].name.casefold())
    cx, cy = W / 2, 250
    nodes: list[Node] = []

    def row(items, y):
        for i, (t, _, o, label) in enumerate(items):
            nodes.append(Node(o, label, _group(t), cx + (i - (len(items) - 1) / 2) * 175, y))

    def col(items, x, y0):
        for i, (t, _, o, label) in enumerate(items):
            nodes.append(Node(o, label, _group(t), x, y0 + i * 58))

    pick = lambda f: [l for l in lines if f(l)]  # noqa: E731
    above = pick(lambda l: l[0] == "parent_of" and not l[1])
    below = pick(lambda l: l[0] == "parent_of" and l[1])
    sibs, spouses = pick(lambda l: l[0] == "sibling_of"), pick(lambda l: l[0] == "married_to")
    left_a, left_e = pick(lambda l: _group(l[0]) == "ally"), pick(lambda l: _group(l[0]) == "enemy")
    right = pick(lambda l: _group(l[0]) in ("allegiance", "quest"))
    row(above, 70)
    row(below, 430)
    col(sibs, cx - 280, cy - (len(sibs) - 1) * 29)
    col(spouses, cx + 280, cy - (len(spouses) - 1) * 29)
    heads = []
    y = 100
    if left_a:
        heads.append(("Allies", 95, y - 34))
        col(left_a, 95, y)
        y += len(left_a) * 58 + 50
    if left_e:
        heads.append(("Enemies", 95, y - 34))
        col(left_e, 95, y)
    if right:
        heads.append(("Factions and quests" if any(_group(l[0]) == "quest" for l in right) else "Factions and service", W - 95, 66))
        col(right, W - 95, 100)
    height = max([500] + [n.y + 60 for n in nodes])
    pct = lambda x, y: (round(100 * x / W, 2), round(100 * y / height, 2))  # noqa: E731
    return {"e": entity, "nodes": nodes, "heads": heads, "w": W, "h": height, "cx": cx, "cy": cy, "pct": pct,
            "lines": sorted(lines, key=lambda l: list(TYPES).index(l[0]))}
