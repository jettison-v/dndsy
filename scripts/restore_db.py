"""Restore an askdnd backup into an EMPTY database (never on top of live data).

    # 1. make an empty database and build its tables
    createdb askdnd_restore
    DATABASE_URL=postgresql+psycopg://localhost/askdnd_restore uv run alembic upgrade head
    # 2. load the backup (a local file, or a key in the S3 bucket)
    uv run python scripts/restore_db.py --into postgresql+psycopg://localhost/askdnd_restore --file private/backups/x.json.gz
    uv run python scripts/restore_db.py --into ... --s3-key v2/backups/askdnd-2026-10-20.json.gz

Restoring into beta itself is a big step: do it only after talking it through.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402

from app import backup  # noqa: E402


def arg(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main() -> None:
    into = arg("--into")
    if not into:
        sys.exit("Say which database to restore into with --into (it must be empty).")
    if "railway" in into and "--yes-this-is-beta" not in sys.argv:
        sys.exit("That looks like the Railway database. Add --yes-this-is-beta only if you really mean it.")
    if arg("--file"):
        raw = Path(arg("--file")).read_bytes()
    elif arg("--s3-key"):
        import boto3

        raw = boto3.client("s3").get_object(Bucket=os.environ["AWS_S3_BUCKET_NAME"], Key=arg("--s3-key"))["Body"].read()
    else:
        sys.exit("Give --file or --s3-key.")
    data = backup.from_bytes(raw)
    with create_engine(into).begin() as conn:
        counts = backup.load(conn, data)
    print(f"Restored backup from {data['made_at']} (database version {data['alembic']}): {sum(counts.values()):,} rows")


if __name__ == "__main__":
    main()
