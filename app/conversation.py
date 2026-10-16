"""Add Session: a written account of a session with no notes or recording,
checked by Claude against the sessions before and after, refined in a short
back-and-forth, then drafted like any other session."""

import json
from collections.abc import Callable

import anthropic
from sqlalchemy.orm import Session

from app.extraction import (
    MODEL,
    ExtractionError,
    _cost,
    _known_world,
    _story_after,
    _story_so_far,
    session_label,
)
from app.models import Campaign, ExtractionRun, GameSession, SessionMessage

CHECK_SYSTEM = """\
You help keep the campaign record for one Dungeons & Dragons (2024 rules) \
table. A reviewer (a player or the Dungeon Master) is writing up a session \
that has no notes or recording, from memory. Your job is to help them make \
the account complete and consistent before it's drafted into a recap.

Each time, read the whole conversation (later messages override earlier \
ones; the story may change as people remember more) and reply with:
- Gaps: what changed between the end of the previous session and the start \
of the next one that the account doesn't explain yet (where the party is, \
who is with them, items gained or lost, quests started or finished, how \
injuries or deaths happened).
- Contradictions with other sessions or with the known world.
- A few clarifying questions, most important first. Name the characters and \
places involved.

Keep it short and friendly: a few bullets or a numbered list, no headings. \
Don't repeat questions that have been answered. Never invent events; ask. \
When the account covers the gap well enough to draft, say so in one line \
and set ready to true (it's fine to still list optional extra details)."""

CHECK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "ready"],
    "properties": {
        "reply": {"type": "string", "description": "Markdown message to the reviewer"},
        "ready": {"type": "boolean", "description": "True when there's enough to draft the session"},
    },
}


def conversation_text(session: GameSession) -> str:
    """The account and the back-and-forth, oldest first, for prompts and drafting."""
    lines = []
    for m in session.messages:
        who = "Claude" if m.role == "claude" else (m.author or "Reviewer")
        lines.append(f"{who}:\n{m.body.strip()}")
    return "\n\n".join(lines)


def build_check_messages(db: Session, session: GameSession) -> list[dict]:
    campaign = db.get(Campaign, session.campaign_id)
    known = {"type": "text", "text": "<known_world>\n" + _known_world(db, campaign) + "\n</known_world>"}
    known["cache_control"] = {"type": "ephemeral"}
    return [
        {
            "role": "user",
            "content": [
                known,
                {"type": "text", "text": "<sessions_before>\n" + _story_so_far(db, session) + "\n</sessions_before>"},
                {"type": "text", "text": "<sessions_after>\n" + _story_after(db, session) + "\n</sessions_after>"},
                {
                    "type": "text",
                    "text": f"<session_being_added>{session_label(session)}"
                    f"{(': ' + session.title) if session.title else ''}</session_being_added>\n"
                    f"<conversation>\n{conversation_text(session)}\n</conversation>\n"
                    "Reply to the reviewer.",
                },
            ],
        }
    ]


def check(
    db: Session,
    session: GameSession,
    client_factory: Callable[[], anthropic.Anthropic] | None = None,
) -> SessionMessage:
    """Ask Claude to review the account so far; store and return its reply.
    The call's cost is recorded as an ExtractionRun with source "conversation"."""
    run = ExtractionRun(session_id=session.id, source="conversation", model=MODEL, status="running")
    db.add(run)
    db.commit()
    try:
        client = (client_factory or anthropic.Anthropic)()
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=8000,
            system=CHECK_SYSTEM,
            messages=build_check_messages(db, session),
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": CHECK_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined to answer this one. Try rewording your message.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        message = SessionMessage(session_id=session.id, role="claude", body=data["reply"].strip(), ready=bool(data["ready"]))
        db.add(message)
        run.status = "done"
        run.input_tokens = (response.usage.input_tokens or 0) + (response.usage.cache_read_input_tokens or 0) + (
            response.usage.cache_creation_input_tokens or 0
        )
        run.output_tokens = response.usage.output_tokens or 0
        run.cost_usd = _cost(response.usage)
        db.commit()
        return message
    except (ExtractionError, anthropic.APIError, json.JSONDecodeError, KeyError) as e:
        db.rollback()
        run = db.merge(run)
        run.status, run.error = "error", (str(e) or type(e).__name__)[:2000]
        db.commit()
        raise ExtractionError(run.error) from e
