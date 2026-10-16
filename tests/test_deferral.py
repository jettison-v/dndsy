from sqlalchemy import select

from app import review
from app.extraction import store_result
from app.importer import import_bundle
from app.models import Correction, ExtractionRun, GameSession
from tests.test_entities import HX, admin, login, player  # noqa: F401  (fixtures)

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main", "dm_name": "Robin"},
    "members": [
        {"email": "player@example.com", "name": "Pat Doe", "role": "player"},
        {"email": "dm@example.com", "name": "Robin Smith", "role": "dm"},
    ],
    "entities": [
        {"kind": "pc", "name": "Thessa", "character": {"owner_email": "player@example.com", "player_name": "Jo"}},
        {"kind": "pc", "name": "Grumm", "character": {"player_name": "Sam"}},
    ],
    "sessions": [{"number": 7, "played_on": "2026-03-01"}],
}
QUESTIONS = ["Who paid the ferryman?", "Was the idol cursed?"]


def drafted(db):
    import_bundle(db, BUNDLE)
    s = db.scalar(select(GameSession))
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, {"title": "", "recap": "R.", "events": [], "entities": [], "glossary": [], "to_check": QUESTIONS})
    db.flush()
    return s


def test_ask_options_and_names(db):
    drafted(db)
    s = db.scalar(select(GameSession))
    assert review.ask_options(db, s.campaign_id) == [("Robin", "Dungeon Master"), ("Sam", "plays Grumm"), ("Jo", "plays Thessa")]
    pat = review.names_for(db, {"email": "player@example.com", "name": "Pat Doe"})
    assert {"player@example.com", "pat doe", "pat", "jo"} <= pat and "robin" not in pat
    assert "robin" in review.names_for(db, {"email": "dm@example.com", "name": "Robin Smith"})


def test_ask_moves_question_to_waiting_and_publishing_still_works(admin, db):  # noqa: F811
    s = drafted(db)
    r = admin.post(f"/admin/sessions/{s.id}/questions/ask", data={"q": QUESTIONS[0], "person": " Jo ", "note": "You were there"}, headers=HX)
    assert "Waiting on Jo" in r.text and "You were there" in r.text and "1 waiting" in r.text
    ctx = review.review_context(db, s, drafting=False)
    assert ctx["open_questions"] == [QUESTIONS[1]] and ctx["done_questions"] == []
    assert [(p, [c.before for c in cs]) for p, cs in ctx["waiting"]] == [("Jo", [QUESTIONS[0]])]
    row = db.scalar(select(Correction).where(Correction.kind == "ask"))
    assert row.asked_by == "Brett" and row.asked_of == "Jo"
    assert "Choose who to ask" in admin.post(f"/admin/sessions/{s.id}/questions/ask", data={"q": QUESTIONS[1], "person": ""}, headers=HX).headers["HX-Trigger"]
    admin.post(f"/admin/sessions/{s.id}/publish", headers=HX)
    assert "R." in admin.get("/").text


def test_askee_answers_from_previously_on(monkeypatch, db):
    s = drafted(db)
    review.ask_question(db, s, QUESTIONS[0], "Jo", "You were there", "Brett")
    review.ask_question(db, s, QUESTIONS[1], "Sam", "", "Brett")
    db.commit()  # so the request's commit/rollback doesn't discard the setup
    pat = login(monkeypatch, db, "player@example.com", "Pat Doe")
    home = pat.get("/").text
    assert "Questions for you" in home and QUESTIONS[0] in home and "You were there" in home
    assert QUESTIONS[1] not in home  # asked of Sam, not Pat
    row = db.scalar(select(Correction).where(Correction.before == QUESTIONS[0]))
    other = db.scalar(select(Correction).where(Correction.before == QUESTIONS[1]))
    assert pat.post(f"/questions/{other.id}/answer", data={"answer": "Not mine"}, follow_redirects=False).status_code == 303
    db.refresh(other)
    assert other.kind == "ask"  # can't answer someone else's
    pat.post(f"/questions/{row.id}/answer", data={"answer": "Grumm paid him.", "remember": "1"})
    db.refresh(row)
    assert (row.kind, row.after, row.standing_instruction, row.answered_by) == ("answer", "Grumm paid him.", True, "Pat Doe")
    assert "Questions for you" not in pat.get("/").text
    assert review.unused_answer_count(db, s) == 1  # the redraft prompt counts it like a reviewer's answer


def test_reviewer_records_answer_on_behalf(admin, db):  # noqa: F811
    s = drafted(db)
    review.ask_question(db, s, QUESTIONS[0], "Robin", "", "Brett")
    db.flush()
    r = admin.post(f"/admin/sessions/{s.id}/questions/answer", data={"q": QUESTIONS[0], "answer": "Grumm did.", "on_behalf_of": "Robin"}, headers=HX)
    assert "Answered by Robin" in r.text
    row = db.scalar(select(Correction).where(Correction.before == QUESTIONS[0]))
    assert row.kind == "answer" and row.answered_by == "Robin" and row.asked_of == "Robin"
    admin.post(f"/admin/sessions/{s.id}/questions/reopen", data={"q": QUESTIONS[0]}, headers=HX)
    assert QUESTIONS[0] in review.review_context(db, s, drafting=False)["open_questions"]
