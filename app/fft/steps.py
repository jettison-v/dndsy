"""A check's steps as a walkthrough (docs/testing-guide.md): one action a line; `typed` what to type, [Button] a
button, **Box** a box's name, "(why: …)" why. Found, Fixed, Tried and the Testing it replaces share these."""

import re


def local_path(p: str) -> bool:
    """An address on askdnd itself: starts with one /, never //, a backslash (browsers read /\\ as //) or a control
    character (the code review, Nov 16: a note's address made a check's link that left askdnd)."""
    return bool(p) and p.startswith("/") and not p.startswith("//") and "\\" not in p and not any(ord(ch) < 32 or ord(ch) == 127 for ch in p)


STEP_MARKS = re.compile(r"(`[^`\n]+`|\[[^\[\]\n]+\]|\*\*[^*\n]+\*\*)")  # (each part can't hold its own opener: linear on any input, CodeQL)
WHY = re.compile(r"\(why:([^()]*)\)$", re.I)  # (on a stripped line)
STEP_MAX = 500  # (a step's length, at most)
TWO_THINGS = re.compile(r",\s*then\b|;\s*then\b|\band then\b|\bthen press\b", re.I)
UNMARKED_TYPING = re.compile(r"\b(type|enter|write|fill in)\s+(?!it\b|in\b|a\b|an\b|the\b|your\b|something\b)\w", re.I)


def walk(do: str) -> list[dict]:
    """A check's steps as the walkthrough shows them (3A): each line a step in parts: text, `typed` (what to type),
    [Button] (a button, drawn as one), **Box** (a box's name), and its (why: …) last."""
    out = []
    for line in (do or "").splitlines():
        line = line.strip()[:STEP_MAX]
        if not line:
            continue
        why = WHY.search(line)
        body = line[: why.start()] if why else line
        parts = []
        for bit in STEP_MARKS.split(body.strip()):
            if not bit:
                continue
            kind = "typed" if bit.startswith("`") else "press" if bit.startswith("[") else "box" if bit.startswith("**") else "text"
            parts.append({"kind": kind, "text": bit.strip("`*") if kind in ("typed", "box") else bit[1:-1] if kind == "press" else bit})
        out.append({"parts": parts, "why": why.group(1).strip() if why else ""})
    return out


def step_problems(do: str) -> list[str]:
    """What breaks the walkthrough's rules (docs/testing-guide.md): a step that does two things, or a word to type that
    isn't `marked` (Brett, Nov 17: "type lots in Or type it" read as an instruction to decode)."""
    found = []
    for n, line in enumerate((x.strip()[:STEP_MAX] for x in (do or "").splitlines() if x.strip()), 1):
        bare = STEP_MARKS.sub(" ", WHY.sub("", line))
        if TWO_THINGS.search(bare):
            found.append(f"Step {n} does two things: one action a step.")
        if UNMARKED_TYPING.search(bare):
            found.append(f"Step {n}: what to type goes in `backticks`.")
    return found
