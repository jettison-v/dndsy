"""Whole-database backups: every table's rows in one gzipped JSON file.

Nightly, scripts/backup_db.py uploads one to S3 under v2/backups/ (never anywhere
else in the bucket, which the legacy app also uses) and keeps the last 30 days.
scripts/restore_db.py loads one into an empty database built with
`alembic upgrade` (to head, or to the backup's own version and then head).

The database never holds raw transcripts (CLAUDE.md), so backups don't either.
They do hold players' notes and the campaign record, so the bucket stays private.
"""

import base64
import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Connection, MetaData, insert, inspect, text

import app.models  # noqa: F401  (registers every table)
from app.db import Base

PREFIX = "v2/backups/"
KEEP_DAYS = 30
FORMAT = 1


def _json(v):
    if isinstance(v, (datetime, date)):
        return {"$dt": v.isoformat()}
    if isinstance(v, (bytes, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, Decimal):
        return float(v)
    return v


def _back(v, column):
    if isinstance(v, dict) and set(v) == {"$dt"}:
        return datetime.fromisoformat(v["$dt"]) if "T" in v["$dt"] else date.fromisoformat(v["$dt"])
    if isinstance(v, dict) and set(v) == {"$b64"}:
        return base64.b64decode(v["$b64"])
    return v


def tables(metadata: MetaData | None = None):
    return (metadata or Base.metadata).sorted_tables  # parents before children


def dump(conn: Connection) -> dict:
    """Every row of every table, plus the database version (alembic)."""
    version = None
    if inspect(conn).has_table("alembic_version"):  # tests build the schema without alembic
        version = conn.execute(text("select version_num from alembic_version")).scalar()
    data = {"format": FORMAT, "made_at": datetime.now(UTC).isoformat(), "alembic": version, "tables": {}}
    for t in tables():
        rows = conn.execute(t.select().order_by(*t.primary_key.columns)).mappings()
        data["tables"][t.name] = [{k: _json(v) for k, v in r.items()} for r in rows]
    return data


def to_bytes(data: dict) -> bytes:
    return gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def from_bytes(raw: bytes) -> dict:
    data = json.loads(gzip.decompress(raw))
    if data.get("format") != FORMAT:
        raise ValueError("Not an askdnd backup (or a newer format).")
    return data


def load(conn: Connection, data: dict) -> dict[str, int]:
    """Insert a backup into a database whose tables are empty. Returns rows per table.

    The database may be built at the backup's own (older) version, `alembic upgrade <data["alembic"]>`, and
    upgraded to head afterwards, so data changes in later migrations run too (scripts/pull_beta.sh does this).
    So the tables as they are in the database are used, not as they are in today's code."""
    live = MetaData()
    live.reflect(conn)
    order = [live.tables[t.name] for t in tables() if t.name in live.tables]
    counts = {}
    for t in order:
        if conn.execute(t.select().limit(1)).first() is not None:
            raise ValueError(f"Table {t.name} isn't empty: restore into a fresh database.")
    for t in order:
        rows = data["tables"].get(t.name) or []
        if rows:
            cols = {c.name: c for c in t.columns}
            conn.execute(insert(t), [{k: _back(v, cols.get(k)) for k, v in r.items() if k in cols} for r in rows])
        counts[t.name] = len(rows)
        pk = list(t.primary_key.columns)
        if len(pk) == 1 and pk[0].autoincrement and rows and conn.dialect.name == "postgresql":
            conn.execute(text(f"select setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                              f"coalesce((select max({pk[0].name}) from {t.name}), 1))"))
    return counts


def key_for(day: date) -> str:
    return f"{PREFIX}askdnd-{day.isoformat()}.json.gz"


def old_keys(keys: list[str], today: date) -> list[str]:
    """Backups older than KEEP_DAYS, only ever inside v2/backups/."""
    out = []
    for k in keys:
        if not k.startswith(PREFIX) or not k.endswith(".json.gz"):
            continue
        try:
            day = date.fromisoformat(k.removeprefix(PREFIX + "askdnd-").removesuffix(".json.gz"))
        except ValueError:
            continue
        if (today - day).days > KEEP_DAYS:
            out.append(k)
    return out
