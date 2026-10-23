"""The campaign map: AideDD's interactive Sword Coast atlas (map by Mike Schley).

We don't host the map. The Campaign page's Map tab shows AideDD's page in a frame, and a
place in the campaign record gets "Show on map" when its name, or one of its other names
or spellings, matches a marker there. The marker names live in
app/data/sword_coast_places.txt (refresh with scripts/atlas_places.py).
"""

from functools import cache
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter

from app import web
from app.models import Entity, EntityKind

router = APIRouter()

ATLAS_URL = "https://www.aidedd.org/atlas/sword-coast"
CREDIT = "Sword Coast map by Mike Schley, interactive atlas by AideDD"
PLACES_FILE = Path(__file__).parent / "data" / "sword_coast_places.txt"


@cache
def _markers() -> dict[str, str]:
    """Lowercased marker name -> the name as AideDD spells it."""
    names = (line.strip() for line in PLACES_FILE.read_text(encoding="utf-8").splitlines())
    return {n.lower(): n for n in names if n}


def marker_for(names: list[str]) -> str | None:
    """The first of these names that's a marker on the map (case doesn't matter)."""
    markers = _markers()
    for name in names:
        hit = markers.get(name.strip().lower())
        if hit:
            return hit
    return None


def atlas_url(marker: str | None = None) -> str:
    """AideDD's link for the whole map, or centered on one marker ("…/sword-coast@Star_Mounts")."""
    if not marker:
        return ATLAS_URL
    return f"{ATLAS_URL}@{quote(marker.replace(' ', '_'), safe="_'-")}"


def entity_marker(entity: Entity) -> str | None:
    """The map marker for a place in the campaign record, if it has one."""
    if entity.kind != EntityKind.PLACE:
        return None
    return marker_for([entity.name, *(a.alias for a in entity.aliases)])


def view(at: str = "") -> dict:
    """The Map tab's frame: `at` centers it on that marker (only real markers are used)."""
    marker = marker_for([at]) if at else None
    return {"marker": marker, "src": atlas_url(marker), "credit": CREDIT}


def show_on_map(marker: str) -> str:
    """Where "Show on map" goes: the Campaign page's Map tab, centered on the marker."""
    return f"{web.base()}/campaign?tab=map&at={quote(marker)}"
