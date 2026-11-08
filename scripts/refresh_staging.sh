#!/bin/sh
# Give staging a fresh copy of prod's data (Brett, Nov 6; docs/SETUP_LOG.md › A staging copy): the newest nightly
# backup, loaded into staging's own database from inside its server. Staging's database is emptied first, so anything
# typed there since the last refresh is gone (feedback sent from staging already lives on prod). Its pictures stay
# apart (v2/staging/files/, reading prod's from v2/files/). Prod is never touched: the backup is read with the backup
# service's key, which Railway lends to one command, as a link good for 15 minutes.
#
#   scripts/refresh_staging.sh
set -e
cd "$(dirname "$0")/.."
LINK=$(railway run --service askdnd-backup --environment production -- uv run python scripts/fetch_backup.py --link)
case "$LINK" in https://*) ;; *) echo "No link to the newest backup." >&2; exit 1 ;; esac
railway ssh --service askdnd-staging --environment staging -- python scripts/restore_db.py --into-staging --fresh --url "$LINK"
echo "Staging has prod's data from the newest nightly backup."
