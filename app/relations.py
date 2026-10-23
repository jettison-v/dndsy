"""Relationships between entities: types and their wording, adding and
removing them. The Campaign page draws them in app/campaign_views.py."""

from dataclasses import dataclass

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
    "gave": RelType("gave", "given by"),  # a person (or faction) gave a quest (Brett 2026-10-22: the Quests tab's "Given by")
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
