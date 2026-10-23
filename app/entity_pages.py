"""Routes for entity pages (/campaign/<id>) and @-mention suggestions.

Like the review page, actions are HTMX requests that return the re-rendered
entity body plus a toast; without HTMX they redirect back to the page.
"""

import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app import access, atlas, entities, pictures, relations
from app.auth import can_edit_entries, can_moderate, current_user, is_dm, is_reviewer
from app.db import get_db
from app.extraction import ExtractionError
from app.linking import entity_linker
from app.models import Entity, EntityAlias, EntityPicture, Fact, Status
from app.templating import templates

router = APIRouter(prefix="/campaign")


def _visible(entity: Entity | None, user: dict | None) -> bool:
    """Published (hidden ones for the DM, reviewers and admins), and in the campaign you're in."""
    here = access.current_campaign()
    return (entity is not None and (entity.status == Status.PUBLISHED or is_reviewer(user))
            and (here is None or entity.campaign_id == here["id"]))


def _not_found(request: Request):
    return web.not_found(request, "That page isn't in the campaign record.")


def entity_context(db: Session, entity: Entity, user: dict) -> dict:
    reviewer = is_reviewer(user)
    moderator = can_moderate(user)  # decides on facts from the table
    facts = list(db.scalars(select(Fact).where(Fact.entity_id == entity.id).order_by(Fact.id)))
    email = (user.get("email") or "").lower()
    others = [
        e
        for e in db.scalars(select(Entity).where(Entity.campaign_id == entity.campaign_id, Entity.id != entity.id).order_by(Entity.name))
        if e.status == Status.PUBLISHED or reviewer
    ]
    return {
        "e": entity,
        "can_edit": can_edit_entries(user),
        "kind_label": entities.KIND_LABELS.get(entity.kind, entity.kind.value),
        "merged": [f for f in facts if f.status == "merged"],
        "pending": [f for f in facts if f.status == "pending"] if moderator else [],
        # A player's own suggestions here, with what happened to each (Waiting, Added, Used, Not used)
        "mine": [f for f in facts if f.author_email.lower() == email] if not moderator else [],
        "done_facts": sorted((f for f in facts if f.status != "pending"), key=lambda f: f.updated_at, reverse=True) if moderator else [],
        "finished": [f for f in facts if f.status == "done"],  # worked into the description or marked Done
        "relations": relations.lines_for(db, entity),
        "rel_choices": relations.CHOICES,
        "others": others,
        "moments": entities.moments(db, entity),
        "ln": entity_linker(db, entity.campaign_id, exclude_id=entity.id, include_drafts=reviewer),
        "picture": pictures.urls(db, [entity.id]).get(entity.id),
        "can_picture": pictures.can_manage(user),
        "map_marker": atlas.entity_marker(entity),
        "kinds": [(k.value, label) for k, label in entities.KIND_LABELS.items() if k.value != "pc"],
        "sessions": _sessions(db, entity.campaign_id) if can_edit_entries(user) else [],
    }


def _sessions(db: Session, campaign_id: int) -> list[tuple[int, str]]:
    """Sessions to put a new key moment in, newest first."""
    from app.extraction import session_label, timeline

    return [(s.id, session_label(s)) for s in reversed(timeline(db, campaign_id))]


@router.get("/{entity_id:int}")
def entity_page(request: Request, entity_id: int, db: Session = Depends(get_db)):
    """No full page any more (Brett, 2026-10-22): a link to an entry opens the Campaign page with its side panel."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    return RedirectResponse(f"{web.base()}/campaign?open={entity_id}", status_code=303)


@router.get("/new")
def new_entry_form(request: Request, kind: str = "npc", db: Session = Depends(get_db)):
    """The DM's "+ New": a small window to add a person, place, faction, item, quest or creature by hand."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_edit_entries(user):
        return web.forbidden(request, "Only the DM, reviewers and admins add entries.")
    kinds = [(k.value, label) for k, label in entities.KIND_LABELS.items() if k.value != "pc"]
    return templates.TemplateResponse(request, "_entity_new.html", {"kinds": kinds, "kind": kind, "error": "", "form": {}})


