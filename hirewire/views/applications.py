"""Applications: the list, adding and editing one, its page, and its notes."""
from dataclasses import replace
from urllib.parse import parse_qsl

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import contains_eager, selectinload, undefer
from werkzeug.datastructures import MultiDict

from .. import applications, auth, companies, db, filters, forms, workflow
from ..auth import login_required
from ..dates import local_today, utcnow
from ..models import (
    ACTIVE_STAGES, CONTACT_ROLES, CURRENCIES, SAVED, SOURCES, STAGE_LABELS, STAGES, WORK_MODES, Application,
    ApplicationContact, Contact, Document, Note, SavedView,
)
from ..ownership import get_child, get_mine, mine

bp = Blueprint("applications", __name__, url_prefix="/applications")


def get_job(job_id):
    return get_mine(Application, job_id, selectinload(Application.company), selectinload(Application.notes),
                    selectinload(Application.stage_changes), selectinload(Application.interviews),
                    selectinload(Application.follow_ups), undefer(Application.job_description),
                    selectinload(Application.contact_links).selectinload(ApplicationContact.contact),
                    selectinload(Application.resume), selectinload(Application.cover_letter))


def my_documents():
    return db.session().scalars(mine(Document).order_by(Document.name, Document.created_at.desc())).all()


def document_choices(kind):
    return [("", "None")] + [(str(doc.id), doc.title) for doc in my_documents() if doc.kind in (kind, "other")]


def form_page(template_values, errors, job=None):
    return render_template(
        "applications/form.html", values=template_values, errors=errors, job=job,
        company_names=companies.names(db.session(), g.user.id),
        stages=[(stage, STAGE_LABELS[stage]) for stage in ACTIVE_STAGES],
        work_modes=[("", "Not sure")] + list(WORK_MODES.items()),
        sources=[("", "Not sure")] + [(source, source) for source in SOURCES],
        currencies=[(currency, currency) for currency in CURRENCIES],
        resumes=document_choices("resume"), cover_letters=document_choices("cover_letter"),
    ), 400 if errors else 200


