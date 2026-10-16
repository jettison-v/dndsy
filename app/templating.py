from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates


def _page_context(request: Request) -> dict:
    """Available in every template: who's signed in and where they are."""
    from app.auth import current_user, is_admin, is_reviewer

    user = current_user(request)
    return {"user": user, "is_admin": is_admin(user), "is_reviewer": is_reviewer(user), "path": request.url.path}


templates = Jinja2Templates(directory=Path(__file__).parent / "templates", context_processors=[_page_context])


def _markdown(text: str) -> str:
    from app.render import markdown_to_html

    return markdown_to_html(text or "", lambda name: None)


templates.env.filters["md"] = _markdown
