"""askdnd Processor: the local GUI for filtering transcripts.

Runs only on Brett's Mac, bound to 127.0.0.1, so raw transcripts never leave it.
Start it with the "askdnd Processor" app, or:  uv run python -m transcript_filter.web
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from transcript_filter import ollama
from transcript_filter.pipeline import (
    DEFAULT_MODEL,
    PipelineError,
    cut_stretches,
    is_final_kept,
    load_state,
    run,
    save_state,
)
from transcript_filter.segments import format_time

HOST, PORT = "127.0.0.1", 8765
ROOT = Path(os.getenv("ASKDND_TRANSCRIPTS", Path(__file__).resolve().parent.parent / "transcripts"))
RAW, WORK = ROOT / "raw", ROOT / "work"
STEM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_UPLOAD = 20_000_000

app = FastAPI(title="askdnd Processor", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
jobs: dict[str, dict] = {}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Reject requests from other websites (a page elsewhere could try to POST here)."""
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin not in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return await call_next(request)


def paths(stem: str) -> dict[str, Path]:
    if not STEM.match(stem):
        raise ValueError("bad session name")
    work = WORK / stem
    return {
        "raw": RAW / f"{stem}.json",
        "state": work / "state.json",
        "stats": work / "stats.json",
        "final_json": work / "final.json",
        "final_txt": work / "final.txt",
    }


def ollama_status() -> dict:
    try:
        models = ollama.installed_models()
    except Exception:
        return {"running": False, "model_ready": False}
    return {"running": True, "model_ready": DEFAULT_MODEL in models}


def session_summary(stem: str) -> dict:
    p = paths(stem)
    job = jobs.get(stem, {})
    if job.get("status") == "running":
        status = "filtering"
    elif p["final_json"].exists():
        status = "saved"
    elif p["state"].exists():
        status = "review"
    else:
        status = "new"
    return {"stem": stem, "status": status, "job": job}


@app.get("/")
def home(request: Request, error: str | None = None):
    stems = sorted((f.stem for f in RAW.glob("*.json") if STEM.match(f.stem)), reverse=True)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"sessions": [session_summary(s) for s in stems], "ollama": ollama_status(), "today": date.today().isoformat(), "error": error},
    )


def looks_like_macwhisper(data) -> bool:
    return (
        isinstance(data, list)
        and len(data) > 0
        and all(isinstance(x, dict) and "timestamp" in x and "text" in x for x in data[:50])
    )


@app.post("/upload")
async def upload(file: UploadFile = File(...), played_on: str = Form(...), replace: str = Form("")):
    raw = await file.read(MAX_UPLOAD + 1)
    if not STEM.match(played_on):
        return RedirectResponse("/?error=Pick+the+session+date.", status_code=303)
    if len(raw) > MAX_UPLOAD:
        return RedirectResponse("/?error=That+file+is+too+large.", status_code=303)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if not looks_like_macwhisper(data):
        return RedirectResponse(
            "/?error=That+doesn't+look+like+a+MacWhisper+export.+Export+as+Segments+%2B+.json.", status_code=303
        )
    p = paths(played_on)
    if p["raw"].exists() and not replace:
        return RedirectResponse(f"/?error=There's+already+a+session+for+{played_on}.+Tick+'Replace'+to+overwrite+it.", status_code=303)
    RAW.mkdir(parents=True, exist_ok=True)
    p["raw"].write_bytes(raw)
    for key in ("state", "stats", "final_json", "final_txt"):
        p[key].unlink(missing_ok=True)
    return RedirectResponse(f"/sessions/{played_on}", status_code=303)


def _filter_job(stem: str):
    p = paths(stem)
    job = jobs[stem]

    def progress(done, total):
        job.update(done=done, total=total)

    try:
        segments, result = run(p["raw"], DEFAULT_MODEL, ROOT, ROOT / "context.md", progress)
        save_state(segments, p["state"])
        p["stats"].write_text(json.dumps(result, indent=1))
        p["final_json"].unlink(missing_ok=True)
        job.update(status="done", finished=time.time())
    except PipelineError as e:
        job.update(status="error", error=str(e))
    except Exception as e:  # show anything unexpected instead of hanging
        job.update(status="error", error=f"{type(e).__name__}: {e}")


