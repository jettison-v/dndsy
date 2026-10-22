"""Download the newest nightly backup from S3 (v2/backups/) into private/backups/, for a local copy of beta.

Run it with the backup service's S3 key, which Railway lends to this one command (never printed or saved):
    railway run --service askdnd-backup -- uv run python scripts/fetch_backup.py
Prints the saved file's path. Reads S3 only; never touches a database. scripts/pull_beta.sh runs it for you.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup  # noqa: E402


def main() -> None:
    import boto3

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    bucket = os.environ["AWS_S3_BUCKET_NAME"]
    found = s3.list_objects_v2(Bucket=bucket, Prefix=backup.PREFIX).get("Contents", [])
    found = [o for o in found if o["Key"].endswith(".json.gz")]
    if not found:
        sys.exit("No backups in S3 yet.")
    newest = max(found, key=lambda o: o["LastModified"])
    out = Path(__file__).resolve().parent.parent / "private" / "backups" / newest["Key"].rsplit("/", 1)[-1]
    out.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, newest["Key"], str(out))
    print(f"{out} ({newest['Size']:,} bytes, made {newest['LastModified']:%Y-%m-%d %H:%M} UTC)", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
