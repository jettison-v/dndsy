"""A person's race and class (an NPC's World entry; Brett, Nov 7: "very helpful for generating images"): kept in
`Entity.traits`, given by a draft or the DM, shown on the entry and the start of Describe it's words."""

from app.models import Entity, EntityKind

TRAITS = ("race", "class")  # a person's (an NPC's): Brett, Nov 7


def has_traits(kind) -> bool:
    return str(getattr(kind, "value", kind)) == EntityKind.NPC.value


def clean_traits(race: str = "", class_: str = "") -> dict:
    """A person's race and class as given, each one short line (empty ones left out)."""
    out = {k: " ".join((v or "").split())[:60] for k, v in (("race", race), ("class", class_))}
    return {k: v for k, v in out.items() if v}


def traits_line(entity: Entity, sep: str = " · ") -> str:
    """ "Owlin · Wizard" (or what's known of it); empty for anything that isn't a person."""
    t = (entity.traits or {}) if has_traits(entity.kind) else {}
    return sep.join(t[k] for k in TRAITS if t.get(k))
