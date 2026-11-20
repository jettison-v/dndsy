#!/bin/bash
# The nightly canary (docs/live-test-plan.md › Every night): launchd runs this on the Mac Mini at 4:00
# (scripts/ai.askdnd.live-test.plist). It opens the test seats, runs part 1 of the live test against beta (then again
# through the DM, --via-dm), and closes
# them, then checks the seats' pages in real iPhone and iPad Safari. A miss, or seats that won't open, goes to Sentry (askdnd-v2), which alerts Brett like the app's own errors.
# SENTRY_DSN is in ~/askdnd-tests/.env on the Mini only (scripts/set-secret.sh SENTRY_DSN --mini), never in git.
#   real_table_nightly.sh              the nightly run
#   real_table_nightly.sh --try-alert  the same, plus one deliberate miss: checks the way to Sentry
T=$HOME/askdnd-tests
cd "$T" || exit 1
set -a; [ -f "$T/.env" ] && . "$T/.env"; set +a
mkdir -p "$T/logs"
# Each run reports to Work › Scheduled on askdnd.ai (The Work Pages, Nov 20; app/data/jobs.json): ok or failed, a line of
# what happened. FFT_MINI_KEY (the Mini's own key, in ~/askdnd-tests/.env) may report only the Mini's jobs.
report() {
  [ -n "$FFT_MINI_KEY" ] || return 0
  curl -s -m 20 -o /dev/null -X POST "https://askdnd.ai/api/fft/jobs/$1" -H "X-Fft-Key: $FFT_MINI_KEY" \
    -H "Content-Type: application/json" -H "User-Agent: askdnd-mini" -d "{\"result\": \"$2\", \"words\": \"$3\"}" || true
}
log="$T/logs/nightly-$(date +%F).log"
# The seats are the after-deploy check's too (real_table_after_deploy.sh): wait for it, up to 20 minutes (a lock left by
# a run that died over two hours ago is dropped)
find "$T/logs" -maxdepth 1 -name .seats-busy -mmin +120 -exec rmdir {} \; 2>/dev/null
for _ in $(seq 240); do mkdir "$T/logs/.seats-busy" 2>/dev/null && { trap 'rmdir "$T/logs/.seats-busy" 2>/dev/null' EXIT; break; }; sleep 5; done
{
  echo "#### $(date)"
  ./real_table_seats.sh close; sleep 3
  ./real_table_seats.sh open; sleep 10  # (if a seat won't open, the run below says so and reports it)
  .venv/bin/python real_table.py --sentry "$@"
  status=$?
  # The same changes through the DM (every sheet closed, the DM's seat on the campaign page): Manage › askdnd › D&D
  # Beyond bridge's table says what each connection can change, and this keeps it true (Brett, 2026-11-04)
  .venv/bin/python real_table.py --sentry --via-dm "$@" || status=1
  if [ $# -eq 0 ]; then
    if [ $status -eq 0 ]; then report nightly ok "Part 1 and through the DM passed"; else report nightly failed "A miss: see Sentry and the night's log"; fi
  fi
  # Real iPhone and iPad Safari in the iOS Simulator (docs/live-test-plan.md › iPhone Safari, Nov 8): the seats' pages,
  # read-only, its own Sentry issue. Only the plain nightly (a named run or --try-alert is about part 1)
  if [ $# -eq 0 ]; then
    if .venv/bin/python iphone_check.py --sentry; then report iphone ok "Every page held together"
    else status=1; report iphone failed "A miss: see Sentry and the night's log"; fi
  fi
  ./real_table_seats.sh close
  echo "#### exit $status $(date)"
} >> "$log" 2>&1
exit $status
