"""Contacts: the people list, adding and editing a person, and linking people to applications."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from .. import auth, contacts, db
from ..auth import login_required
from ..dates import local_today
from ..models import CONTACT_ROLES, Application, ApplicationContact, Company, Contact
from ..ownership import get_mine, mine

bp = Blueprint("contacts", __name__, url_prefix="/contacts")


def my_companies():
    return db.session().execute(select(Company.id, Company.name).where(Company.user_id == g.user.id)
                                .order_by(Company.name_key)).all()


def form_page(values, errors, contact=None, job=None):
    return render_template("contacts/form.html", values=values, errors=errors, contact=contact, job=job,
                           companies=[("", "No company")] + [(str(id_), name) for id_, name in my_companies()]), \
        400 if errors else 200


@bp.get("/")
@login_required
def index():
    words = " ".join(request.args.get("q", "").split())[:100]
    company = request.args.get("company", "")
    query = (mine(Contact).outerjoin(Contact.company)
             .options(selectinload(Contact.company),
                      selectinload(Contact.application_links).selectinload(ApplicationContact.application))
             .order_by(Contact.name))
    if words:
        query = query.where(or_(Contact.name.icontains(words, autoescape=True),
                                Contact.job_title.icontains(words, autoescape=True),
                                Contact.email.icontains(words, autoescape=True),
                                Company.name.icontains(words, autoescape=True)))
    if company.isdigit():
        query = query.where(Contact.company_id == int(company))
    people = db.session().scalars(query).all()
    return render_template("contacts/list.html", people=people, words=words, company=company,
                           companies=my_companies(), today=local_today(g.user.timezone))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    # "Add a new person" on an application page brings its id, so the person is linked straight away.
    job_id = request.values.get("job", "")
    job = get_mine(Application, int(job_id)) if job_id.isdigit() else None
    if request.method == "GET":
        start = {"company_id": job.company_id if job else int(request.args.get("company", 0) or 0) or None}
        return form_page(start, {}, job=job)
    values, errors = contacts.read_form(request.form, {id_ for id_, _ in my_companies()})
    if errors:
        return form_page(request.form, errors, job=job)
    s = db.session()
    contact = Contact(user_id=g.user.id, **values)
    s.add(contact)
    if job:
        role = request.form.get("role") if request.form.get("role") in CONTACT_ROLES else "recruiter"
        s.add(ApplicationContact(application=job, contact=contact, role=role))
    s.commit()
    flash(f"{contact.name} has been added.")
    if job:
        return redirect(url_for("applications.detail", job_id=job.id) + "#people")
    return redirect(url_for("contacts.index"))


@bp.route("/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit(contact_id):
    contact = get_mine(Contact, contact_id)
    if request.method == "GET":
        return form_page(contacts.form_values(contact), {}, contact)
    values, errors = contacts.read_form(request.form, {id_ for id_, _ in my_companies()})
    if errors:
        return form_page(request.form, errors, contact)
    for name, value in values.items():
        setattr(contact, name, value)
    db.session().commit()
    flash("Your changes have been saved.")
    return redirect(url_for("contacts.index"))


@bp.post("/<int:contact_id>/contacted")
@login_required
def contacted_today(contact_id):
    contact = get_mine(Contact, contact_id)
    contact.last_contacted_on = local_today(g.user.timezone)
    db.session().commit()
    flash(f"Noted: you talked to {contact.name} today.")
    return redirect(auth.safe_next(request.form.get("next"), url_for("contacts.index")))


@bp.post("/<int:contact_id>/delete")
@login_required
def delete(contact_id):
    contact = get_mine(Contact, contact_id)
    s = db.session()
    s.delete(contact)
    s.commit()
    flash(f"{contact.name} has been deleted.")
    return redirect(url_for("contacts.index"))


# ---------- People on an application ----------

@bp.post("/link/<int:job_id>")
@login_required
def link(job_id):
    job = get_mine(Application, job_id)
    contact_id = request.form.get("contact_id", "")
    if not contact_id.isdigit():
        flash("Choose a person from the list.", "error")
        return redirect(url_for("applications.detail", job_id=job.id) + "#people")
    contact = get_mine(Contact, int(contact_id))
    role = request.form.get("role") if request.form.get("role") in CONTACT_ROLES else "other"
    s = db.session()
    existing = s.get(ApplicationContact, (job.id, contact.id))
    if existing:
        existing.role = role
    else:
        s.add(ApplicationContact(application=job, contact=contact, role=role))
    s.commit()
    return redirect(url_for("applications.detail", job_id=job.id) + "#people")


@bp.post("/unlink/<int:job_id>/<int:contact_id>")
@login_required
def unlink(job_id, contact_id):
    job = get_mine(Application, job_id)
    s = db.session()
    existing = s.get(ApplicationContact, (job.id, contact_id))
    if existing:
        s.delete(existing)
        s.commit()
    return redirect(url_for("applications.detail", job_id=job.id) + "#people")
