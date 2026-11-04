from pathlib import Path

from fastapi import Request

from app import access, config, rules_data, vtt
from app import conditions as cond
from app.creatures import short as creature_short
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
    fight: dict = {}

    def fight_now() -> dict | None:
        """The fight in D&D Beyond's VTT as you see it (app/fight.py), for the fight band; read once per page."""
        from app import fight as f

        if "v" not in fight:
            fight["v"] = None
            if user and here:
                try:
                    fight["v"] = f.loader(here["id"], user.get("email"))
                except Exception:
                    pass  # database unavailable: the page works without it
        return fight["v"]

    viewing_as = user if request.session.get("real_user") and user else None  # app/view_as.py
    viewing_role = access.ROLE_LABELS.get(access.role(user.get("email"))) if viewing_as else None
    return {"user": user, "viewing_as": viewing_as, "viewing_role": viewing_role, "is_admin": is_admin(user), "is_reviewer": is_reviewer(user), "is_dm": is_dm(user), "can_moderate": can_moderate(user),
            "can_see_notes": can_see_character_notes(user), "path": request.url.path,
            "manage_pages": pages_for(user, request.url.path), "tablenav": tablenav, "campaign_role": campaign_role,
            "in_campaign": access.path_slug.get() is not None,  # the address names the campaign (/c/<campaign>/…)
            # The campaign you're in, the start of its story addresses, and the campaigns you can switch to
            "here": here, "cbase": f"/c/{here['slug']}" if here else "",
            "my_campaigns": access.campaigns_for(user.get("email")) if user else [],
            "managed_ids": [c["id"] for c in access.campaigns_for(user.get("email")) if access.role(user.get("email"), c["id"]) in (access.DM, access.REVIEWER)] if user else [],  # (the Manage menu's other campaigns)
            "switch_path": switch_path(request.url.path),
            "vtt_on": lambda key: vtt.on(here, key),  # the VTT switch (app/vtt.py)
            "table_url": table_url(here),
            "fight_now": fight_now,
            "my_dice": _my_dice, "dice_tuning": _dice_tuning,
            "my_id": (lambda: access.user_id(user.get("email"))) if user else (lambda: None)}  # your dice and everyone's tuning (app/dice.py), for thrown rolls


# Pages that make sense in any campaign: switching campaigns keeps you on them (else you land on Story)
SWITCH_KEEPS = ("/", "/campaign", "/party", "/your-suggestions", "/manage", "/manage/inbox",
                "/manage/sessions", "/manage/sessions/doc", "/manage/table", "/manage/house-rules", "/manage/history",
                "/manage/settings", "/manage/dm-guide")


def switch_path(path: str) -> str:
    return path if path in SWITCH_KEEPS else "/"


def _my_dice() -> dict:
    from app.dice import mine

    return mine()


templates = Jinja2Templates(directory=Path(__file__).parent / "templates", context_processors=[_page_context])


def _dice_tuning() -> dict:
    from app.dice import tuning

    return tuning()


def table_url(campaign: dict | None) -> str:
    """Where this campaign plays: askdnd's own table once its switch is on (askdnd's VTT), else D&D Beyond's VTT. The
    Table button stays put."""
    if campaign and vtt.on(campaign, "vtt_table"):
        return f"/c/{campaign['slug']}/table"
    game = (campaign or {}).get("ddb_campaign_id")
    return f"https://www.dndbeyond.com/games/{game}" if game else ""


# Short names for Battle's Resources row, once the whole names won't fit on one line (Brett, 2026-11-01: seeing them all
# matters more than the whole word), with the whole name on hover and in the window a resource opens. Anything not listed
# keeps its name.
RES_SHORT = {
    "Action Surge": "Surge", "Adrenaline Rush": "Adrenaline", "Arcane Recovery": "Arcane Rec.", "Bardic Inspiration": "Bardic Insp.",
    "Breath Weapon": "Breath", "Channel Divinity": "Channel", "Create Eldritch Cannon": "Make Cannon", "Divine Intervention": "Intervention",
    "Draconic Cry": "Cry", "Dreadful Strike": "Dreadful", "Eldritch Cannon": "Cannon", "Faithful Steed": "Steed",
    "Favored by the Gods": "Favored", "Favored Enemy": "Fav. Enemy", "Flamethrower": "Flame", "Flash of Genius": "Flash",
    "Focus Points": "Focus", "Font of Magic: Sorcery Points": "Sorcery", "Force Ballista": "Ballista", "Harness Divine Power": "Harness",
    "Healing Hands": "Heal Hands", "Infuse Item": "Infuse", "Innate Sorcery": "Innate", "Lay On Hands: Healing Pool": "Lay on Hands",
    "Luck Points": "Luck", "Magical Cunning": "Cunning", "Magical Tinkering": "Tinkering", "Nature's Sanctuary": "Sanctuary",
    "Nature's Veil": "Veil", "Psionic Energy Dice": "Psi Dice", "Relentless Endurance": "Relentless", "Second Wind": "2nd Wind",
    "Sorcery Incarnate": "Incarnate", "Sorcery Points": "Sorcery", "Stone's Endurance": "Stone's End.", "Stroke of Luck": "Stroke",
    "Superiority Dice": "Sup. Dice", "Tides of Chaos": "Tides", "Uncanny Metabolism": "Metabolism", "Wild Companion": "Companion",
    "Wild Resurgence: Regain Spell Slot": "Wild Res.",
}


