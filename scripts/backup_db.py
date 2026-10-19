"""Back up the whole askdnd database to S3 (v2/backups/), keeping 30 days.

Runs nightly on Railway (the "backup" service, see docs/SETUP_LOG.md). Needs:
DATABASE_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET_NAME,
AWS_REGION (optional). With --out it writes a local file instead of uploading:

    uv run python scripts/backup_db.py --out private/backups/test.json.gz
"""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402

from app import backup  # noqa: E402


def engine_url() -> str:
    from app import config

    return config.DATABASE_URL  # DATABASE_URL on Railway; the local database otherwise


def record(engine, started, status: str, detail: str) -> None:
    """Note the run in the database, for the Manage overview (it says when backups last worked)."""
    from app.models import JobRun

    try:
        with engine.begin() as conn:
            conn.execute(JobRun.__table__.insert().values(name="backup", status=status, detail=detail[:2000], started_at=started))
    except Exception as e:  # noqa: BLE001 - the backup itself matters more than the note
        print(f"Couldn't record the run: {e}")


def main() -> None:
    engine = create_engine(engine_url())
    started = datetime.now(UTC)
    try:
        detail = run(engine)
    except Exception as e:
        record(engine, started, "error", f"{type(e).__name__}: {e}")
        raise
    if "--out" not in sys.argv:
        record(engine, started, "ok", detail)


def run(engine) -> str:
    with engine.connect() as conn:
        data = backup.dump(conn)
    raw = backup.to_bytes(data)
    rows = sum(len(v) for v in data["tables"].values())
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
        print(f"Wrote {out} ({len(raw):,} bytes, {rows:,} rows)")
        return str(out)
    import boto3

    bucket = os.environ["AWS_S3_BUCKET_NAME"]
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION") or None)
    today = datetime.now(UTC).date()
    key = backup.key_for(today)
    assert key.startswith(backup.PREFIX)
    s3.put_object(Bucket=bucket, Key=key, Body=raw, ContentType="application/gzip", ServerSideEncryption="AES256")
    print(f"Uploaded s3://{bucket}/{key} ({len(raw):,} bytes, {rows:,} rows)")
    listed = s3.list_objects_v2(Bucket=bucket, Prefix=backup.PREFIX).get("Contents") or []
    for old in backup.old_keys([o["Key"] for o in listed], today):
        s3.delete_object(Bucket=bucket, Key=old)
        print(f"Removed old backup {old}")
    return f"{key} · {len(raw) / 1e6:.1f} MB · {rows:,} rows"


if __name__ == "__main__":
    main()