@app.post("/sessions/{stem}/filter")
def start_filter(stem: str):
    p = paths(stem)
    if not p["raw"].exists():
        return RedirectResponse("/", status_code=303)
    if jobs.get(stem, {}).get("status") != "running":
        jobs[stem] = {"status": "running", "done": 0, "total": 0, "started": time.time()}
        threading.Thread(target=_filter_job, args=(stem,), daemon=True).start()
    return RedirectResponse(f"/sessions/{stem}", status_code=303)


@app.get("/sessions/{stem}/progress")
def progress(stem: str):
    job = jobs.get(stem, {"status": "idle"})
    elapsed = time.time() - job.get("started", time.time())
    remaining = None
    if job.get("done") and job.get("total"):
        remaining = round(elapsed / job["done"] * (job["total"] - job["done"]))
    return {**{k: v for k, v in job.items() if k in ("status", "done", "total", "error")}, "remaining": remaining}


@app.get("/sessions/{stem}")
def session_page(request: Request, stem: str):
    p = paths(stem)
    if not p["raw"].exists():
        return RedirectResponse("/", status_code=303)
    summary = session_summary(stem)
    context = {"s": summary, "ollama": ollama_status(), "fmt": format_time, "stretches": [], "stats": None}
    if p["state"].exists() and summary["status"] != "filtering":
        segments = load_state(p["state"])
        stretches = []
        for run_ in cut_stretches(segments):
            words = sum(len(x.text.split()) for x in run_)
            stretches.append({
                "id": run_[0].index,
                "start": run_[0].start,
                "end": run_[-1].end,
                "lines": run_,
                "words": words,
                "kept": all(x.extra.get("keep") for x in run_),
            })
        kept = [x for x in segments if is_final_kept(x)]
        context.update(
            stretches=stretches,
            stats=json.loads(p["stats"].read_text()) if p["stats"].exists() else {},
            kept_words=sum(len(x.text.split()) for x in kept),
            unchecked=[x for x in segments if x.extra.get("unchecked") and is_final_kept(x)],
        )
    return templates.TemplateResponse(request, "session.html", context)


@app.post("/sessions/{stem}/stretches/{first_index}")
def toggle_stretch(stem: str, first_index: int, keep: str = Form(...)):
    p = paths(stem)
    segments = load_state(p["state"])
    for run_ in cut_stretches(segments):
        if run_[0].index == first_index:
            for seg in run_:
                seg.extra["keep"] = keep == "1"
    save_state(segments, p["state"])
    p["final_json"].unlink(missing_ok=True)  # a change means the saved copy is out of date
    return RedirectResponse(f"/sessions/{stem}#s{first_index}", status_code=303)


@app.post("/sessions/{stem}/save")
def save_final(stem: str):
    p = paths(stem)
    kept = [x for x in load_state(p["state"]) if is_final_kept(x)]
    p["final_json"].write_text(json.dumps(
        [{"start": round(x.start, 3), "end": round(x.end, 3), "speaker": x.speaker, "text": x.text} for x in kept],
        indent=1, ensure_ascii=False,
    ))
    p["final_txt"].write_text("\n".join(f"[{format_time(x.start)}] {x.speaker or 'Unknown'}: {x.text}" for x in kept) + "\n")
    return RedirectResponse(f"/sessions/{stem}#saved", status_code=303)


@app.post("/sessions/{stem}/reveal")
def reveal(stem: str):
    """Show the saved file in Finder."""
    p = paths(stem)
    target = p["final_txt"] if p["final_txt"].exists() else p["raw"]
    subprocess.run(["open", "-R", str(target)], check=False)
    return RedirectResponse(f"/sessions/{stem}", status_code=303)


@app.post("/ollama/start")
def start_ollama():
    subprocess.run(["open", "-a", "Ollama"], check=False)
    time.sleep(3)
    return RedirectResponse("/", status_code=303)


@app.post("/quit")
def quit_app(request: Request):
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return templates.TemplateResponse(request, "message.html", {"title": "Processor stopped", "message": "You can close this tab. Double-click askdnd Processor to start it again."})


def main():
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
