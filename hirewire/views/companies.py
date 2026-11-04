"""Companies: the list, a company's page with its applications, and editing it."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy.orm import selectinload

from .. import companies, db
from ..auth import login_required
from ..models import Application, Company, Contact
from ..ownership import get_mine, mine

bp = Blueprint("companies", __name__, url_prefix="/companies")


@bp.get("/")
@login_required
def index():
    words = request.args.get("q", "").strip()[:100]
    rows = companies.with_counts(db.session(), g.user.id, words)
    return render_template("companies/list.html", rows=rows, words=words)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    errors, values = {}, {}
    if request.method == "POST":
        values, errors = companies.read_form(request.form)
        if not errors:
            s = db.session()
            company = Company(user_id=g.user.id)
            errors = companies.save(s, company, values, g.user.id)
            if not errors:
                s.add(company)
                s.commit()
                flash("The company has been added.")
                return redirect(url_for("companies.detail", company_id=company.id))
    return render_template("companies/form.html", values=values, errors=errors, company=None), 400 if errors else 200


@bp.get("/<int:company_id>")
@login_required
def detail(company_id):
    company = get_mine(Company, company_id,
                       selectinload(Company.applications).selectinload(Application.company))
    jobs = sorted(company.applications, key=lambda job: job.updated_at, reverse=True)
    people = db.session().scalars(mine(Contact).where(Contact.company_id == company.id).order_by(Contact.name)).all()
    return render_template("companies/detail.html", company=company, jobs=jobs, people=people)


@bp.route("/<int:company_id>/edit", methods=["GET", "POST"])
@login_required
def edit(company_id):
    company = get_mine(Company, company_id)
    errors = {}
    values = {name: getattr(company, name) for name in ("name", "website", "industry", "location", "notes")}
    if request.method == "POST":
        values, errors = companies.read_form(request.form)
        if not errors:
            errors = companies.save(db.session(), company, values, g.user.id)
            if not errors:
                db.session().commit()
                flash("Your changes have been saved.")
                return redirect(url_for("companies.detail", company_id=company.id))
    return render_template("companies/form.html", values=values, errors=errors, company=company), 400 if errors else 200


@bp.post("/<int:company_id>/delete")
@login_required
def delete(company_id):
    company = get_mine(Company, company_id, selectinload(Company.applications))
    if company.applications:
        flash("This company still has applications. Delete or move them first.")
        return redirect(url_for("companies.detail", company_id=company.id))
    s = db.session()
    s.delete(company)
    s.commit()
    flash("The company has been deleted.")
    return redirect(url_for("companies.index"))
