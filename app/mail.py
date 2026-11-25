"""Sending one email through Resend (the Inbox digest, the fixes email, nobody's-listening): one way, written once (the
backend look-back's LB4). `mail` is {subject, html, text} and, for an email a person can stop, `stop` (its one-click
unsubscribe address). Each sender keeps its own `SEND` for tests to replace; nothing here reaches Resend in a test."""

import json
import urllib.request

from app import config

RESEND = "https://api.resend.com/emails"


def send(to: str, mail: dict) -> bool:
    """Send it; True when Resend took it. Raises on a network error (each caller's look counts a miss and tries again)."""
    out = {"from": config.EMAIL_FROM, "to": [to], "subject": mail["subject"], "html": mail["html"], "text": mail["text"]}
    if mail.get("stop"):
        out["headers"] = {"List-Unsubscribe": f"<{mail['stop']}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    req = urllib.request.Request(RESEND, data=json.dumps(out).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json",
                                          "User-Agent": "askdnd"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return 200 <= r.status < 300
