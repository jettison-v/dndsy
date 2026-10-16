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
class FamilyUnit:
    """One set of parents (married or not) and their children."""

    parents: list[int]
    married: bool
    children: list[int] = field(default_factory=list)


@dataclass
class FamilyGraph:
    people: dict[int, Entity]
    units: list[FamilyUnit]

    def mermaid(self) -> str:
        """Mermaid flowchart text: each person once; parents join at a dot
        (red if married, grey if not) and the dot points to their children."""

        def label(e: Entity) -> str:
            return e.name.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")

        lines = ["flowchart TD"]
        for pid, e in sorted(self.people.items(), key=lambda kv: kv[1].name.casefold()):
            lines.append(f'  P{pid}["{label(e)}"]:::person')
            lines.append(f'  click P{pid} href "/campaign/{pid}"')
        for i, u in enumerate(self.units):
            lines.append(f"  U{i}(( )):::{'married' if u.married else 'parents'}")
            for pid in u.parents:
                lines.append(f"  P{pid} --- U{i}")
            for kid in u.children:
                lines.append(f"  U{i} --> P{kid}")
        lines += [
            "  classDef person fill:#272b30,stroke:#4a4f57,color:#ebe7df,rx:8,ry:8",
            "  classDef married fill:#d64545,stroke:#d64545",
            "  classDef parents fill:#6f6b64,stroke:#6f6b64",
        ]
        return "\n".join(lines)


def family_graph(db: Session, campaign_id: int, visible=lambda e: True) -> FamilyGraph:
    """Everyone linked by parent_of or married_to, grouped into family units:
    children are grouped by their exact set of parents; a married couple with
    no shared children still forms a unit."""
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
    parents_of: dict[int, set[int]] = {}
    marriages: set[frozenset[int]] = set()
    for r in rels:
        people[r.from_entity_id], people[r.to_entity_id] = r.from_entity, r.to_entity
        if r.type == "parent_of":
            parents_of.setdefault(r.to_entity_id, set()).add(r.from_entity_id)
        elif r.from_entity_id != r.to_entity_id:
            marriages.add(frozenset((r.from_entity_id, r.to_entity_id)))

    def name(pid):
        return people[pid].name.casefold()

    units: dict[frozenset[int], FamilyUnit] = {}
    for kid in sorted(parents_of, key=name):
        key = frozenset(parents_of[kid])
        unit = units.setdefault(key, FamilyUnit(sorted(key, key=name), key in marriages))
        unit.children.append(kid)
    for couple in sorted(marriages, key=lambda c: sorted(name(p) for p in c)):
        if couple in units:
            units[couple].married = True
        else:
            units[couple] = FamilyUnit(sorted(couple, key=name), True)
    return FamilyGraph(people, list(units.values()))
