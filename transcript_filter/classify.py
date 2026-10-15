"""Ask a local model which stretches of a block are clearly not the game."""

from collections.abc import Callable

from transcript_filter.segments import Segment, format_time

BLOCK_LINES = 60
CONTEXT_LINES = 8

SYSTEM_PROMPT = """\
You are filtering a transcript of a Dungeons & Dragons (2024 rules) session \
played over Zoom by four players and a Dungeon Master (DM). Label every \
numbered line "game" or "table_talk" so table talk can be removed before the \
transcript is shared. Speaker labels are unreliable, and the same words can \
appear twice because of audio echo.

"game" means THIS D&D campaign only:
- the DM's narration, NPC voices, descriptions of places and events
- players talking in character, planning, deciding what to do next
- dice rolls, combat, initiative, damage, saving throws
- rules questions and debates about D&D spells, abilities and items
- players recapping earlier sessions or reviewing their characters, spells \
and inventory, including before play officially starts

"table_talk" is everything else:
- real life: work, money, family, kids, sports, news, food, health, sleep
- OTHER games and media (video games, board games, TV, YouTube), even when \
they mention castles, spells, armies, giants or dragons
- Zoom and tech: joining, "can you hear me", audio problems, screen sharing \
setup unrelated to the game, people arriving late or leaving
- breaks, scheduling the next session, goodbyes

How sessions usually go: the first 30-45 minutes is mostly catch-up while \
people join, with bursts of D&D planning mixed in. Play starts when the DM \
recaps or begins narrating. Mid-session breaks look like people leaving and \
rejoining at different times. Judge each line by its own words and its \
neighbors; short filler ("yeah", "okay", "hmm") gets the label of the lines \
around it. If a line is clearly about the D&D campaign, it is "game" even \
in the middle of table talk."""

LABELS = ("game", "table_talk")

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "label": {"type": "string", "enum": list(LABELS)},
                },
                "required": ["n", "label"],
            },
        }
    },
    "required": ["lines"],
}


def render_line(n: int, seg: Segment) -> str:
    who = seg.speaker or "Unknown"
    return f"{n}. [{format_time(seg.start)}] {who}: {seg.text}"


def build_prompt(
    context: list[Segment], block: list[Segment], first_number: int, campaign: str = ""
) -> str:
    parts = []
    if campaign:
        parts += ["Background on this table and campaign:", campaign.strip(), ""]
    if context:
        parts.append("Earlier lines, for context only (do not label these):")
        parts += [f"- {render_line(0, s)[3:]}" for s in context]
        parts.append("")
    parts.append(
        f"Lines to check (numbered {first_number}-{first_number + len(block) - 1}). "
        "Label every one of these lines."
    )
    parts += [render_line(first_number + i, s) for i, s in enumerate(block)]
    return "\n".join(parts)


def apply_labels(block: list[Segment], first_number: int, lines: list[dict]) -> None:
    """Store the model's label on each segment. Missing or bad labels -> "game"."""
    by_number = {}
    for item in lines:
        try:
            by_number[int(item["n"])] = item["label"]
        except (KeyError, TypeError, ValueError):
            continue
    for i, seg in enumerate(block):
        label = by_number.get(first_number + i)
        seg.extra["label"] = label if label in LABELS else "game"


SMOOTH_MAX_LINES = 3  # a run this short takes the label of identical neighbors
SMOOTH_MAX_WORDS = 12
MIN_CUT_LINES = 4  # table talk shorter than this is kept (too little to matter)


def _runs(segments: list[Segment]) -> list[list[Segment]]:
    runs: list[list[Segment]] = []
    for seg in segments:
        if runs and runs[-1][0].extra["label"] == seg.extra["label"]:
            runs[-1].append(seg)
        else:
            runs.append([seg])
    return runs


def smooth_and_cut(segments: list[Segment]) -> int:
    """Absorb short runs into same-labeled neighbors, then remove table talk.

    `segments` are the classified (kept) ones in time order. Returns lines removed.
    """
    runs = _runs(segments)
    for i in range(1, len(runs) - 1):
        run, before, after = runs[i], runs[i - 1], runs[i + 1]
        short = len(run) <= SMOOTH_MAX_LINES and sum(s.words for s in run) <= SMOOTH_MAX_WORDS
        if short and before[0].extra["label"] == after[0].extra["label"]:
            for seg in run:
                seg.extra["label"] = before[0].extra["label"]
    removed = 0
    for run in _runs(segments):
        if run[0].extra["label"] == "table_talk" and len(run) >= MIN_CUT_LINES:
            for seg in run:
                seg.removed_by = "off_topic"
                seg.reason = "table talk"
                removed += 1
    return removed


MIN_SPLIT_LINES = 10


def blocks(kept: list[Segment], size: int = BLOCK_LINES):
    for i in range(0, len(kept), size):
        yield kept[max(0, i - CONTEXT_LINES) : i], kept[i : i + size]


def classify_block(
    context: list[Segment],
    block: list[Segment],
    ask: Callable[[str, str, dict], dict],
    campaign: str = "",
) -> int:
    """Classify one block; on failure retry as two halves, then flag as unchecked."""
    try:
        result = ask(SYSTEM_PROMPT, build_prompt(context, block, 1, campaign), SCHEMA)
        apply_labels(block, 1, result.get("lines", []))
        return len(block)
    except Exception:  # timeout, bad JSON, model loop
        if len(block) >= 2 * MIN_SPLIT_LINES:
            half = len(block) // 2
            first, second = block[:half], block[half:]
            return classify_block(context, first, ask, campaign) + classify_block(
                (context + first)[-CONTEXT_LINES:], second, ask, campaign
            )
        for seg in block:
            seg.extra["unchecked"] = True
            seg.extra["label"] = "game"
        return 0


def classify(
    segments: list[Segment],
    ask: Callable[[str, str, dict], dict],
    progress: Callable[[int, int], None] = lambda done, total: None,
    campaign: str = "",
) -> int:
    """Label every still-kept segment via `ask`, then cut table talk. Returns lines cut."""
    kept = [s for s in segments if s.kept]
    all_blocks = list(blocks(kept))
    for b, (context, block) in enumerate(all_blocks):
        classify_block(context, block, ask, campaign)
        progress(b + 1, len(all_blocks))
    return smooth_and_cut(kept)