@router.post("/new")
def new_entry(request: Request, kind: str = Form(""), name: str = Form(""), summary: str = Form(""), hidden: str = Form(""),
              db: Session = Depends(get_db)):
    user = current_user(request)
    if not user or not can_edit_entries(user):
        return web.forbidden(request, "Only the DM, reviewers and admins add entries.")
    campaign = web.campaign(db)
    try:
        entity = entities.create(db, campaign.id, kind, name, summary, published=not hidden, by=web.person_name(user))
        db.commit()
    except entities.EntityError as e:
        db.rollback()
        kinds = [(k.value, label) for k, label in entities.KIND_LABELS.items() if k.value != "pc"]
        return templates.TemplateResponse(request, "_entity_new.html", {"kinds": kinds, "kind": kind, "error": str(e),
                                                                        "form": {"name": name, "summary": summary, "hidden": hidden}})
    return Response(status_code=204, headers={"HX-Redirect": f"{web.base()}/campaign?open={entity.id}"})


@router.get("/{entity_id:int}/peek")
def entity_peek(request: Request, entity_id: int, db: Session = Depends(get_db)):
    """The side panel: everything about one entry, the table's facts and the form to add one."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    return templates.TemplateResponse(request, "_peek.html", entity_context(db, entity, user))


@router.get("/{entity_id:int}/read")
def entity_read(request: Request, entity_id: int, db: Session = Depends(get_db)):
    """The Campaign page's Reader: one entry on the page, swapped in when you pick a name or a quest."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    return templates.TemplateResponse(request, "_peek.html", {**entity_context(db, entity, user), "where": "reader"})


@router.get("/{entity_id:int}/edit")
def entity_edit(request: Request, entity_id: int, db: Session = Depends(get_db)):
    """The large window for the DM, reviewers and admins: names, description, relationships, picture, facts."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    if not can_edit_entries(user):
        return web.forbidden(request, "Only the DM, reviewers and admins edit campaign entries.")
    return templates.TemplateResponse(request, "_entity_edit.html", entity_context(db, entity, user))


def _act(request: Request, db: Session, entity_id: int, action: Callable[[Entity, dict], str], reviewer_only: bool = True,
         allowed: Callable[[dict], bool] = can_edit_entries):
    """Run an entity action, commit, and answer with what was showing: the side panel (?in=panel) or the edit
    window's body."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if reviewer_only and not allowed(user):
        return web.forbidden(request, "Only the DM, reviewers and admins can do that.")
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    try:
        message = action(entity, user)
        db.commit()
    except (entities.EntityError, relations.RelationError, ExtractionError) as e:
        db.rollback()
        message = str(e)
    db.expire_all()
    entity = db.get(Entity, entity_id)
    if entity is None:  # e.g. removed while acting
        return RedirectResponse("/campaign", status_code=303)
    if request.headers.get("HX-Request"):
        where = request.query_params.get("in", "")  # the side panel, the Campaign page's Reader, or the edit window
        context = {**entity_context(db, entity, user), "where": where}
        response = templates.TemplateResponse(request, "_peek.html" if where in ("panel", "reader") else "_entity_body.html", context)
        response.headers["HX-Trigger"] = json.dumps({"toast": message})
        return response
    request.session["toast"] = message
    return RedirectResponse(f"{web.base()}/campaign?open={entity_id}", status_code=303)


@router.post("/{entity_id:int}/facts")
def add_fact(request: Request, entity_id: int, text: str = Form(""), kind: str = Form("addition"), db: Session = Depends(get_db)):
    def act(entity, user):
        entities.add_fact(db, entity, text, user, kind=kind, merged=is_dm(user))
        if is_dm(user):
            return "Added to the page"
        return "Fact saved" if can_moderate(user) else "Thanks! The DM or a reviewer will add it to the page."

    return _act(request, db, entity_id, act, reviewer_only=False)


