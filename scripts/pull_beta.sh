#!/bin/sh
# Copy beta's data into a local database (askdnd_beta) from the newest nightly backup in S3, for testing on real
# data. Beta itself is never touched: the backup is downloaded with the backup service's key, which Railway lends
# to that one command. The copy stays on this Mac (private/ is never committed). Stop the local server first.
#
#   scripts/pull_beta.sh
#
# Then the local app uses it when .env has DATABASE_URL=postgresql+psycopg://localhost/askdnd_beta. Running it again
# replaces the copy with the newest backup (local changes are lost; beta has the real ones anyway).
set -e
cd "$(dirname "$0")/.."
DB=askdnd_beta
URL=postgresql+psycopg://localhost/$DB

FILE=$(railway run --service askdnd-backup -- uv run python scripts/fetch_backup.py)
VERSION=$(uv run python -c "import gzip, json, sys; print(json.loads(gzip.decompress(open(sys.argv[1], 'rb').read()))['alembic'])" "$FILE")

dropdb --if-exists --force "$DB"
createdb "$DB"
# Build the tables as they were when the backup was made, load it, then bring it up to today's version, so any
# data changes since then run on it too.
DATABASE_URL=$URL uv run alembic upgrade "$VERSION"
uv run python scripts/restore_db.py --into "$URL" --file "$FILE"
DATABASE_URL=$URL uv run alembic upgrade head
echo "Local copy of beta ready in $DB (from $(basename "$FILE"))."
