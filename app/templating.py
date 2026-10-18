from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates


def _page_context(request: Request) -> dict:
    """Available in every template: who's signed in and where they are."""
    from app.auth import can_moderate, can_see_character_notes, current_user, is_admin, is_dm, is_reviewer

    user = current_user(request)
    return {"user": user, "is_admin": is_admin(user), "is_reviewer": is_reviewer(user), "is_dm": is_dm(user), "can_moderate": can_moderate(user),
            "can_see_notes": can_see_character_notes(user), "path": request.url.path}


templates = Jinja2Templates(directory=Path(__file__).parent / "templates", context_processors=[_page_context])


def _markdown(text: str) -> str:
    from app.render import markdown_to_html

    return markdown_to_html(text or "", lambda name: None)


templates.env.filters["md"] = _markdown


def _relation_label(type_: str) -> str:
    from app.relations import TYPES

    return TYPES[type_].forward if type_ in TYPES else type_.replace("_", " ")


templates.env.filters["rel_label"] = _relation_label


def _ago(when) -> str:
    """'just now', '5 minutes ago', '3 hours ago', 'yesterday', or 'Oct 14' — no time zone needed."""
    from datetime import UTC, datetime

    if when is None:
        return ""
    seconds = (datetime.now(UTC) - when).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 86400:
        hours = round(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if seconds < 2 * 86400:
        return "yesterday"
    return when.strftime("%b %-d, %Y") if seconds > 300 * 86400 else when.strftime("%b %-d")


templates.env.filters["ago"] = _ago


def _terms(text: str, on=None, seen=None):
    """Underline rule terms (first mention) with a definition on hover; see rules_terms."""
    from app.rules_terms import annotate

    return annotate(text or "", on, seen)


templates.env.filters["terms"] = _terms


def _ordinal(n) -> str:
    """1 -> "1st", 2 -> "2nd" (spell levels)."""
    from app.character_views import ordinal

    return ordinal(int(n)) if str(n).isdigit() else str(n)


templates.env.filters["ordinal"] = _ordinal
