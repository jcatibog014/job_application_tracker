"""Companies: one per name per person, made when first typed on an application."""
import re

from sqlalchemy import func, select

from . import forms
from .models import Application, Company


def name_key(name):
    """What makes two names the same company: "ACME  Inc " and "acme inc" match."""
    return re.sub(r"\s+", " ", name).strip().lower()


def find(s, user_id, name):
    return s.scalar(select(Company).where(Company.user_id == user_id, Company.name_key == name_key(name)))


def find_or_add(s, user_id, name):
    """The user's company with this name, made if it's new. The caller commits."""
    company = find(s, user_id, name)
    if company is None:
        company = Company(user_id=user_id, name=re.sub(r"\s+", " ", name).strip(), name_key=name_key(name))
        s.add(company)
        s.flush()
    return company


def read_form(form):
    """The company form -> (values, errors)."""
    values, errors = {}, {}
    for name, limit, required in (("name", 120, True), ("industry", 80, False), ("location", 120, False),
                                  ("notes", 5000, False)):
        values[name], problem = forms.text(form, name, limit, required, label="A name")
        if problem:
            errors[name] = problem
    values["website"], problem = forms.web_link(form, "website")
    if problem:
        errors["website"] = problem
    return values, errors


def save(s, company, values, user_id):
    """Apply the form; a clash with another company's name is an error. Returns errors."""
    other = find(s, user_id, values["name"])
    if other is not None and other is not company:
        return {"name": "You already have a company with this name."}
    for name, value in values.items():
        setattr(company, name, value)
    company.name_key = name_key(values["name"])
    return {}


def with_counts(s, user_id, words=""):
    """The user's companies with how many applications each has, by name.
    Returns a list of (company, count)."""
    count = func.count(Application.id)
    query = (select(Company, count).outerjoin(Application, Application.company_id == Company.id)
             .where(Company.user_id == user_id).group_by(Company.id).order_by(Company.name_key))
    if words:
        query = query.where(Company.name_key.contains(name_key(words), autoescape=True))
    return s.execute(query).all()


def names(s, user_id):
    """For the company box on the application form (a list it suggests from)."""
    return s.scalars(select(Company.name).where(Company.user_id == user_id).order_by(Company.name_key)).all()
