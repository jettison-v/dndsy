"""The Product Taxonomy (Brett, Nov 18, docs/mockups/product-taxonomy/): every issue is about one Feature, every Feature is
in one Product Area. The list is a file (app/data/taxonomy.json), kept with the code it describes and ordering
docs/MAP.md; askdnd keeps a batch (`FftArea` with its `key`) for each Product Area under the standing Fixes and polish
item, made the first time it's needed. A Roadmap build keeps its own batch, with no key.

To reuse Found, Fixed, Tried elsewhere, give that project its own taxonomy.json: nothing here names askdnd's areas."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fft.models import FftArea, FftItem

FILE = Path(__file__).resolve().parent.parent / "data" / "taxonomy.json"


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    area: str  # its Product Area's key
    map: tuple[str, ...]  # the docs/MAP.md sections it owns


@dataclass(frozen=True)
class ProductArea:
    key: str
    title: str
    what: str
    features: tuple[Feature, ...]


@cache
def areas() -> tuple[ProductArea, ...]:
    raw = json.loads(FILE.read_text())["areas"]
    return tuple(ProductArea(a["key"], a["title"], a["what"],
                             tuple(Feature(f["key"], f["title"], a["key"], tuple(f["map"])) for f in a["features"])) for a in raw)


@cache
def _features() -> dict[str, Feature]:
    return {f.key: f for a in areas() for f in a.features}


def feature(key: str) -> Feature | None:
    return _features().get(key or "")


def area(key: str) -> ProductArea | None:
    return next((a for a in areas() if a.key == key), None)


def path(key: str) -> str:
    """"Battle › Hit points", or "" for no Feature (or one the list no longer has)."""
    f = feature(key)
    return f"{area(f.area).title} › {f.title}" if f else ""


def standing_item(db: Session) -> FftItem:
    item = db.scalar(select(FftItem).where(FftItem.standing.is_(True)).order_by(FftItem.id))
    if item is None:
        item = FftItem(title="Fixes and polish", section="now", standing=True, place=(db.scalar(select(func.max(FftItem.place))) or 0) + 1)
        db.add(item)
        db.flush()
    return item


def batch(db: Session, area_key: str) -> FftArea:
    """The Product Area's batch, made under Fixes and polish (at the end of Brett's order) the first time it's needed; its
    title follows the list."""
    pa = area(area_key)
    if pa is None:
        raise KeyError(area_key)
    row = db.scalar(select(FftArea).where(FftArea.key == pa.key).order_by(FftArea.id))
    if row is None:
        item = standing_item(db)
        place = (db.scalar(select(func.max(FftArea.place)).where(FftArea.item_id == item.id)) or 0) + 1
        row = FftArea(item_id=item.id, key=pa.key, title=pa.title[:80], place=place)
        db.add(row)
        db.flush()
    elif row.title != pa.title[:80] or row.archived:
        row.title, row.archived = pa.title[:80], False
    return row
