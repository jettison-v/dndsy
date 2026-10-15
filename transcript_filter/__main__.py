"""Filter a MacWhisper transcript locally.

    uv run python -m transcript_filter transcripts/raw/2026-08-29.json
    uv run python -m transcript_filter transcripts/raw/2026-08-29.json --model gemma4:12b

Prints only statistics, never transcript text.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from transcript_filter import ollama
from transcript_filter.cache import Cache
from transcript_filter.classify import classify
from transcript_filter.dedup import remove_echo
from transcript_filter.report import stats, write_filtered, write_review
from transcript_filter.segments import load_macwhisper

DEFAULT_MODEL = "qwen3:30b-instruct"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=Path("transcripts"))
    parser.add_argument("--echo-only", action="store_true", help="skip the Ollama step")
    args = parser.parse_args()

    if not args.echo_only and args.model not in ollama.installed_models():
        print(f"Model {args.model} isn't installed in Ollama. Run: ollama pull {args.model}", file=sys.stderr)
        return 1

    segments = load_macwhisper(args.input)
    echo = remove_echo(segments)
    print(f"echo: removed {echo} of {len(segments)} segments", flush=True)

    model_label = "echo only" if args.echo_only else args.model
    started = time.monotonic()
    if not args.echo_only:
        cache = Cache(args.out / ".cache" / f"{args.model.replace(':', '-')}.json")

        def ask(system, user, schema):
            key = cache.key(system, user)
            if key not in cache:
                cache[key] = ollama.chat_json(args.model, system, user, schema)
            return cache[key]

        progress = lambda done, total: print(f"  block {done}/{total} ({time.monotonic() - started:.0f}s)", flush=True)  # noqa: E731
        classify(segments, ask, progress)

    name = args.input.stem
    tag = model_label.replace(":", "-").replace(" ", "-")
    (args.out / "filtered").mkdir(parents=True, exist_ok=True)
    (args.out / "review").mkdir(parents=True, exist_ok=True)
    write_filtered(segments, args.out / "filtered" / f"{name}.{tag}.json", args.out / "filtered" / f"{name}.{tag}.txt")
    review = args.out / "review" / f"{name}.{tag}.html"
    write_review(segments, review, name, model_label)

    unchecked = sum(1 for s in segments if s.extra.get("unchecked"))
    result = stats(segments) | {"segments_unchecked": unchecked} | {"model": model_label, "seconds": round(time.monotonic() - started)}
    (args.out / "review" / f"{name}.{tag}.stats.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    print(f"review page: {review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
