"""Restore an askdnd backup into an EMPTY database (never on top of live data).

    # 1. make an empty database and build its tables
    createdb askdnd_restore
    DATABASE_URL=postgresql+psycopg://localhost/askdnd_restore uv run alembic upgrade head
    # 2. load the backup (a local file, or a key in the S3 bucket)
    uv run python scripts/restore_db.py --into postgresql+psycopg://localhost/askdnd_restore --file private/backups/x.json.gz
    uv run python scripts/restore_db.py --into ... --s3-key v2/backups/askdnd-2026-10-20.json.gz

Restoring into beta itself is a big step: do it only after talking it through.

Staging (docs/SETUP_LOG.md › Staging) has no public database address, so its copy of beta is loaded from inside its
own server, where only it runs:
    railway ssh --service askdnd-staging --environment staging -- python scripts/restore_db.py --into-staging --file /tmp/x.json.gz
--into-staging restores into that server's own database, and only when Railway says the server is staging's.

Refreshing staging from prod (scripts/refresh_staging.sh; Brett, Nov 6): --fresh empties staging's database first,
builds its tables as they were when the backup was made, loads it, then brings it up to today's version (as
scripts/pull_beta.sh does locally); --url fetches the backup from a short-lived link (fetch_backup.py --link).
--fresh works only with --into-staging.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402

from app import backup  # noqa: E402


def arg(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def alembic(url: str, version: str) -> None:
    import subprocess

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", version], check=True, env={**os.environ, "DATABASE_URL": url},
                   cwd=Path(__file__).resolve().parent.parent)


def empty(url: str, version: str) -> None:
    """Staging's database emptied and its tables built as they were at `version` (the backup's)."""
    from sqlalchemy import text

    with create_engine(url).begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    alembic(url, version)


def main() -> None:
    into = arg("--into")
    if "--into-staging" in sys.argv:
        if os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "staging":
            sys.exit("--into-staging runs only on staging's own server (railway ssh --environment staging).")
        from app import config

        into = config.DATABASE_URL
    elif into and "railway" in into and "--yes-this-is-beta" not in sys.argv:
        sys.exit("That looks like the Railway database. Add --yes-this-is-beta only if you really mean it.")
    if not into:
        sys.exit("Say which database to restore into with --into (it must be empty).")
    fresh = "--fresh" in sys.argv
    if fresh and "--into-staging" not in sys.argv:
        sys.exit("--fresh empties the database first, so it runs only with --into-staging.")
    if arg("--file"):
        raw = Path(arg("--file")).read_bytes()
    elif arg("--url"):
        import urllib.request

        with urllib.request.urlopen(arg("--url"), timeout=300) as r:
            raw = r.read()
    elif arg("--s3-key"):
        import boto3

        raw = boto3.client("s3").get_object(Bucket=os.environ["AWS_S3_BUCKET_NAME"], Key=arg("--s3-key"))["Body"].read()
    else:
        sys.exit("Give --file, --url or --s3-key.")
    data = backup.from_bytes(raw)
    if fresh:
        empty(into, data["alembic"])
    with create_engine(into).begin() as conn:
        counts = backup.load(conn, data)
    if fresh:
        alembic(into, "head")
    print(f"Restored backup from {data['made_at']} (database version {data['alembic']}): {sum(counts.values()):,} rows")
    if listed := data["tables"].get("stored_files"):
        print(f"It lists {len(listed):,} files (pictures and the like). They aren't in the backup: they stay in file storage "
              "(S3 v2/files/), which keeps every file a kept backup names. For a local database, scripts/fetch_files.py "
              "copies them into private/files/.")


if __name__ == "__main__":
    main()
