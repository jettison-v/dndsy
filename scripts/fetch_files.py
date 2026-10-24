"""Download the files a backup lists (pictures; later maps and handouts) from S3 (v2/files/) into private/files/,
for a local copy of beta. Files already there are skipped (a key's content never changes).

Run it with the backup service's S3 key, which Railway lends to this one command (never printed or saved):
    railway run --service askdnd-backup -- uv run python scripts/fetch_files.py private/backups/askdnd-….json.gz
Reads S3 only; never touches a database. scripts/pull_beta.sh runs it for you. If the key can't read v2/files/
it says so and stops without failing: pictures still have their copies in the database until VTT 0.5 removes them.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup, files  # noqa: E402


def fetch(keys: list[str], source, target: files.LocalFolder) -> int:
    have = {f.key for f in target.list()}
    got = 0
    for key in keys:
        if key not in have:
            target.put(key, source.get(key), "")
            got += 1
    return got


def main() -> None:
    from botocore.exceptions import ClientError

    data = backup.from_bytes(Path(sys.argv[1]).read_bytes())
    keys = [r["key"] for r in data["tables"].get("stored_files") or []]
    target = files.LocalFolder(files.ROOT / "private" / "files")
    try:
        got = fetch(keys, files.S3(os.environ["AWS_S3_BUCKET_NAME"], os.environ.get("AWS_REGION")), target)
    except ClientError as e:
        print(f"Couldn't download files from S3 ({e.response['Error']['Code']}); pictures will use their database copies.",
              file=sys.stderr)
        return
    print(f"Files: {len(keys):,} listed, {got:,} downloaded to {target.root}", file=sys.stderr)


if __name__ == "__main__":
    main()