def res_short(name: str) -> str:
    return RES_SHORT.get(name, name)


def res_groups(rows: list[dict]) -> list[dict]:
    """Resources in their order, those sharing a name before ": " under that name (any class's): {"name", "rows"}."""
    names = [r["name"].split(": ", 1)[0] if ": " in r["name"] else "" for r in rows]
    out: list[dict] = []
    for r, name in zip(rows, names):
        shared = name and names.count(name) > 1
        if shared and out and out[-1]["name"] == name:
            out[-1]["rows"].append(r)
        else:
            out.append({"name": name if shared else "", "rows": [r]})
    return out


def _markdown(text: str) -> str:
    from app.render import markdown_to_html

    return markdown_to_html(text or "", lambda name: None)


def _ini_shown(n) -> str:
    from app import initiative

    return initiative.shown(n)


templates.env.filters["md"] = _markdown
templates.env.filters["res_groups"] = res_groups
templates.env.filters["res_short"] = res_short
templates.env.filters["creature_short"] = creature_short  # (Your creatures' switch by the name)
templates.env.filters["ini"] = lambda n: _ini_shown(n)  # an initiative as the VTT keeps it: 14, 13.5 (app/initiative.py)


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

    if not when:
        return ""
    if isinstance(when, str):  # (as JSON carries it)
        when = datetime.fromisoformat(when)
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


def _clock(when, date: bool = False):
    """A time of day as the reader keeps it: askdnd's server keeps UTC and doesn't know the reader's time zone, so it
    writes the time in UTC and app.js ("clocks") rewrites it in the browser's own. `when` is a datetime, ISO text (as
    JSON carries it) or seconds since 1970; `date` adds the day ("Oct 29, 6:22 PM")."""
    from datetime import UTC, datetime

    from markupsafe import Markup

    if not when:
        return ""
    if isinstance(when, int | float):
        when = datetime.fromtimestamp(when, UTC)
    elif isinstance(when, str):
        when = datetime.fromisoformat(when)
    when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    shown = when.strftime("%b %-d, %Y, %-I:%M %p" if date else "%-I:%M %p") + " UTC"
    return Markup('<time datetime="{}" data-clock="{}">{}</time>').format(when.isoformat(), "date" if date else "time", shown)


templates.env.filters["clock"] = _clock


def _left(until) -> str:
    """How long until then: '5 hours 40 minutes', '12 minutes', 'a moment' (no time zone needed)."""
    from datetime import UTC, datetime

    if not until:
        return ""
    minutes = max(0, round((until - datetime.now(UTC)).total_seconds() / 60))
    hours, minutes = divmod(minutes, 60)
    parts = ([f"{hours} hour{'s' if hours != 1 else ''}"] if hours else []) + ([f"{minutes} minute{'s' if minutes != 1 else ''}"] if minutes else [])
    return " ".join(parts) or "a moment"


templates.env.filters["left"] = _left


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
# The D&D Beyond bridge (app/ddb_bridge.py) may run here (DDB_BRIDGE=1); pages also ask vtt_on("ddb_bridge")
templates.env.globals["bridge_on"] = config.DDB_BRIDGE
templates.env.globals["bridge_extension_url"] = config.BRIDGE_EXTENSION_URL
templates.env.globals["lasts_times"], templates.env.globals["lasts_abilities"] = cond.TIMES, cond.ABILITIES  # + Condition's Lasts
templates.env.globals["SRD_ATTRIBUTION"] = rules_data.ATTRIBUTION  # Help › About; the SRD's license asks for it word for word
# Conditions' look on Battle, Party and the menu bar (app/conditions.py, _cond_icons.html)
templates.env.globals["cond_slug"] = cond.slug
templates.env.globals["cond_edge"] = cond.edge
templates.env.globals["cond_darkens"] = cond.darkens
templates.env.filters["cond_var"] = lambda slug: "var(--cond-dark)" if slug == "blinded" else f"var(--cond-{slug})"  # Blinded's edge is black
templates.env.globals["STEP_KINDS"] = {"bonus": "Bonus action", "action": "Action", "reaction": "Reaction", "move": "Movement", "free": "Free"}
