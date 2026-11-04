#!/bin/bash
# The nightly canary (docs/live-test-plan.md › Every night): launchd runs this on the Mac Mini at 4:00
# (scripts/ai.askdnd.live-test.plist). It opens the test seats, runs part 1 of the live test against beta (then again
# through the DM, --via-dm), and closes
# them. A miss, or seats that won't open, goes to Sentry (askdnd-v2), which alerts Brett like the app's own errors.
# SENTRY_DSN is in ~/askdnd-tests/.env on the Mini only (scripts/set-secret.sh SENTRY_DSN --mini), never in git.
#   real_table_nightly.sh              the nightly run
#   real_table_nightly.sh --try-alert  the same, plus one deliberate miss: checks the way to Sentry
T=$HOME/askdnd-tests
cd "$T" || exit 1
set -a; [ -f "$T/.env" ] && . "$T/.env"; set +a
mkdir -p "$T/logs"
log="$T/logs/nightly-$(date +%F).log"
{
  echo "#### $(date)"
  ./real_table_seats.sh close; sleep 3
  ./real_table_seats.sh open; sleep 10  # (if a seat won't open, the run below says so and reports it)
  .venv/bin/python real_table.py --sentry "$@"
  status=$?
  # The same changes through the DM (every sheet closed, the DM's seat on the campaign page): Manage › askdnd › D&D
  # Beyond bridge's table says what each connection can change, and this keeps it true (Brett, 2026-11-04)
  .venv/bin/python real_table.py --sentry --via-dm "$@" || status=1
  ./real_table_seats.sh close
  echo "#### exit $status $(date)"
} >> "$log" 2>&1
exit $status
