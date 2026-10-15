"""Filter a MacWhisper transcript locally.

    uv run python -m transcript_filter transcripts/raw/2026-08-29.json
    uv run python -m transcript_filter transcripts/raw/2026-08-29.json --model qwen3:30b-instruct

Prints only statistics, never transcript text.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from transcript_filter.pipeline import DEFAULT_MODEL, PipelineError, run
from transcript_filter.report import write_filtered, write_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=Path("transcripts"))
    parser.add_argument(
        "--context",
        type=Path,
        default=Path("transcripts/context.md"),
        help="private campaign notes for the model (used if the file exists)",
    )
    parser.add_argument("--minutes", type=float, help="only process the first N minutes (for testing)")
    parser.add_argument("--echo-only", action="store_true", help="skip the Ollama step")
    args = parser.parse_args()

    started = time.monotonic()

    def progress(done, total):
        print(f"  block {done}/{total} ({time.monotonic() - started:.0f}s)", flush=True)

    try:
        segments, result = run(args.input, args.model, args.out, args.context, progress, args.minutes, args.echo_only)
    except PipelineError as e:
        print(e, file=sys.stderr)
        return 1

    name = args.input.stem
    tag = result["model"].replace(":", "-").replace(" ", "-") + (f".first{args.minutes:g}m" if args.minutes else "")
    (args.out / "filtered").mkdir(parents=True, exist_ok=True)
    (args.out / "review").mkdir(parents=True, exist_ok=True)
    write_filtered(segments, args.out / "filtered" / f"{name}.{tag}.json", args.out / "filtered" / f"{name}.{tag}.txt")
    review = args.out / "review" / f"{name}.{tag}.html"
    write_review(segments, review, name, result["model"])
    (args.out / "review" / f"{name}.{tag}.stats.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    print(f"review page: {review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