def _fact_action(request: Request, db: Session, fact_id: int, fn: Callable[[Fact], str]):
    fact = db.get(Fact, fact_id)
    if fact is None:
        return RedirectResponse("/campaign", status_code=303)
    return _act(request, db, fact.entity_id, lambda entity, user: fn(fact), allowed=can_moderate)


# --- Pictures (the DM, reviewers and admins) ------------------------------------------


@router.get("/{entity_id:int}/picture")
def picture(request: Request, entity_id: int, size: str = "full", db: Session = Depends(get_db)):
    user = current_user(request)
    entity = db.get(Entity, entity_id)
    pic = db.scalar(select(EntityPicture).where(EntityPicture.entity_id == entity_id)) if user and _visible(entity, user) else None
    if pic is None:
        return Response(status_code=404)
    # URLs carry ?v=<updated time>, so a browser can keep a copy until the picture changes.
    return Response(pic.thumb if size == "thumb" else pic.data, media_type=pic.content_type,
                    headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


def _picture_action(request: Request, db: Session, entity_id: int, fn: Callable[[Entity, dict], str]):
    def act(entity, user):  # refusals happen before anything is written, so there's nothing to roll back
        if not pictures.can_manage(user):
            return "Only the DM and reviewers can change pictures."
        try:
            return fn(entity, user)
        except pictures.PictureError as e:
            return str(e)

    return _act(request, db, entity_id, act, reviewer_only=False)


@router.post("/{entity_id:int}/picture")
def upload_picture(request: Request, entity_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = file.file.read(pictures.MAX_UPLOAD + 1)
    return _picture_action(request, db, entity_id, lambda entity, user: pictures.save(db, entity, raw, user) and "Picture saved")


@router.post("/{entity_id:int}/picture/delete")
def delete_picture(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _picture_action(request, db, entity_id, lambda entity, user: pictures.remove(db, entity) or "Picture removed")


@router.post("/facts/{fact_id:int}/merge")
def merge_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.merge_fact(f) or "Added to the page")


@router.post("/facts/{fact_id:int}/reject")
def reject_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.reject_fact(f) or "Dismissed")


@router.post("/facts/{fact_id:int}/done")
def done_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.done_fact(f) or "Marked Done")


@router.post("/facts/{fact_id:int}/undo")
def undo_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.undo_fact(f) or "Undone")


@router.post("/{entity_id:int}/description/regenerate")
def regenerate(request: Request, entity_id: int, db: Session = Depends(get_db)):
    def act(entity, user):
        entities.regenerate(db, entity)
        return "Claude drafted a new description"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/description/accept")
def accept_description(request: Request, entity_id: int, summary: str | None = Form(None), db: Session = Depends(get_db)):
    def act(entity, user):
        entities.accept_description(entity, summary, by=web.person_name(user))
        return "Description updated"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/description")
def set_description(request: Request, entity_id: int, summary: str = Form(""), db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.set_description(entity, summary, by=web.person_name(user)) or "Description saved")


@router.post("/{entity_id:int}/name")
def rename(request: Request, entity_id: int, name: str = Form(""), db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.rename(entity, name) or "Renamed")


@router.post("/{entity_id:int}/details")
def set_details(request: Request, entity_id: int, kind: str = Form(...), quest_open: str = Form("open"), published: str = Form(""),
                db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.set_details(entity, kind, quest_open, bool(published)) or "Saved")


@router.post("/{entity_id:int}/quest")
def set_quest(request: Request, entity_id: int, open: str = Form("1"), db: Session = Depends(get_db)):
    """Mark done or Reopen, from the quest in the Reader."""
    return _act(request, db, entity_id, lambda entity, user: entities.set_quest_open(entity, open == "1"))


@router.post("/{entity_id:int}/moments")
def add_moment(request: Request, entity_id: int, session_id: int = Form(0), kind: str = Form("event"), text: str = Form(""),
               db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.add_moment(db, entity, session_id, kind, text) and "Key moment added")


