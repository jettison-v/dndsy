"""Sync note sources: export each Google Doc and store a snapshot when it changed."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import files
from app.gdocs import ExportedDoc
from app.models import NoteImage, NoteSnapshot, NoteSource


def store_export(db: Session, source: NoteSource, doc: ExportedDoc, title: str | None = None) -> bool:
    """Save `doc` as a new snapshot if its content changed. Returns True if stored."""
    source.last_synced_at = datetime.now(UTC)
    if title:
        source.title = title
    latest = source.snapshots[-1] if source.snapshots else None
    if latest and latest.content_hash == doc.content_hash:
        return False
    snap = NoteSnapshot(content_hash=doc.content_hash, text=doc.text)
    snap.images = [NoteImage(name=n, content_type=t, data=d, file_key=_store(db, source, t, d)) for n, (t, d) in doc.images.items()]
    source.snapshots.append(snap)
    return True


def _store(db: Session, source: NoteSource, content_type: str, data: bytes) -> str | None:
    """The image's key in file storage. Kinds file storage won't keep stay in the database only, for now (VTT 0.5)."""
    if not files.ready():
        return None
    try:
        return files.put(db, source.campaign_id, data, content_type)
    except files.FileError:
        return None


def sync_sources(
    db: Session,
    sources: list[NoteSource],
    fetch: Callable[[str], tuple[str, ExportedDoc]],
) -> dict[str, str]:
    """`fetch(doc_id)` returns (title, exported doc). Returns a status per source title."""
    results = {}
    for source in sources:
        try:
            title, doc = fetch(source.google_doc_id)
            changed = store_export(db, source, doc, title)
            results[source.title or source.google_doc_id] = (
                f"updated ({len(doc.text.split()):,} words, {len(doc.images)} images)" if changed else "no changes"
            )
        except Exception as e:  # one bad doc shouldn't stop the others
            results[source.title or source.google_doc_id] = f"failed: {e}"
    db.flush()
    return results
