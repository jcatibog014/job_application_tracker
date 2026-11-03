"""Interviews: reading the form."""
from . import forms
from .dates import parse_local
from .models import INTERVIEW_KINDS, OUTCOMES

LENGTHS = (15, 30, 45, 60, 90, 120, 180, 240)


def read_form(form, tz_name):
    """The interview form -> (values, errors). The time is read on the person's clock."""
    values, errors = {}, {}
    raw = (form.get("starts_at") or "").strip()
    try:
        values["starts_at"] = parse_local(raw, tz_name)
    except ValueError:
        values["starts_at"] = None
        errors["starts_at"] = "Choose the day and time." if not raw else "Use a date and time like 2026-11-12 14:00."
    minutes = form.get("minutes", "60")
    values["minutes"] = int(minutes) if minutes.isdigit() and int(minutes) in LENGTHS else 60
    values["kind"], problem = forms.choice(form, "kind", INTERVIEW_KINDS, default="video")
    if problem:
        errors["kind"] = problem
    values["outcome"], _ = forms.choice(form, "outcome", OUTCOMES, default="pending")
    for name, limit in (("with_whom", 200), ("place", 500), ("prep_notes", 10_000)):
        values[name], problem = forms.text(form, name, limit)
        if problem:
            errors[name] = problem
    return values, errors


def form_values(interview):
    return {name: getattr(interview, name) for name in
            ("starts_at", "minutes", "kind", "outcome", "with_whom", "place", "prep_notes")}
