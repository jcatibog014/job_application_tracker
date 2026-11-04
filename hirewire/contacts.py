"""Contacts: reading the form."""
import re

from . import forms

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE = re.compile(r"[0-9+()\-. ]{5,40}")


def read_form(form, company_ids):
    """The contact form -> (values, errors). company_ids are the user's own companies."""
    values, errors = {}, {}
    for name, limit, required in (("name", 120, True), ("job_title", 120, False), ("email", 200, False),
                                  ("phone", 40, False), ("notes", 5000, False)):
        values[name], problem = forms.text(form, name, limit, required, label="A name")
        if problem:
            errors[name] = problem
    if values["email"] and not EMAIL.fullmatch(values["email"]):
        errors["email"] = "Use an email address like name@example.com."
    if values["phone"] and not PHONE.fullmatch(values["phone"]):
        errors["phone"] = "Use digits, spaces and + ( ) - only."
    values["profile_url"], problem = forms.web_link(form, "profile_url")
    if problem:
        errors["profile_url"] = problem
    values["last_contacted_on"], problem = forms.day(form, "last_contacted_on")
    if problem:
        errors["last_contacted_on"] = problem
    company = form.get("company_id", "")
    values["company_id"] = int(company) if company.isdigit() and int(company) in company_ids else None
    return values, errors


def form_values(contact):
    values = {name: getattr(contact, name) for name in
              ("name", "job_title", "email", "phone", "profile_url", "notes", "company_id")}
    values["last_contacted_on"] = contact.last_contacted_on.isoformat() if contact.last_contacted_on else ""
    return values
