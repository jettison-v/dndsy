"""Minimal client for the local Ollama server (stdlib only, localhost only)."""

import json
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"


def chat_json(
    model: str, system: str, user: str, schema: dict, num_ctx: int = 16384, timeout: int = 180
) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "format": schema,
        "stream": False,
        "think": False,
        "keep_alive": "15m",
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": 3000},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    return json.loads(payload["message"]["content"])


def installed_models() -> list[str]:
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=10) as resp:
        return [m["name"] for m in json.loads(resp.read())["models"]]
