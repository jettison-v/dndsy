"""Remove Zoom echo: the same words transcribed twice with overlapping times.

The echo copy usually has a different (or no) speaker label and may be split
into fragments, e.g. "Wages, medical" + "All that stuff, right?" alongside
"Wages, medical, all that stuff, right?". We keep the longest version and drop
segments whose words are (almost) all contained in a nearby, longer segment.

The echo copy is often transcribed slightly differently ("85% chance on those"
vs "it's a 85% chance on those"), so a long same-order run of words also counts.
Genuine replies share words too ("Is that an evocation?" / "It's an evocation
spell.") but rarely a long run in the same order.
"""

import re
from collections import Counter
from difflib import SequenceMatcher

from transcript_filter.segments import Segment

WINDOW_SECONDS = 4.0  # how far apart two copies can start
TIME_SLACK = 1.5  # tolerated gap between time ranges to count as overlapping
MIN_CONTAINED = 0.8  # share of a fragment's words found in the longer segment
MIN_RUN = 4  # same-order identical words that mark a reworded echo...
MIN_RUN_SHARE = 0.5  # ...when they cover this share of the shorter segment

_WORD = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def containment(small: list[str], big: list[str]) -> float:
    """Share of `small`'s words (with repeats) that also appear in `big`."""
    if not small:
        return 1.0
    big_counts = Counter(big)
    hits = 0
    for word, n in Counter(small).items():
        hits += min(n, big_counts.get(word, 0))
    return hits / len(small)


def longest_run(small: list[str], big: list[str]) -> int:
    """Length of the longest run of identical words, in the same order."""
    return SequenceMatcher(None, small, big, autojunk=False).find_longest_match().size


def overlaps(a: Segment, b: Segment, slack: float = TIME_SLACK) -> bool:
    return a.start <= b.end + slack and b.start <= a.end + slack


def is_echo_of(small: Segment, big: Segment) -> bool:
    small_t, big_t = tokens(small.text), tokens(big.text)
    if len(small_t) > len(big_t):
        return False
    if not overlaps(small, big):
        return False
    if containment(small_t, big_t) >= MIN_CONTAINED:
        return True
    run = longest_run(small_t, big_t)
    return run >= MIN_RUN and run >= MIN_RUN_SHARE * len(small_t)


def remove_echo(segments: list[Segment]) -> int:
    """Mark echo duplicates in place (sorted by start). Returns how many."""
    removed = 0
    n = len(segments)
    for i, seg in enumerate(segments):
        if not seg.kept or not tokens(seg.text):
            continue
        j = i - 1
        candidates = []
        while j >= 0 and seg.start - segments[j].start <= WINDOW_SECONDS:
            candidates.append(segments[j])
            j -= 1
        j = i + 1
        while j < n and segments[j].start - seg.start <= WINDOW_SECONDS:
            candidates.append(segments[j])
            j += 1
        for other in candidates:
            if not other.kept or other is seg:
                continue
            seg_len, other_len = len(tokens(seg.text)), len(tokens(other.text))
            # Drop the shorter copy; on a tie drop the later one in the export.
            if (seg_len, -seg.index) < (other_len, -other.index) and is_echo_of(seg, other):
                seg.removed_by = "echo"
                seg.reason = f"echo of line {other.index}"
                removed += 1
                break
    return removed
