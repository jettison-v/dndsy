"""askdnd v2 web app."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.auth import current_user
from app.auth import router as auth_router

app = FastAPI(title="askdnd", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    session_cookie="askdnd_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=config.IS_PRODUCTION,
)
app.include_router(auth_router)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

LOGIN_ERRORS = {
    "not_allowed": "That Google account isn't on the list for this table.",
    "failed": "Sign-in didn't complete. Please try again.",
    "not_configured": "Google sign-in isn't set up yet.",
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": config.APP_ENV}


@app.get("/login")
def login(request: Request, error: str | None = None):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": LOGIN_ERRORS.get(error or "")}
    )


@app.get("/")
def home(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "home.html", {"env": config.APP_ENV, "user": user}
    )
