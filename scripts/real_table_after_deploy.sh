#!/bin/bash
# The quick check after each deploy (docs/live-test-plan.md › After each deploy): launchd runs this on the Mac Mini every
# 5 minutes (scripts/ai.askdnd.after-deploy.plist). When beta's version (/health) has changed since the last check, it
# opens the test seats, runs four short runs of the live test against beta and closes them; a miss goes to Sentry
# ("Live test after deploying …"), so a deploy that breaks the table is known within minutes, not at 4:00.
# It shares the seats with the nightly (real_table_nightly.sh) through logs/.seats-busy: whichever comes second waits
# (the nightly) or tries again in 5 minutes (this).
T=$HOME/askdnd-tests
cd "$T" || exit 1
set -a; [ -f "$T/.env" ] && . "$T/.env"; set +a
mkdir -p "$T/logs"
RUNS=(closed-sheet hit-points condition cast)
now=$(curl -s -m 15 -A askdnd-live-test https://beta.askdnd.ai/health | .venv/bin/python -c 'import json, sys; print(json.load(sys.stdin).get("version", ""))' 2>/dev/null)
[ -n "$now" ] && [ "$now" != local ] || exit 0  # (beta down or restarting: the next check sees it)
last=$(cat "$T/logs/after-deploy-version" 2>/dev/null)
[ "$now" = "$last" ] && exit 0
if [ -z "$last" ]; then echo "$now" > "$T/logs/after-deploy-version"; exit 0; fi  # (the first time: only remembered)
# The seats are free? (a lock left by a run that died over two hours ago is dropped)
find "$T/logs" -maxdepth 1 -name .seats-busy -mmin +120 -exec rmdir {} \; 2>/dev/null
mkdir "$T/logs/.seats-busy" 2>/dev/null || exit 0
trap 'rmdir "$T/logs/.seats-busy"' EXIT
{
  echo "#### after deploying $now, $(date)"
  ./real_table_seats.sh open; sleep 10
  .venv/bin/python real_table.py --sentry --after-deploy="$now" "${RUNS[@]}"
  status=$?
  ./real_table_seats.sh close
  echo "#### exit $status $(date)"
} >> "$T/logs/after-deploy-$(date +%F).log" 2>&1
echo "$now" > "$T/logs/after-deploy-version"
