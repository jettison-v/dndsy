"""The filter pipeline, shared by the command line and the processor GUI."""

import json
import time
from collections.abc import Callable
from pathlib import Path

from transcript_filter import ollama
from transcript_filter.cache import Cache
from transcript_filter.classify import classify
from transcript_filter.dedup import remove_echo
from transcript_filter.report import stats
from transcript_filter.segments import Segment, load_macwhisper

DEFAULT_MODEL = "gemma4:12b"


class PipelineError(RuntimeError):
    pass


def run(
    raw_path: Path,
    model: str = DEFAULT_MODEL,
    out_dir: Path = Path("transcripts"),
    context_path: Path = Path("transcripts/context.md"),
    progress: Callable[[int, int], None] = lambda done, total: None,
    minutes: float | None = None,
    echo_only: bool = False,
) -> tuple[list[Segment], dict]:
    """De-dup echo, then (unless echo_only) label table talk with the local model."""
    if not echo_only and model not in ollama.installed_models():
        raise PipelineError(f"Model {model} isn't installed in Ollama. Run: ollama pull {model}")
    segments = load_macwhisper(raw_path)
    if minutes:
        segments = [s for s in segments if s.start < minutes * 60]
    remove_echo(segments)
    started = time.monotonic()
    if not echo_only:
        cache = Cache(out_dir / ".cache" / f"{model.replace(':', '-')}.json")

        def ask(system, user, schema):
            key = cache.key(system, user)
            if key not in cache:
                cache[key] = ollama.chat_json(model, system, user, schema)
            return cache[key]

        campaign = context_path.read_text() if context_path.exists() else ""
        classify(segments, ask, progress, campaign)
    unchecked = sum(1 for s in segments if s.extra.get("unchecked"))
    result = stats(segments) | {
        "segments_unchecked": unchecked,
        "model": "echo only" if echo_only else model,
        "seconds": round(time.monotonic() - started),
    }
    return segments, result


def save_state(segments: list[Segment], path: Path) -> None:
    """Every segment with its filter decision, for the review screen.
    `keep` is Brett's override: True restores a stretch the model cut."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "i": s.index,
            "start": s.start,
            "end": s.end,
            "speaker": s.speaker,
            "text": s.text,
            "removed_by": s.removed_by,
            "reason": s.reason,
            "unchecked": bool(s.extra.get("unchecked")),
            "keep": bool(s.extra.get("keep")),
        }
        for s in segments
    ]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.replace(path)


def load_state(path: Path) -> list[Segment]:
    segments = []
    for r in json.loads(path.read_text()):
        seg = Segment(r["i"], r["start"], r["end"], r["speaker"], r["text"], r["removed_by"], r.get("reason", ""))
        seg.extra["unchecked"] = r.get("unchecked", False)
        seg.extra["keep"] = r.get("keep", False)
        segments.append(seg)
    return segments


def is_final_kept(seg: Segment) -> bool:
    if seg.removed_by == "echo":
        return False
    return seg.removed_by is None or bool(seg.extra.get("keep"))


def cut_stretches(segments: list[Segment]) -> list[list[Segment]]:
    """Runs of model-cut lines (echo lines in between don't break a run)."""
    runs: list[list[Segment]] = []
    current: list[Segment] = []
    for seg in segments:
        if seg.removed_by == "echo":
            continue
        if seg.removed_by == "off_topic":
            current.append(seg)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs
