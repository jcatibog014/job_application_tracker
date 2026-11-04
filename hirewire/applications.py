"""Applications: reading the form, saving it, and the timeline on its page."""
from dataclasses import dataclass
from datetime import datetime

from . import companies, forms, workflow
from .models import ACTIVE_STAGES, CURRENCIES, OUTCOMES, SOURCES, WORK_MODES

TEXT_FIELDS = (
    # name, limit, required
    ("role_title", 150, True),
    ("location", 120, False),
    ("job_description", 20_000, False),
)


def read_form(form, is_new, document_ids=()):
    """The application form -> (values, errors). A new one also has its first stage.
    document_ids are the user's own files, the only ones it may point at."""
    values, errors = {}, {}

    def keep(name, result):
        values[name], problem = result
        if problem:
            errors[name] = problem

    keep("company_name", forms.text(form, "company_name", 120, required=True, label="A company"))
    for name, limit, required in TEXT_FIELDS:
        keep(name, forms.text(form, name, limit, required, label="A job title"))
    keep("posting_url", forms.web_link(form, "posting_url"))
    keep("work_mode", forms.choice(form, "work_mode", ("", *WORK_MODES)))
    keep("source", forms.choice(form, "source", ("", *SOURCES)))
    keep("currency", forms.choice(form, "currency", CURRENCIES, default="PHP"))
    keep("salary_min", forms.whole_number(form, "salary_min"))
    keep("salary_max", forms.whole_number(form, "salary_max"))
    keep("applied_on", forms.day(form, "applied_on"))
    if values["salary_min"] and values["salary_max"] and values["salary_min"] > values["salary_max"]:
        errors["salary_max"] = "The highest pay can't be less than the lowest."
    if is_new:
        keep("stage", forms.choice(form, "stage", ACTIVE_STAGES, default="applied"))
    for name in ("resume_id", "cover_letter_id"):
        raw = form.get(name, "")
        values[name] = int(raw) if raw.isdigit() and int(raw) in document_ids else None
    return values, errors


def apply_form(s, job, values, user_id, moment):
    """Copy the form's values onto the application (not the stage: workflow.py does that)."""
    job.company = companies.find_or_add(s, user_id, values["company_name"])
    for name, value in values.items():
        if name not in ("company_name", "stage"):
            setattr(job, name, value)
    job.updated_at = moment


def form_values(job):
    """What the edit form starts with."""
    return {
        "company_name": job.company.name, "role_title": job.role_title, "location": job.location,
        "job_description": job.job_description, "posting_url": job.posting_url, "work_mode": job.work_mode,
        "source": job.source, "currency": job.currency, "salary_min": job.salary_min,
        "salary_max": job.salary_max, "applied_on": job.applied_on.isoformat() if job.applied_on else "",
        "resume_id": job.resume_id or "", "cover_letter_id": job.cover_letter_id or "",
    }


# ---------- The timeline ----------

@dataclass
class Event:
    moment: datetime
    kind: str  # "note", "stage"... (the template draws each kind)
    title: str
    body: str = ""
    item: object = None  # the row it came from, for buttons like Delete


SOURCE_WORDS = {"board": "on the Board", "email": "from an email"}


def timeline(job):
    """Everything that happened to an application, newest first. At the same
    moment, a stage change comes before the notes made with it."""
    events = [Event(note.created_at, "note", "Note", note.body, note) for note in job.notes]
    for change in job.stage_changes:
        title = workflow.describe(change)
        if change.source in SOURCE_WORDS:
            title += f" ({SOURCE_WORDS[change.source]})"
        events.append(Event(change.changed_at, "stage", title, change.note, change))
    for interview in job.interviews:
        who = f" with {interview.with_whom}" if interview.with_whom else ""
        title = f"{interview.kind_label}{who}"
        if interview.outcome != "pending":
            title += f" ({OUTCOMES[interview.outcome].lower()})"
        events.append(Event(interview.starts_at, "interview", title, "", interview))
    for follow_up in job.follow_ups:
        if follow_up.done_at:
            events.append(Event(follow_up.done_at, "follow_up", "Followed up", follow_up.note, follow_up))
    order = {"stage": 0, "note": 1}
    return sorted(events, key=lambda event: (event.moment, -order.get(event.kind, 2)), reverse=True)