def _leave(request: Request, db: Session, entity_id: int, fn: Callable[[Entity], tuple[str, str]]):
    """Delete or merge: the entry is gone, so go back to the Campaign page (or the entry it was merged into)."""
    user = current_user(request)
    if not user or not can_edit_entries(user):
        return web.forbidden(request, "Only the DM, reviewers and admins can do that.")
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    try:
        message, url = fn(entity)
        db.commit()
    except entities.EntityError as e:
        db.rollback()
        return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": str(e)})})
    request.session["toast"] = message
    return Response(status_code=204, headers={"HX-Redirect": url})


@router.post("/{entity_id:int}/delete")
def delete_entry(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _leave(request, db, entity_id, lambda e: (f"Deleted {entities.delete(db, e)}. Manage › History can bring it back.", "/campaign"))


@router.post("/{entity_id:int}/merge")
def merge_entry(request: Request, entity_id: int, into: int = Form(0), db: Session = Depends(get_db)):
    def act(source):
        target = db.get(Entity, into)
        if target is None:
            raise entities.EntityError("Pick the entry to keep.")
        name = source.name
        entities.merge(db, source, target)
        return f"Merged {name} into {target.name}", f"{web.base()}/campaign?open={target.id}"

    return _leave(request, db, entity_id, act)


@router.post("/{entity_id:int}/description/discard")
def discard_description(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.discard_description(entity) or "Discarded")


@router.post("/{entity_id:int}/description/undo")
def undo_description(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.undo_description(entity) or "Restored the earlier description")


@router.post("/{entity_id:int}/aliases")
def add_alias(request: Request, entity_id: int, alias: str = Form(...), misspelling: str = Form(""), db: Session = Depends(get_db)):
    def act(entity, user):
        text = " ".join(alias.split())
        if not text or text.casefold() == entity.name.casefold():
            raise entities.EntityError("Enter a different name or spelling.")
        if any(a.alias.casefold() == text.casefold() for a in entity.aliases):
            raise entities.EntityError("That name is already listed.")
        entity.aliases.append(EntityAlias(alias=text, misspelling=bool(misspelling)))
        return "Added"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/aliases/{alias_id:int}/toggle")
def toggle_alias(request: Request, entity_id: int, alias_id: int, db: Session = Depends(get_db)):
    def act(entity, user):
        a = next((x for x in entity.aliases if x.id == alias_id), None)
        if a is None:
            raise entities.EntityError("That name is gone.")
        a.misspelling = not a.misspelling
        return "Marked as a misspelling" if a.misspelling else "Marked as another name"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/aliases/{alias_id:int}/delete")
def delete_alias(request: Request, entity_id: int, alias_id: int, db: Session = Depends(get_db)):
    def act(entity, user):
        a = next((x for x in entity.aliases if x.id == alias_id), None)
        if a is not None:
            entity.aliases.remove(a)
        return "Removed"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/relationships")
def add_relationship(
    request: Request, entity_id: int, type: str = Form(...), other_id: int = Form(...), note: str = Form(""), db: Session = Depends(get_db)
):
    def act(entity, user):
        other = db.get(Entity, other_id)
        if other is None:
            raise relations.RelationError("Pick who or what it's related to.")
        _, created = relations.add(db, entity, type, other, note)
        return "Relationship added" if created else "That relationship is already there"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/relationships/{rel_id:int}/delete")
def delete_relationship(request: Request, entity_id: int, rel_id: int, db: Session = Depends(get_db)):
    from app.models import EntityRelation

    def act(entity, user):
        rel = db.get(EntityRelation, rel_id)
        if rel and entity.id in (rel.from_entity_id, rel.to_entity_id):
            db.delete(rel)
        return "Relationship removed"

    return _act(request, db, entity_id, act)


@router.get("/mentions")
def mentions(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Name suggestions for "@" in text boxes: [{name, kind, via}]."""
    user = current_user(request)
    if not user:
        return JSONResponse([], status_code=401)
    campaign = web.campaign(db)
    if campaign is None:
        return JSONResponse([])
    return JSONResponse(entities.mention_suggestions(db, campaign.id, q[:60], include_drafts=is_reviewer(user)))
