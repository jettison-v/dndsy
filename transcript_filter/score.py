"""Score a filter run against hand labels (transcripts/gold/<name>.json).

    uv run python -m transcript_filter.score transcripts/raw/2026-08-29.json <filtered.json> [...]

Prints only numbers.
"""

import json
import sys
from pathlib import Path

from transcript_filter.dedup import remove_echo
from transcript_filter.segments import load_macwhisper


def gold_label(t: float, ranges) -> str | None:
    for start, end, label in ranges:
        if start <= t <= end:
            return label
    return None


def score(raw: Path, filtered: Path, gold: dict) -> dict:
    segments = load_macwhisper(raw)
    remove_echo(segments)
    kept = {(round(k["start"], 3), k["text"]) for k in json.loads(filtered.read_text())}
    counts = {"game_kept": 0, "game_cut": 0, "talk_kept": 0, "talk_cut": 0}
    for s in segments:
        label = gold_label(s.start, gold["ranges"])
        if not s.kept or label is None:
            continue
        was_kept = (round(s.start, 3), s.text) in kept
        key = ("game" if label == "game" else "talk") + ("_kept" if was_kept else "_cut")
        counts[key] += s.words
    game = counts["game_kept"] + counts["game_cut"]
    talk = counts["talk_kept"] + counts["talk_cut"]
    return counts | {
        "game_words_lost_pct": round(100 * counts["game_cut"] / game, 1) if game else 0,
        "table_talk_removed_pct": round(100 * counts["talk_cut"] / talk, 1) if talk else 0,
    }


if __name__ == "__main__":
    raw = Path(sys.argv[1])
    gold = json.loads((Path("transcripts/gold") / f"{raw.stem}.json").read_text())
    for f in sys.argv[2:]:
        print(Path(f).name, json.dumps(score(raw, Path(f), gold)))
