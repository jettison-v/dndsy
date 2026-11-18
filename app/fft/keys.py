"""A key per actor and place, each allowed only what it does (T6). Today's keys come from the environment (Railway
variables; `.env` locally): FEEDBACK_KEY is Claude's on askdnd.ai, FFT_RELAY_KEY staging's relay (it may only send
notes, which always wait for an admin), FFT_MINI_KEY the Mac Mini's runs (it may only record its own tries). Keys made
in the app later live hashed in `fft_keys`. No key of Claude's can confirm a fix: only a person does (R16)."""

import hashlib
import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.fft.models import FftKey

SCOPES = {
    "claude": frozenset({"read", "write", "ask", "check", "deploy"}),
    "relay": frozenset({"relay"}),
    "mini": frozenset({"mini"}),
}


@dataclass(frozen=True)
class Actor:
    name: str  # "claude", "relay", "mini": the event's actor
    scopes: frozenset

    def may(self, scope: str) -> bool:
        return scope in self.scopes


def _env_keys() -> list[tuple[str, str]]:
    return [(k, v) for k, v in (("claude", config.FEEDBACK_KEY), ("relay", os.getenv("FFT_RELAY_KEY", "").strip()),
                                 ("mini", os.getenv("FFT_MINI_KEY", "").strip())) if v]


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def actor_for(db: Session, key: str | None) -> Actor | None:
    """Who a key is, or None. Compared in constant time; a revoked key is no one."""
    if not key or len(key) < 24:
        return None
    for name, value in _env_keys():
        if secrets.compare_digest(key, value):
            return Actor(name, SCOPES[name])
    row = db.scalar(select(FftKey).where(FftKey.key_hash == digest(key), FftKey.revoked.is_(False)))
    if row is not None and row.actor in SCOPES:
        return Actor(row.actor, frozenset(row.scopes or []) & SCOPES[row.actor])
    return None


def require(db: Session, key: str | None, scope: str) -> Actor:
    """The route's guard: an unknown key gets a 404 (the API isn't there for it); a known one without the scope, 403."""
    actor = actor_for(db, key)
    if actor is None:
        raise HTTPException(404)
    if not actor.may(scope):
        raise HTTPException(403, f"This key can't {scope}.")
    return actor


def make(db: Session, name: str, actor: str, scopes: list[str] | None = None) -> str:
    """A new key (shown once), kept only as its hash."""
    if actor not in SCOPES:
        raise ValueError(actor)
    key = secrets.token_urlsafe(32)
    db.add(FftKey(name=name[:60], key_hash=digest(key), actor=actor, scopes=sorted(set(scopes or SCOPES[actor]) & SCOPES[actor])))
    return key
