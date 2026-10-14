"""askdnd v2 web app."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

APP_ENV = os.getenv("APP_ENV", "development")

app = FastAPI(title="askdnd", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": APP_ENV}


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {"env": APP_ENV})
