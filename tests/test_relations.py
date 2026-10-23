import pytest
from sqlalchemy import select

from app import campaign_views, relations
from app.extraction import _known_world, store_result
from app.importer import import_bundle
from app.models import Campaign, Entity, EntityRelation, ExtractionRun, GameSession, Proposal
from app.review import ReviewError, accept_proposal, undo_proposal
from tests.test_entities import HX, admin, player  # noqa: F401  (fixtures)

FAMILY = {
    "campaign": {"slug": "main", "name": "Main"},
    "entities": [
        {"kind": "npc", "name": n}
        for n in ("Aldric", "Mira", "Kiera", "Tomas", "Orrin", "Pip", "Bram")
    ]
    + [{"kind": "faction", "name": "Tidewardens"}],
    "sessions": [{"number": 1}],
}


def ents(db):
    return {e.name: e for e in db.scalars(select(Entity))}


def family(db):
    import_bundle(db, FAMILY)
    E = ents(db)
    for a, t, b in [
        ("Aldric", "married_to", "Mira"), ("Aldric", "parent_of", "Kiera"), ("Mira", "parent_of", "Kiera"),
        ("Aldric", "parent_of", "Tomas"), ("Orrin", "married_to", "Kiera"), ("Kiera", "parent_of", "Pip"),
        ("Orrin", "parent_of", "Pip"), ("Bram", "parent_of", "Orrin"),
    ]:
        relations.add(db, E[a], t, E[b])
    return E


def test_add_dedupes_and_inverse_choice(db):
    E = family(db)
    _, created = relations.add(db, E["Mira"], "married_to", E["Aldric"])  # symmetric, already there
    assert not created
    rel, created = relations.add(db, E["Tomas"], "~parent_of", E["Mira"])  # "Tomas is child of Mira"
    assert created and (rel.from_entity_id, rel.type, rel.to_entity_id) == (E["Mira"].id, "parent_of", E["Tomas"].id)
    with pytest.raises(relations.RelationError):
        relations.add(db, E["Tomas"], "parent_of", E["Tomas"])
    with pytest.raises(relations.RelationError):
        relations.add(db, E["Tomas"], "best_friend", E["Mira"])


def test_lines_show_inverses(db):
    E = family(db)
    relations.add(db, E["Kiera"], "member_of", E["Tidewardens"])
    kiera = [(l.label, l.other.name) for l in relations.lines_for(db, E["Kiera"])]
    assert ("child of", "Aldric") in kiera and ("parent of", "Pip") in kiera and ("married to", "Orrin") in kiera
    assert ("has member", "Kiera") in [(l.label, l.other.name) for l in relations.lines_for(db, E["Tidewardens"])]
    assert "Kiera member of Tidewardens" in _known_world(db, db.scalar(select(Campaign)))


def test_family_trees(db):
    """The Relationships tab (Brett 2026-10-22, R1): one tree per family, generations in rows, children by parents."""
    E = family(db)
    fams = campaign_views.families(db, db.scalar(select(Campaign)).id, lambda e: True)
    assert len(fams) == 1 and fams[0].name == "Aldric and Mira's family"
    rows = [[([p.name for p in g.parents], [p.name for p in g.people]) for g in row] for row in fams[0].rows]
    assert rows == [
        [([], ["Aldric", "Mira", "Bram"])],  # married couples side by side
        [(["Aldric", "Mira"], ["Kiera"]), (["Bram"], ["Orrin"]), (["Aldric"], ["Tomas"])],  # Kiera and Orrin are married: side by side
        [(["Kiera", "Orrin"], ["Pip"])],
    ]
    assert [s.name for s in fams[0].spouses[E["Kiera"].id]] == ["Orrin"]


def test_unmarried_coparents_share_a_row_and_hidden_people_stay_out(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [
        {"kind": "npc", "name": "Bhal"}, {"kind": "npc", "name": "Terra"}, {"kind": "pc", "name": "Big C"}, {"kind": "npc", "name": "Alea"}]})
    E = ents(db)
    for a, b in (("Bhal", "Big C"), ("Terra", "Big C"), ("Alea", "Terra")):
        relations.add(db, E[a], "parent_of", E[b])
    cid = db.scalar(select(Campaign)).id
    rows = campaign_views.families(db, cid, lambda e: True)[0].rows
    assert [[p.name for g in row for p in g.people] for row in rows] == [["Alea"], ["Bhal", "Terra"], ["Big C"]]
    rows = campaign_views.families(db, cid, lambda e: e.name != "Alea")[0].rows
    assert [[p.name for g in row for p in g.people] for row in rows] == [["Bhal", "Terra"], ["Big C"]]


