"""Load MacWhisper "Segments" JSON exports."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    index: int  # position in the original export
    start: float  # seconds
    end: float
    speaker: str | None
    text: str
    removed_by: str | None = None  # None (kept), "echo" or "off_topic"
    reason: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def kept(self) -> bool:
        return self.removed_by is None

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_time(value: str) -> float:
    """'SS.mmm', 'MM:SS.mmm' or 'HH:MM:SS.mmm' -> seconds."""
    seconds = 0.0
    for part in value.strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def parse_range(value: str) -> tuple[float, float]:
    start, end = value.split("-", 1)
    return parse_time(start), parse_time(end)


def format_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def load_macwhisper(path: Path) -> list[Segment]:
    raw = json.loads(Path(path).read_text())
    segments = []
    for i, item in enumerate(raw):
        start, end = parse_range(item["timestamp"])
        segments.append(
            Segment(
                index=i,
                start=start,
                end=end,
                speaker=item.get("speaker") or None,
                text=(item.get("text") or "").strip(),
            )
        )
    segments.sort(key=lambda s: (s.start, s.index))
    return segments
