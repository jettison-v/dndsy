#!/bin/bash
# The Mac Mini's test seats for scripts/real_table.py (docs/testing-setup.md): real Chrome, reachable only from the Mini.
#   real_table_seats.sh copy    copies each seat's Chrome profile (Brett's sign-ins and the bridge) into ~/askdnd-tests/seats
#   real_table_seats.sh open    opens every seat that isn't open, and waits until each answers
#   real_table_seats.sh close   closes every seat
# Chrome won't let a script drive its normal profile folder, hence the copies. Brett's own profile is never a seat.
T=$HOME/askdnd-tests
C="$HOME/Library/Application Support/Google/Chrome"
PROFILES=("dm:Profile 1" "player2:Default" "player3:Profile 4")  # (the Mini's Jettison, Cupta Family and Trent profiles)

port() { case "$1" in dm) echo 9231;; player2) echo 9232;; player3) echo 9233;; esac; }
up() { curl -s -m 2 "http://127.0.0.1:$(port "$1")/json/version" >/dev/null; }

case "$1" in
  copy)
    pkill -TERM -f 'user-data-dir=.*/askdnd-tests/seats/'; sleep 2
    for p in "${PROFILES[@]}"; do
      seat=${p%%:*}; mkdir -p "$T/seats/$seat"
      # (keep Service Worker: the bridge's own code runs from it. Only page caches are left out.)
      rsync -a --delete --exclude Cache --exclude 'Code Cache' --exclude GPUCache --exclude DawnGraphiteCache --exclude DawnWebGPUCache \
        "$C/${p#*:}/" "$T/seats/$seat/Default/"
    done ;;
  open)  # (only the seats that aren't open already, then waits until each answers)
    for p in "${PROFILES[@]}"; do
      seat=${p%%:*}
      up "$seat" && continue
      open -na "Google Chrome" --args --user-data-dir="$T/seats/$seat" --profile-directory=Default --remote-debugging-port="$(port "$seat")" \
        --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check about:blank
    done
    for p in "${PROFILES[@]}"; do
      seat=${p%%:*}
      for _ in $(seq 60); do up "$seat" && break; sleep 1; done
      up "$seat" || { echo "$seat didn't open"; exit 1; }
    done ;;
  close) pkill -TERM -f 'user-data-dir=.*/askdnd-tests/seats/' ;;
  *) echo "copy, open or close"; exit 1 ;;
esac