@bp.get("/")
@login_required
def index():
    s = db.session()
    f = filters.parse_filters(request.args)
    query = filters.apply_filters(mine(Application).join(Application.company), f, local_today(g.user.timezone))
    total = s.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    pages = max(1, -(-total // filters.PER_PAGE))  # rounded up
    if f.page > pages:
        f = replace(f, page=pages)
    jobs = s.scalars(query.options(contains_eager(Application.company))
                     .limit(filters.PER_PAGE).offset((f.page - 1) * filters.PER_PAGE)).all()
    views = s.scalars(mine(SavedView).order_by(SavedView.created_at, SavedView.id)).all()
    return render_template(
        "applications/list.html", jobs=jobs, f=f, total=total, pages=pages, views=views,
        here=filters.view_query(request.args), chips=filters.chips(f), filtered=filters.is_filtered(f),
        stage_choices=[(stage, STAGE_LABELS[stage]) for stage in STAGES],
        sources=SOURCES, sorts=filters.SORTS, per_page=filters.PER_PAGE,
        interview_choices=filters.INTERVIEW_CHOICES, to_args=filters.to_args, sort_link=filters.sort_link)


@bp.post("/views")
@login_required
def save_view():
    """Name the filters the page shows now. The same name again replaces the old view."""
    s = db.session()
    name, problem = forms.text(request.form, "name", filters.VIEW_NAME_LIMIT, required=True, label="A name")
    query = filters.view_query(MultiDict(parse_qsl(request.form.get("query", ""))))
    if problem:
        flash(problem)
        return redirect(url_for("applications.index") + ("?" + query if query else ""))
    view = s.scalar(mine(SavedView).where(SavedView.name == name))
    if view is None:
        view = SavedView(user_id=g.user.id, name=name)
        s.add(view)
    view.query = query
    s.commit()
    flash(f'Saved the view "{name}".')
    return redirect(url_for("applications.index") + ("?" + query if query else ""))


@bp.post("/views/<int:view_id>/delete")
@login_required
def delete_view(view_id):
    s = db.session()
    view = get_mine(SavedView, view_id)
    s.delete(view)
    s.commit()
    flash(f'Deleted the view "{view.name}".')
    return redirect(url_for("applications.index"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "GET":
        # Quick add and the company page fill some fields in through the address.
        start = {name: request.args.get(name, "") for name in ("company_name", "role_title")}
        return form_page({"stage": "applied", "currency": "PHP", **start}, {})
    values, errors = applications.read_form(request.form, is_new=True,
                                            document_ids={doc.id for doc in my_documents()})
    if errors:
        return form_page(request.form, errors)
    s = db.session()
    moment = utcnow()
    job = Application(user_id=g.user.id, created_at=moment)
    if values["stage"] != SAVED and not values["applied_on"]:
        values["applied_on"] = local_today(g.user.timezone, moment)
    applications.apply_form(s, job, values, g.user.id, moment)
    s.add(job)
    workflow.start(s, job, values["stage"], moment, user=g.user)
    s.commit()
    flash("The application has been added.")
    return redirect(url_for("applications.detail", job_id=job.id))


@bp.get("/<int:job_id>")
@login_required
def detail(job_id):
    job = get_job(job_id)
    forward, endings, back = workflow.group_moves(job.stage, workflow.came_from(db.session(), job))
    moment = utcnow()
    linked = {link.contact_id for link in job.contact_links}
    people = [person for person in db.session().scalars(mine(Contact).order_by(Contact.name)) if person.id not in linked]
    return render_template("applications/detail.html", job=job, timeline=applications.timeline(job),
                           forward=forward, endings=endings, back=back, now=moment,
                           today=local_today(g.user.timezone, moment), people=people,
                           roles=list(CONTACT_ROLES.items()))


def wants_json():
    return request.accept_mimetypes.best == "application/json"


@bp.post("/<int:job_id>/move")
@login_required
def move(job_id):
    """A stage button on the application's page, or a drag on the Board (which wants JSON back)."""
    job = get_job(job_id)
    s = db.session()
    source = "board" if request.form.get("from") == "board" else "manual"
    note, _ = forms.text(request.form, "note", 500)
    try:
        workflow.move(s, job, request.form.get("to", ""), g.user, utcnow(), note=note, source=source)
    except workflow.MoveNotAllowed as problem:
        s.rollback()
        if wants_json():
            return jsonify(error=str(problem)), 409
        flash(str(problem))
    else:
        s.commit()
        if wants_json():
            return jsonify(stage=job.stage, label=job.stage_label,
                           moves=workflow.allowed_moves(job.stage, workflow.came_from(s, job)))
        flash(f"Moved to {job.stage_label}.")
    return redirect(auth.safe_next(request.form.get("next"), url_for("applications.detail", job_id=job.id)))


@bp.route("/<int:job_id>/edit", methods=["GET", "POST"])
@login_required
def edit(job_id):
    job = get_job(job_id)
    if request.method == "GET":
        return form_page(applications.form_values(job), {}, job)
    values, errors = applications.read_form(request.form, is_new=False,
                                            document_ids={doc.id for doc in my_documents()})
    if errors:
        return form_page(request.form, errors, job)
    applications.apply_form(db.session(), job, values, g.user.id, utcnow())
    db.session().commit()
    flash("Your changes have been saved.")
    return redirect(url_for("applications.detail", job_id=job.id))


@bp.post("/<int:job_id>/delete")
@login_required
def delete(job_id):
    s = db.session()
    s.delete(get_job(job_id))
    s.commit()
    flash("The application has been deleted.")
    return redirect(url_for("applications.index"))


# ---------- Notes ----------

@bp.post("/<int:job_id>/notes")
@login_required
def add_note(job_id):
    job = get_job(job_id)
    body, problem = forms.text(request.form, "body", 5000, required=True, label="A note")
    if problem:
        flash(problem)
    else:
        moment = utcnow()
        db.session().add(Note(application=job, body=body, created_at=moment))
        job.updated_at = moment
        db.session().commit()
    return redirect(url_for("applications.detail", job_id=job.id) + "#timeline")


@bp.post("/notes/<int:note_id>/delete")
@login_required
def delete_note(note_id):
    note = get_child(Note, note_id)
    job_id = note.application_id
    s = db.session()
    s.delete(note)
    s.commit()
    flash("The note has been deleted.")
    return redirect(url_for("applications.detail", job_id=job_id) + "#timeline")
