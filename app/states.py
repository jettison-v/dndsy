"""One colour key for every state a Backstage page shows (Brett's pick AU2 on docs/mockups/end-of-day-audit/, Nov 25: the
same state had a different colour on different pages, from five vocabularies). A state's key gives its one word (AU7:
one word in a pill; anything longer goes on a line beside it) and its tone, and the tone its colour:

- you: waiting on you (amber)
- going: under way (blue); working: under way right now (blue, moving)
- done: done or ready (green)
- quiet: nothing to do (grey outline)
- broken: something failed (red)

Pages draw a state with `state_tag(key)` (a template global), never by choosing a class from its words."""

from markupsafe import Markup, escape

TONES = {"you": "draft", "going": "new", "working": "working", "done": "done", "quiet": "faint", "broken": "error"}

STATES: dict[str, tuple[str, str]] = {
    # a session's recap (Sessions, its review page, the Inbox)
    "draft": ("Draft", "you"), "edited": ("Edited", "going"), "published": ("Published", "done"),
    "drafting": ("Drafting…", "working"), "no draft": ("Not drafted", "quiet"), "read": ("To draft", "you"),
    # a Labs feature (Settings)
    "building": ("Building", "going"), "ready": ("Ready", "done"),
    # a document (Documents)
    "waiting": ("Yours", "you"), "current": ("Current", "done"), "done": ("Done", "done"), "earlier": ("Earlier", "quiet"),
    # a homebrew item (Items)
    "in play": ("In play", "done"), "unused": ("Unused", "quiet"),
    # anything that runs
    "running": ("Running", "working"), "failed": ("Failed", "broken"),
    # a piece of sync work (the Sync page, app/sync_page.py)
    "queued": ("Waiting", "going"), "not yet": ("Not yet", "you"), "cancelled": ("Cancelled", "quiet"),
}


def word(key: str) -> str:
    return STATES.get(key, (key, ""))[0]


def tone_class(key: str) -> str:
    return TONES.get(STATES.get(key, ("", "quiet"))[1], "faint")


def state_tag(key: str) -> Markup:
    """A state as its pill: its one word in its tone's colour, marked by its key (never found by its words)."""
    return Markup('<span class="tag {}" data-state="{}">{}</span>').format(tone_class(key), key, escape(word(key)))
