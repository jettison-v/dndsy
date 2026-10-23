from pathlib import Path

from fastapi import Request

from app import access, vtt
from fastapi.templating import Jinja2Templates


def _page_context(request: Request) -> dict:
    """Available in every template: who's signed in and where they are."""
    from app.auth import can_moderate, can_see_character_notes, current_user, is_admin, is_dm, is_reviewer
    from app.manage import pages_for

    user = current_user(request)
    table: dict = {}

    def tablenav() -> dict:
        """The menu bar's characters and Live pill (app/live.py), read once, only by pages that show them. A character
        page's mode is remembered in the session, so "your character" opens in the mode you used last."""
        from app.live import table as live_table

        if "v" not in table:
            table["v"] = live_table(user, request.url.path, last_mode=request.session.get("mode"))
            if table["v"].get("mode") and request.session.get("mode") != table["v"]["mode"]:
                request.session["mode"] = table["v"]["mode"]
        return table["v"]

    def campaign_role(campaign_id: int) -> str:
        """Your role in another campaign, for the campaign menu ("DM", "Reviewer"; players have no label)."""
        return {"dm": "DM", "reviewer": "Reviewer"}.get(access.role(user.get("email"), campaign_id) or "", "") if user else ""

    here = access.current_campaign() if user else None
    viewing_as = user if request.session.get("real_user") and user else None  # app/view_as.py
    viewing_role = access.ROLE_LABELS.get(access.role(user.get("email"))) if viewing_as else None
    return {"user": user, "viewing_as": viewing_as, "viewing_role": viewing_role, "is_admin": is_admin(user), "is_reviewer": is_reviewer(user), "is_dm": is_dm(user), "can_moderate": can_moderate(user),
            "can_see_notes": can_see_character_notes(user), "path": request.url.path,
            "manage_pages": pages_for(user, request.url.path), "tablenav": tablenav, "campaign_role": campaign_role,
            "in_campaign": access.path_slug.get() is not None,  # the address names the campaign (/c/<campaign>/…)
            # The campaign you're in, the start of its story addresses, and the campaigns you can switch to
            "here": here, "cbase": f"/c/{here['slug']}" if here else "",
            "my_campaigns": access.campaigns_for(user.get("email")) if user else [],
            "switch_path": switch_path(request.url.path),
            "vtt_on": lambda key: vtt.on(here, key)}  # the VTT switch (app/vtt.py)


# Pages that make sense in any campaign: switching campaigns keeps you on them (else you land on Story)
SWITCH_KEEPS = ("/", "/campaign", "/party", "/your-suggestions", "/manage", "/manage/inbox",
                "/manage/sessions", "/manage/sessions/doc", "/manage/table", "/manage/house-rules", "/manage/history",
                "/manage/settings", "/manage/dm-guide")


def switch_path(path: str) -> str:
    return path if path in SWITCH_KEEPS else "/"


templates = Jinja2Templates(directory=Path(__file__).parent / "templates", context_processors=[_page_context])


def _markdown(text: str) -> str:
    from app.render import markdown_to_html

    return markdown_to_html(text or "", lambda name: None)


templates.env.filters["md"] = _markdown


def _entry_url(entity_id) -> str:
    """An entry's one address: the Campaign page with it open, in the campaign being looked at (2026-10-23)."""
    from app import web

    return f"{web.base()}/campaign?open={entity_id}"


templates.env.globals["entry_url"] = _entry_url


def _outcome(status: str) -> dict:
    from app.suggestions import outcome

    return outcome(status)


templates.env.filters["outcome"] = _outcome


def _diff(old: str, new: str):
    from app.render import word_diff

    return word_diff(old, new)


templates.env.filters["diff"] = _diff  # {{ before | diff(after) }}: a marked-up edit (<del>, <ins>)  # a suggestion's status as its author sees it: Waiting, Added, Used, Not used


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


_STATIC = Path(__file__).parent / "static"
_hashes: dict[tuple[str, float], str] = {}


def _static(name: str) -> str:
    """/static/<name>?v=<content hash>: browsers fetch the new file whenever it changes (no hand-edited numbers)."""
    import hashlib

    path = _STATIC / name
    try:
        key = (name, path.stat().st_mtime)
    except OSError:
        return f"/static/{name}"
    if key not in _hashes:
        _hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={_hashes[key]}"


templates.env.globals["static"] = _static


_DICE = None


def _dice(text: str) -> str:
    """The first dice expression in a line ("5 ft · 1d6+3 bludgeoning" -> "1d6+3"), for roll buttons."""
    import re

    global _DICE
    _DICE = _DICE or re.compile(r"(\d+d\d+(?:\s*[+−-]\s*\d+)?)")
    m = _DICE.search(text or "")
    return re.sub(r"\s+", "", m.group(1)).replace("−", "-") if m else ""


templates.env.filters["dice"] = _dice


def _combo_steps(turn: dict) -> list[dict]:
    from app.player_notes import combo_steps

    return combo_steps(turn or {})


templates.env.filters["combo_steps"] = _combo_steps
templates.env.globals["STEP_KINDS"] = {"bonus": "Bonus action", "action": "Action", "reaction": "Reaction", "move": "Movement", "free": "Free"}
