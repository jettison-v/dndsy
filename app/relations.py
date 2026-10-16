"""Relationships between entities: types and their wording, adding and
removing them, and the family tree drawn from parent_of + married_to."""

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Entity, EntityRelation


@dataclass(frozen=True)
class RelType:
    forward: str  # "A <forward> B"
    inverse: str  # how B's page describes it
    symmetric: bool = False


TYPES: dict[str, RelType] = {
    "parent_of": RelType("parent of", "child of"),
    "married_to": RelType("married to", "married to", symmetric=True),
    "sibling_of": RelType("sibling of", "sibling of", symmetric=True),
    "member_of": RelType("member of", "has member"),
    "serves": RelType("serves", "served by"),
    "ally_of": RelType("ally of", "ally of", symmetric=True),
    "enemy_of": RelType("enemy of", "enemy of", symmetric=True),
}
# Choices for the "Add a relationship" form, phrased from the entity page's
# point of view: (value, label). "~" marks the inverse direction.
CHOICES = [(t, rt.forward) for t, rt in TYPES.items()] + [
    ("~" + t, rt.inverse) for t, rt in TYPES.items() if not rt.symmetric
]


class RelationError(ValueError):
    pass


def find(db: Session, from_id: int, type_: str, to_id: int) -> EntityRelation | None:
    """The existing link, either way round for symmetric types."""
    pairs = [(from_id, to_id)] + ([(to_id, from_id)] if TYPES[type_].symmetric else [])
    return db.scalar(
        select(EntityRelation).where(
            EntityRelation.type == type_,
            or_(*[(EntityRelation.from_entity_id == a) & (EntityRelation.to_entity_id == b) for a, b in pairs]),
        )
    )


def add(db: Session, from_entity: Entity, type_: str, to_entity: Entity, note: str = "") -> tuple[EntityRelation, bool]:
    """(relation, created). Adding one that already exists returns it unchanged."""
    if type_.startswith("~"):  # chosen from the other entity's point of view
        from_entity, to_entity, type_ = to_entity, from_entity, type_[1:]
    if type_ not in TYPES:
        raise RelationError(f"Unknown relationship type: {type_}")
    if from_entity.id == to_entity.id:
        raise RelationError("An entity can't be related to itself.")
    if from_entity.campaign_id != to_entity.campaign_id:
        raise RelationError("Those two belong to different campaigns.")
    existing = find(db, from_entity.id, type_, to_entity.id)
    if existing:
        return existing, False
    rel = EntityRelation(from_entity_id=from_entity.id, type=type_, to_entity_id=to_entity.id, note=note.strip()[:300])
    db.add(rel)
    db.flush()
    return rel, True


@dataclass
class Line:
    """One relationship as an entity page shows it: "<label> <other>"."""

    id: int
    label: str
    other: Entity
    note: str


def lines_for(db: Session, entity: Entity) -> list[Line]:
    rels = db.scalars(
        select(EntityRelation).where(
            or_(EntityRelation.from_entity_id == entity.id, EntityRelation.to_entity_id == entity.id)
        )
    )
    out = []
    for r in rels:
        rt = TYPES.get(r.type)
        if rt is None:
            continue
        if r.from_entity_id == entity.id:
            out.append(Line(r.id, rt.forward, r.to_entity, r.note))
        else:
            out.append(Line(r.id, rt.inverse, r.from_entity, r.note))
    order = {rt.forward: i for i, rt in enumerate(TYPES.values())} | {rt.inverse: i + 0.5 for i, rt in enumerate(TYPES.values())}
    return sorted(out, key=lambda l: (order.get(l.label, 99), l.other.name.casefold()))


def describe(db: Session, campaign_id: int) -> list[str]:
    """Every relationship as a sentence, for Claude's known-world context."""
    q = (
        select(EntityRelation)
        .join(Entity, Entity.id == EntityRelation.from_entity_id)
        .where(Entity.campaign_id == campaign_id)
        .order_by(EntityRelation.id)
    )
    return [
        f"{r.from_entity.name} {TYPES[r.type].forward} {r.to_entity.name}" + (f" ({r.note})" if r.note else "")
        for r in db.scalars(q)
        if r.type in TYPES
    ]


# --- Family tree ---------------------------------------------------------------


@dataclass
class TreeNode:
    """A person and their spouse(s), with their children's nodes beneath."""

    person: Entity
    spouses: list[Entity] = field(default_factory=list)
    children: list["TreeNode"] = field(default_factory=list)


def family_tree(db: Session, campaign_id: int, visible=lambda e: True) -> list[TreeNode]:
    """Descendant trees from parent_of and married_to links. Each person's
    children are listed once; someone who married into a family appears beside
    their spouse and again (without their children) under their own parents."""
    rels = [
        r
        for r in db.scalars(
            select(EntityRelation)
            .join(Entity, Entity.id == EntityRelation.from_entity_id)
            .where(Entity.campaign_id == campaign_id, EntityRelation.type.in_(("parent_of", "married_to")))
        )
        if visible(r.from_entity) and visible(r.to_entity)
    ]
    people: dict[int, Entity] = {}
    children: dict[int, list[int]] = {}
    parents: dict[int, set[int]] = {}
    spouses: dict[int, list[int]] = {}
    for r in rels:
        people[r.from_entity_id], people[r.to_entity_id] = r.from_entity, r.to_entity
        if r.type == "parent_of":
            children.setdefault(r.from_entity_id, []).append(r.to_entity_id)
            parents.setdefault(r.to_entity_id, set()).add(r.from_entity_id)
        else:
            spouses.setdefault(r.from_entity_id, []).append(r.to_entity_id)
            spouses.setdefault(r.to_entity_id, []).append(r.from_entity_id)

    def name(pid):
        return people[pid].name.casefold()

    expanded: set[int] = set()

    def couple_of(pid: int) -> list[int]:
        return [pid] + sorted(set(s for s in spouses.get(pid, []) if s != pid), key=name)

    def build(pid: int) -> TreeNode:
        couple = couple_of(pid)
        expanded.update(couple)
        node = TreeNode(people[pid], [people[s] for s in couple[1:]])
        for k in sorted({c for p in couple for c in children.get(p, [])}, key=name):
            if k in expanded:  # already drawn elsewhere: show them here, without repeating their family
                node.children.append(TreeNode(people[k], [people[s] for s in couple_of(k)[1:]]))
            else:
                node.children.append(build(k))
        return node

    roots: list[TreeNode] = []
    # Start from people with no known parents whose spouses have none either;
    # anyone left over (unusual links) starts a tree of their own.
    candidates = sorted(people, key=name)
    first = [p for p in candidates if not parents.get(p) and not any(parents.get(s) for s in spouses.get(p, []))]
    for pid in first + candidates:
        if pid not in expanded:
            roots.append(build(pid))
    return roots