def drafted(db, rels):
    s = db.scalar(select(GameSession))
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, {
        "title": "", "recap": "R.", "events": [], "glossary": [], "to_check": [], "relationships": rels,
        "entities": [{"name": "Wren", "kind": "npc", "summary": "Orrin's sister.", "aliases": [], "quest_status": "not_a_quest"}],
    })
    db.flush()
    return s


def test_extraction_proposes_new_relationships_only(db):
    family(db)
    drafted(db, [
        {"from": "Kiera", "type": "married_to", "to": "Orrin", "note": ""},  # known (reverse direction)
        {"from": "Wren", "type": "sibling_of", "to": "Orrin", "note": ""},  # Wren is new
        {"from": "Orrin", "type": "sibling_of", "to": "Wren", "note": ""},  # same thing again
        {"from": "Tomas", "type": "enemy_of", "to": "Tidewardens", "note": "after the fire"},
        {"from": "Tomas", "type": "nonsense", "to": "Pip", "note": ""},
    ])
    props = [p.payload for p in db.scalars(select(Proposal).where(Proposal.kind == "relationship"))]
    assert [(p["from_name"], p["type"], p["to_name"]) for p in props] == [
        ("Wren", "sibling_of", "Orrin"), ("Tomas", "enemy_of", "Tidewardens")]
    assert props[0]["from_id"] is None and props[1]["note"] == "after the fire"


def test_accept_relationship_after_its_entity_and_undo(db):
    family(db)
    drafted(db, [{"from": "Wren", "type": "sibling_of", "to": "Orrin", "note": ""}])
    rel_p = db.scalar(select(Proposal).where(Proposal.kind == "relationship"))
    with pytest.raises(ReviewError, match="Accept Wren first"):
        accept_proposal(db, rel_p)
    accept_proposal(db, db.scalar(select(Proposal).where(Proposal.kind == "entity")))
    db.flush()
    accept_proposal(db, rel_p)
    db.flush()
    rel = db.scalar(select(EntityRelation).where(EntityRelation.type == "sibling_of"))
    assert rel.from_entity.name == "Wren" and rel.to_entity.name == "Orrin"
    undo_proposal(db, rel_p)
    db.flush()
    assert db.scalar(select(EntityRelation).where(EntityRelation.type == "sibling_of")) is None
    assert rel_p.status == "pending"


def test_review_page_shows_relationship_suggestion(admin, db):  # noqa: F811
    family(db)
    s = drafted(db, [{"from": "Tomas", "type": "enemy_of", "to": "Tidewardens", "note": ""}])
    page = admin.get(f"/c/main/manage/sessions/{s.id}").text
    assert "Relationship" in page and "enemy of" in page


def test_entity_page_relationship_editing(admin, player, db):  # noqa: F811
    E = family(db)
    page = admin.get(f"/campaign/{E['Kiera'].id}/edit").text
    assert "Child of" in page and "Add relationship" in page
    admin.post(f"/campaign/{E['Tomas'].id}/relationships", data={"type": "member_of", "other_id": E["Tidewardens"].id}, headers=HX)
    rel = db.scalar(select(EntityRelation).where(EntityRelation.type == "member_of"))
    assert rel.from_entity_id == E["Tomas"].id
    admin.post(f"/campaign/{E['Tomas'].id}/relationships/{rel.id}/delete", headers=HX)
    assert db.scalar(select(EntityRelation).where(EntityRelation.type == "member_of")) is None
    page = admin.get("/c/main/campaign?tab=relationships").text
    assert '<div id="t-relationships">' in page and "Aldric and Mira&#39;s family" in page
    assert f'data-modal-url="/c/main/campaign/{E["Pip"].id}/connections"' in page  # anyone opens their connections
