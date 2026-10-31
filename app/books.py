"""Books: private rules content from the books the DM owns (data strategy, 2026-10-27,
docs/plans/2026-10-27-data-strategy.md; the sources model, docs/plans/2026-10-26-content-sources.md).

Rules content comes in layers, read as one by rules_data.catalog/find: the campaign's own (campaign_content), then
its books, then the SRD (files in the repo). A book's entries live only in the database (models.BookEntry), copied in
by scripts/book_load.py from the offline copy in private/books/; never in the repo, test fixtures or docs.

Checked once: each campaign keeps its list of books (Campaign.books), mirroring what the DM shares on D&D Beyond. Its
DM or an admin switches each on or off on Manage › Settings › Books; every lookup reads that list from the campaign
row. Nothing is checked when a game loads and nothing is asked of D&D Beyond.

The first book: the whole 2024 Monster Manual, labelled "MM 2024". Wild Shape reads its Beasts.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    key: str  # "mm-2024"
    title: str  # "Monster Manual (2024)"
    short: str  # "MM 2024": the label beside an entry from it
    ddb_source_id: int  # D&D Beyond's id for the book (a sheet's spells and items name it)


# The books askdnd knows, in lookup order (a book earlier in the list wins when two have the same entry)
BOOKS = (
    Book("phb-2024", "Player's Handbook (2024)", "PHB 2024", 145),
    Book("dmg-2024", "Dungeon Master's Guide (2024)", "DMG 2024", 146),
    Book("mm-2024", "Monster Manual (2024)", "MM 2024", 147),
)
BY_KEY = {b.key: b for b in BOOKS}
DEFAULT = tuple(b.key for b in BOOKS)  # a new campaign's: the 2024 core books (the SRD is always on)
DEFAULT_JSON = json.dumps(list(DEFAULT))
KIND_NAMES = {"monster": ("monster", "monsters"), "spell": ("spell", "spells"), "magic_item": ("magic item", "magic items")}


def book(key: str) -> Book | None:
    return BY_KEY.get(key)


def on(campaign) -> list[str]:
    """The keys of a campaign's books that are on, in lookup order."""
    mine = set(campaign.books or []) if campaign is not None else set()
    return [b.key for b in BOOKS if b.key in mine]


def label(entry: dict) -> str:
    """Where an entry is from, for the page: "MM 2024 p. 373", "SRD 5.2.1", "Homebrew"."""
    page = entry.get("page")
    return f"{entry.get('source', '')} p. {page}" if page else entry.get("source", "")


# ------------------------------------------------------------------ reading


_read: dict[tuple, tuple] = {}  # (books, kind) -> (what the database had, the entries): read and checked once


def entries(db, kind: str, campaign_id: int | None) -> list[dict]:
    """The entries of a kind in the campaign's books that are on (the first book wins a key), validated; each with
    "source" (the book's short label), "page" and "image". An entry that no longer fits its schema is left out.
    Read and checked once, then kept until a book entry is added, changed or removed (one small query says so), so a
    character page doesn't read a whole book each time. Like the SRD's, the entries are shared: read, never change."""
    if db is None or campaign_id is None:
        return []
    from sqlalchemy import func, select

    from app import rules_data
    from app.models import BookEntry, Campaign

    keys = on(db.get(Campaign, campaign_id))
    if not keys or kind not in rules_data.CAMPAIGN_KINDS:
        return []
    version = tuple(db.execute(select(func.count(), func.max(BookEntry.id), func.max(BookEntry.updated_at))
                               .where(BookEntry.book.in_(keys), BookEntry.kind == kind)).one())
    kept = _read.get((tuple(keys), kind))
    if kept and kept[0] == version:
        return kept[1]
    _read[(tuple(keys), kind)] = (version, out := _entries(db, kind, keys))
    return out


def _entries(db, kind: str, keys: list[str]) -> list[dict]:
    from sqlalchemy import select

    from app import rules_data
    from app.models import BookEntry

    order = {k: i for i, k in enumerate(keys)}
    rows = sorted(db.scalars(select(BookEntry).where(BookEntry.book.in_(keys), BookEntry.kind == kind)),
                  key=lambda r: order[r.book])
    out: dict[str, dict] = {}
    for r in rows:
        if r.key in out:
            continue
        entry = {**(r.data or {}), "key": r.key, "name": r.name, "source": BY_KEY[r.book].short}
        if not rules_data.fits(kind, entry, f"book entry {r.id} ({r.book} {kind} {r.key})"):
            continue
        out[r.key] = {**entry, "page": r.page, **({"image": r.image} if r.image else {})}
    return list(out.values())


def counts(db) -> dict[str, dict[str, int]]:
    """What's in askdnd from each book: {"mm-2024": {"monster": 91}}."""
    from sqlalchemy import func, select

    from app.models import BookEntry

    out: dict[str, dict[str, int]] = {}
    for b, kind, n in db.execute(select(BookEntry.book, BookEntry.kind, func.count()).group_by(BookEntry.book, BookEntry.kind)):
        out.setdefault(b, {})[kind] = n
    return out


def rows(db, campaign) -> list[dict]:
    """Manage › Settings › Books: each book with entries in askdnd, what's in it, and whether it's on here."""
    have, mine = counts(db), set(on(campaign))
    out = []
    for b in BOOKS:
        if b.key not in have:
            continue
        what = ", ".join(f"{n} {KIND_NAMES[k][n != 1]}" for k, n in sorted(have[b.key].items()))
        out.append({"b": b, "what": what, "on": b.key in mine})
    return out


# ------------------------------------------------------------------ changing


def switch(campaign, key: str, turn_on: bool) -> str:
    """Switch a book on or off for a campaign; returns what happened. Nothing is deleted: switching it back on
    brings its entries back."""
    b = book(key)
    if b is None:
        return "askdnd doesn't know that book."
    campaign.books = [k for k in (campaign.books or []) if k != key] + ([key] if turn_on else [])
    return f"{b.title} is {'on' if turn_on else 'off'} for {campaign.name}."


def save(db, book_key: str, kind: str, entry: dict, page: int | None = None, image: str = ""):
    """Add or replace one entry of a book (validated first; raises ValueError if it doesn't fit). Its key is its
    name's slug unless it has one; the same key as an SRD entry replaces that entry where the book is on."""
    from sqlalchemy import select

    from app import rules_data
    from app.models import BookEntry

    b = book(book_key)
    if b is None:
        raise ValueError(f"askdnd doesn't know the book {book_key!r}")
    if kind not in rules_data.CAMPAIGN_KINDS:
        raise ValueError(f"a book entry can't be a {kind}")
    entry = {**entry, "key": entry.get("key") or rules_data.slug(entry.get("name", "")), "source": b.short}
    rules_data.check(kind, entry)
    row = db.scalar(select(BookEntry).where(BookEntry.book == b.key, BookEntry.kind == kind, BookEntry.key == entry["key"]))
    if row is None:
        row = BookEntry(book=b.key, kind=kind, key=entry["key"])
        db.add(row)
    row.name, row.page, row.image = entry["name"], page, image or ""
    row.data = {k: v for k, v in entry.items() if k not in ("key", "name", "source")}
    db.flush()
    _read.clear()  # (a change in this same transaction has the same time as the read before it)
    return row
