"""Email suggestions: checking the inbox, and what Accept does.

check() reads new emails (gmail.py), keeps the ones mail_rules.py
understands as suggestions, and remembers each message id so an email is
never suggested twice. Nothing changes until the person presses Accept,
and then every change goes through workflow.move (with source "email").
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import companies, crypto, gmail, mail_rules, reminders, workflow
from .dates import local_today
from .models import (
    APPLIED, CLOSED_STAGES, INTERVIEW, OFFER, REJECTED, SAVED, Application, Company, EmailSuggestion, GmailAccount,
    Interview, Note,
)

CHECK_EVERY = timedelta(hours=1)  # opening the page checks again after this long
MOVES_TO_INTERVIEW = ("applied", "screening", "no_reply")


class SuggestionProblem(Exception):
    pass


def job_rows(s, user_id):
    """What match_application needs about each application."""
    return s.execute(select(Application.id, Company.name, Company.website, Application.stage, Application.updated_at)
                     .join(Application.company).where(Application.user_id == user_id)).all()


def add_from_raw(s, user, raws, moment):
    """Turn raw emails into suggestions. Returns how many are new."""
    seen = set(s.scalars(select(EmailSuggestion.message_id).where(EmailSuggestion.user_id == user.id)))
    jobs = [(job_id, name, website, stage in CLOSED_STAGES, updated)
            for job_id, name, website, stage, updated in job_rows(s, user.id)]
    added = 0
    for raw in raws:
        message = gmail.parse_message(raw)
        if message.message_id in seen:
            continue
        seen.add(message.message_id)
        message.received_at = message.received_at or moment
        finding = mail_rules.read_email(message, user.timezone)
        if finding is None:
            continue
        s.add(EmailSuggestion(
            user_id=user.id, message_id=message.message_id,
            sender=(f"{message.sender_name} <{message.sender_address}>" if message.sender_name else message.sender_address)[:300],
            subject=message.subject[:300], snippet=mail_rules.snippet(message.text), received_at=message.received_at,
            kind=finding.kind, company_guess=finding.company, role_guess=finding.role, proposed_at=finding.when,
            application_id=mail_rules.match_application(finding, message, jobs), created_at=moment))
        added += 1
    return added


def check(s, user, moment, fetcher=None):
    """Read the inbox now. Returns how many new suggestions, or raises GmailProblem.
    The caller commits (also on a problem: the error is kept for the Settings page)."""
    account = s.scalar(select(GmailAccount).where(GmailAccount.user_id == user.id))
    if account is None:
        raise gmail.GmailProblem("Connect Gmail in Settings first.")
    password = crypto.decrypt(account.password_encrypted)
    if password is None:
        account.last_error = "The saved app password can't be read any more. Please connect Gmail again."
        raise gmail.GmailProblem(account.last_error)
    try:
        raws = (fetcher or gmail.fetch_recent)(account.address, password)
    except gmail.GmailProblem as problem:
        account.last_error = str(problem)[:300]
        account.last_checked_at = moment
        raise
    added = add_from_raw(s, user, raws, moment)
    account.last_checked_at, account.last_error = moment, ""
    return added


def due_for_check(account, moment):
    return account is not None and (account.last_checked_at is None or account.last_checked_at <= moment - CHECK_EVERY)


def pending(s, user_id):
    return s.scalars(select(EmailSuggestion).where(EmailSuggestion.user_id == user_id,
                                                   EmailSuggestion.status == "pending")
                     .options(selectinload(EmailSuggestion.application).selectinload(Application.company))
                     .order_by(EmailSuggestion.received_at.desc())).all()


def describe(suggestion):
    """What Accept will do, in words."""
    job = suggestion.application
    company = suggestion.company_guess or "this company"
    if suggestion.kind == "applied":
        if job is None:
            return f"Add a new application for {company}, as Applied."
        if job.stage == SAVED:
            return "Move it from Saved to Applied."
        return "Add this email to the application's timeline."
    if suggestion.kind == "interview":
        when = "an interview" if suggestion.proposed_at is None else "an interview at the time below"
        if job is None:
            return f"Add a new application for {company}, with {when}."
        move = " and move it to Interview" if job.stage in MOVES_TO_INTERVIEW else ""
        return f"Add {when}{move}."
    if suggestion.kind == "rejection":
        return "Close it as Rejected." if job else "Choose the application this rejection is about."
    return "Move it to Offer." if job else "Choose the application this offer is about."


def accept(s, suggestion, user, moment, job=None, when=None, role=""):
    """Do what the suggestion says. job is the chosen application (None: a new one).
    Raises SuggestionProblem if it can't be done. The caller commits."""
    kind = suggestion.kind
    if job is None:
        if kind not in ("applied", "interview"):
            raise SuggestionProblem("Choose the application this email is about.")
        job = Application(user_id=user.id, role_title=(role or suggestion.role_guess or "Job from an email")[:150],
                          created_at=moment, updated_at=moment,
                          applied_on=local_today(user.timezone, suggestion.received_at))
        job.company = companies.find_or_add(s, user.id, suggestion.company_guess or "Unknown company")
        s.add(job)
        workflow.start(s, job, INTERVIEW if kind == "interview" else APPLIED, moment, source="email", user=user)
        s.flush()
    try:
        if kind == "applied" and job.stage == SAVED:
            workflow.move(s, job, APPLIED, user, moment, source="email")
        elif kind == "interview":
            if when is not None:
                interview = Interview(application=job, starts_at=when, kind="video", created_at=moment,
                                      prep_notes=f"From an email: {suggestion.subject}"[:10_000])
                s.add(interview)
            if job.stage in MOVES_TO_INTERVIEW:
                workflow.move(s, job, INTERVIEW, user, moment, source="email")
            if when is not None:
                reminders.after_interview_saved(s, interview, user, moment)
        elif kind == "rejection":
            workflow.move(s, job, REJECTED, user, moment, source="email")
        elif kind == "offer":
            workflow.move(s, job, OFFER, user, moment, source="email")
    except workflow.MoveNotAllowed as problem:
        raise SuggestionProblem(str(problem)) from None
    s.add(Note(application=job, body=f"From an email: “{suggestion.subject}”", created_at=moment))
    job.updated_at = moment
    suggestion.status, suggestion.application = "accepted", job
    return job
