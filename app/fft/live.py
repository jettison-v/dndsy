"""Live updates for Found, Fixed, Tried: whenever a change to it commits (each writes an event, rules._event), every
open askdnd page hears "fft" through the live connection (app/realtime.py, to EVERYONE: the tool spans campaigns), and
a page showing Feedback, Testing, Notes you sent or a round's card shows its new copy in place (app.js). The message
says only that something changed: each page asks for what its person may see."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app import realtime
from app.fft.models import FftEvent


@event.listens_for(Session, "after_flush")
def _heard(db: Session, flush_context) -> None:
    if any(isinstance(x, FftEvent) for x in db.new) and not db.info.get("fft_announced"):
        db.info["fft_announced"] = True
        realtime.announce(db, realtime.EVERYONE, "fft")


@event.listens_for(Session, "after_commit")
def _reset(db: Session) -> None:
    db.info.pop("fft_announced", None)


@event.listens_for(Session, "after_soft_rollback")
def _reset_rollback(db: Session, previous_transaction) -> None:
    db.info.pop("fft_announced", None)
