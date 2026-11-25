"""One door between Found, Fixed, Tried and askdnd (app/fft/host.py; the backend look-back's LB3, Brett's pick A,
Nov 25; "FFT is a product", Nov 20): the tool's modules use askdnd only through host.py, besides the platform every host
has. A new need of askdnd is added to host.py, never imported beside it."""

import ast
from pathlib import Path

FFT = Path(__file__).resolve().parent.parent / "app" / "fft"
PLATFORM = {"app.db", "app.templating", "app.web", "app.config", "app.realtime", "app.files", "app.errors", "app.timing",
            "app.single", "app.mail"}
DOOR = {"host.py"}  # (the door itself)
MOVED_ONCE = {"carry.py"}  # (askdnd's old Feedback and Testing, carried into the tool once by a migration: askdnd's by nature)


def _outside(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "app":
                out += [f"app.{a.name}" for a in node.names]
            elif node.module.startswith("app.") and not node.module.startswith("app.fft"):
                out.append(node.module)
        elif isinstance(node, ast.Import):
            out += [a.name for a in node.names if a.name.startswith("app.") and not a.name.startswith("app.fft")]
    return [m for m in out if m not in PLATFORM and m != "app.fft"]


def test_the_tool_uses_askdnd_only_through_its_door():
    found = {f.name: _outside(ast.parse(f.read_text())) for f in sorted(FFT.glob("*.py")) if f.name not in DOOR | MOVED_ONCE}
    assert {name: mods for name, mods in found.items() if mods} == {}


def test_the_check_catches_a_new_import(tmp_path):
    """The check itself works: each way of importing askdnd is caught, the platform and the tool's own aren't."""
    code = "from app import access, config\nfrom app.models import User\nimport app.view_as\nfrom app.fft import rules\nfrom app.db import get_db\n"
    assert sorted(_outside(ast.parse(code))) == ["app.access", "app.models", "app.view_as"]
