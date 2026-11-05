"""How the live test has gone, night by night (docs/live-test-plan.md › Every night).

    uv run python scripts/live_results.py              # the last 14 nights, read from the Mac Mini
    uv run python scripts/live_results.py --nights 30
    uv run python scripts/live_results.py --file results.jsonl   # a copy on this computer

real_table.py adds a line to ~/askdnd-tests/logs/results.jsonl on the Mini after every part 1 (and every run through
the DM): each check with its run, whether it passed and how long it took. This lists, worst first, every check that
didn't pass every time (missed, or passed only on a second try), and the checks getting slower, so a check that fails
one night in five shows up before anyone has to remember it did.
"""

import argparse
import json
import statistics
import subprocess
from collections import defaultdict


def lines(path: str | None) -> list[dict]:
    if path:
        text = open(path).read()
    else:
        text = subprocess.run(["ssh", "mac-mini-server", "cat askdnd-tests/logs/results.jsonl"], capture_output=True, text=True, check=True).stdout
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nights", type=int, default=14)
    p.add_argument("--file")
    args = p.parse_args()
    nights = lines(args.file)
    days = sorted({n["at"][:10] for n in nights})[-args.nights:]
    nights = [n for n in nights if n["at"][:10] in days]
    print(f"{len(nights)} runs of part 1 over {len(days)} days ({days[0] if days else '-'} to {days[-1] if days else '-'})")
    seen = defaultdict(lambda: {"ok": 0, "missed": 0, "again": 0, "seconds": []})
    for n in nights:
        how = " (through the DM)" if n.get("via_dm") else ""
        for c in n["checks"]:
            run = c["run"].removesuffix(" (again)")
            key = f"{run}: {c['what']}{how}" if run else c["what"] + how
            row = seen[key]
            if c["run"].endswith(" (again)"):
                row["again"] += 1 if c["ok"] else 0
                continue
            row["ok" if c["ok"] else "missed"] += 1
            if c["ok"] and c.get("seconds") is not None:
                row["seconds"].append((n["at"], c["seconds"]))
    shaky = sorted(((r["missed"] / (r["ok"] + r["missed"]), k, r) for k, r in seen.items() if r["missed"]), reverse=True)
    print("\nDidn't pass every time (first try):" if shaky else "\nEvery check passed on its first try.")
    for share, k, r in shaky:
        print(f"  {r['missed']} of {r['ok'] + r['missed']} missed, {r['again']} passed on a second try   {k}")
    slower = []
    for k, r in seen.items():
        s = [x for _, x in sorted(r["seconds"])]
        if len(s) >= 4:
            early, late = statistics.median(s[: len(s) // 2]), statistics.median(s[len(s) // 2:])
            if late > 10 and late > early * 1.5:
                slower.append((late - early, k, early, late))
    if slower:
        print("\nGetting slower (median seconds, earlier half of the nights to later):")
        for _, k, early, late in sorted(slower, reverse=True):
            print(f"  {early:.0f} → {late:.0f}   {k}")


if __name__ == "__main__":
    main()
