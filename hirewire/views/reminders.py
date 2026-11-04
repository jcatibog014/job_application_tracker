"""Interviews, follow-ups, the Schedule page and the calendar feed."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .. import auth, calendar_feed, db, forms, interviews, reminders, workflow
from ..auth import login_required
from ..dates import local_today, utcnow
from ..models import (
    INTERVIEW, INTERVIEW_KINDS, NO_REPLY, OUTCOMES, Application, EmailSuggestion, FollowUp, Interview, User,
)
from ..ownership import get_child, get_mine

bp = Blueprint("reminders", __name__)

# A new interview moves the application to Interview from these stages.
MOVES_TO_INTERVIEW = ("applied", "screening", "no_reply")


def back_to(job_id, anchor=""):
    """After a button: the page it was pressed on (if it said), else the application's page."""
    default = url_for("applications.detail", job_id=job_id) + anchor
    return redirect(auth.safe_next(request.form.get("next"), default))


def today():
    return local_today(g.user.timezone)


# ---------- Interviews ----------

def interview_page(job, values, errors, interview=None):
    return render_template(
        "interviews/form.html", job=job, values=values, errors=errors, interview=interview,
        kinds=list(INTERVIEW_KINDS.items()), outcomes=list(OUTCOMES.items()),
        lengths=[(minutes, f"{minutes} minutes" if minutes < 60 else
                  f"{minutes // 60} hour{'s' if minutes > 60 else ''}{' 30 minutes' if minutes % 60 else ''}")
                 for minutes in interviews.LENGTHS],
    ), 400 if errors else 200


@bp.route("/applications/<int:job_id>/interviews/new", methods=["GET", "POST"])
@login_required
def new_interview(job_id):
    job = get_mine(Application, job_id, selectinload(Application.company))
    if request.method == "GET":
        return interview_page(job, {"minutes": 60, "kind": "video"}, {})
    values, errors = interviews.read_form(request.form, g.user.timezone)
    if errors:
        return interview_page(job, {**request.form, "starts_at": values["starts_at"]}, errors)
    s = db.session()
    moment = utcnow()
    values["outcome"] = "pending"
    interview = Interview(application=job, created_at=moment, **values)
    s.add(interview)
    job.updated_at = moment
    message = "The interview has been added."
    if job.stage in MOVES_TO_INTERVIEW:
        workflow.move(s, job, INTERVIEW, g.user, moment, note="Interview added")
        message = "The interview has been added, and the application moved to Interview."
    reminders.after_interview_saved(s, interview, g.user, moment)
    s.commit()
    flash(message)
    return redirect(url_for("applications.detail", job_id=job.id) + "#interviews")


@bp.route("/interviews/<int:interview_id>/edit", methods=["GET", "POST"])
@login_required
def edit_interview(interview_id):
    interview = get_child(Interview, interview_id,
                          selectinload(Interview.application).selectinload(Application.company))
    job = interview.application
    if request.method == "GET":
        return interview_page(job, interviews.form_values(interview), {}, interview)
    values, errors = interviews.read_form(request.form, g.user.timezone)
    if errors:
        return interview_page(job, {**request.form, "starts_at": values["starts_at"]}, errors, interview)
    for name, value in values.items():
        setattr(interview, name, value)
    s = db.session()
    moment = utcnow()
    job.updated_at = moment
    reminders.after_interview_saved(s, interview, g.user, moment)
    s.commit()
    flash("Your changes have been saved.")
    return redirect(url_for("applications.detail", job_id=job.id) + "#interviews")


@bp.post("/interviews/<int:interview_id>/outcome")
@login_required
def interview_outcome(interview_id):
    """The quick "How did it go?" buttons under a past interview."""
    interview = get_child(Interview, interview_id, selectinload(Interview.application))
    outcome = request.form.get("outcome")
    if outcome not in OUTCOMES:
        abort(400)
    interview.outcome = outcome
    s = db.session()
    reminders.after_interview_saved(s, interview, g.user, utcnow())
    s.commit()
    return back_to(interview.application_id, "#interviews")


@bp.post("/interviews/<int:interview_id>/delete")
@login_required
def delete_interview(interview_id):
    interview = get_child(Interview, interview_id)
    job_id = interview.application_id
    s = db.session()
    s.delete(interview)  # its thank-you goes with it (ON DELETE CASCADE)
    s.commit()
    flash("The interview has been deleted.")
    return redirect(url_for("applications.detail", job_id=job_id) + "#interviews")


# ---------- Follow-ups ----------

def read_follow_up(form):
    errors = {}
    due_on, problem = forms.day(form, "due_on", required=True)
    if problem:
        errors["due_on"] = problem
    note, problem = forms.text(form, "note", 300, required=True, label="A note")
    if problem:
        errors["note"] = problem
    return due_on, note, errors


@bp.post("/applications/<int:job_id>/follow-ups")
@login_required
def add_follow_up(job_id):
    job = get_mine(Application, job_id)
    due_on, note, errors = read_follow_up(request.form)
    if errors:
        for problem in errors.values():
            flash(problem, "error")
    else:
        db.session().add(FollowUp(application=job, due_on=due_on, note=note, created_at=utcnow()))
        db.session().commit()
        flash("The follow-up has been added.")
    return back_to(job.id, "#follow-ups")


def get_follow_up(follow_up_id):
    return get_child(FollowUp, follow_up_id)


@bp.post("/follow-ups/<int:follow_up_id>/done")
@login_required
def follow_up_done(follow_up_id):
    follow_up = get_follow_up(follow_up_id)
    reminders.mark_done(follow_up, utcnow())
    db.session().commit()
    flash("Marked as done.")
    return back_to(follow_up.application_id, "#follow-ups")


@bp.post("/follow-ups/<int:follow_up_id>/not-done")
@login_required
def follow_up_not_done(follow_up_id):
    follow_up = get_follow_up(follow_up_id)
    reminders.mark_not_done(follow_up)
    db.session().commit()
    return back_to(follow_up.application_id, "#follow-ups")


@bp.post("/follow-ups/<int:follow_up_id>/snooze")
@login_required
def snooze_follow_up(follow_up_id):
    follow_up = get_follow_up(follow_up_id)
    days = request.form.get("days", "")
    if not days.isdigit() or int(days) not in reminders.SNOOZE_CHOICES:
        abort(400)
    reminders.snooze(follow_up, int(days), today())
    db.session().commit()
    flash(f"Snoozed for {reminders.SNOOZE_CHOICES[int(days)]}.")
    return back_to(follow_up.application_id, "#follow-ups")


@bp.route("/follow-ups/<int:follow_up_id>/edit", methods=["GET", "POST"])
@login_required
def edit_follow_up(follow_up_id):
    follow_up = get_child(FollowUp, follow_up_id, selectinload(FollowUp.application).selectinload(Application.company))
    errors = {}
    values = {"due_on": follow_up.due_on.isoformat(), "note": follow_up.note}
    if request.method == "POST":
        due_on, note, errors = read_follow_up(request.form)
        values = request.form
        if not errors:
            follow_up.due_on, follow_up.note = due_on, note
            db.session().commit()
            flash("Your changes have been saved.")
            return redirect(url_for("applications.detail", job_id=follow_up.application_id) + "#follow-ups")
    return render_template("follow_ups/form.html", follow_up=follow_up, values=values, errors=errors), \
        400 if errors else 200


@bp.post("/follow-ups/<int:follow_up_id>/delete")
@login_required
def delete_follow_up(follow_up_id):
    follow_up = get_follow_up(follow_up_id)
    job_id = follow_up.application_id
    s = db.session()
    s.delete(follow_up)
    s.commit()
    flash("The follow-up has been deleted.")
    return back_to(job_id, "#follow-ups")


# ---------- The No reply nudge ----------

@bp.post("/applications/<int:job_id>/no-reply")
@login_required
def mark_no_reply(job_id):
    job = get_mine(Application, job_id)
    s = db.session()
    try:
        workflow.move(s, job, NO_REPLY, g.user, utcnow(), note="No reply after waiting")
    except workflow.MoveNotAllowed as problem:
        s.rollback()
        flash(str(problem), "error")
    else:
        s.commit()
        flash("Closed as No reply. If they answer later, you can move it back.")
    return back_to(job.id)


@bp.post("/applications/<int:job_id>/keep-waiting")
@login_required
def keep_waiting(job_id):
    job = get_mine(Application, job_id)
    reminders.keep_waiting(job, today())
    db.session().commit()
    flash(f"OK. We'll ask again in {reminders.KEEP_WAITING_DAYS} days.")
    return back_to(job.id)


# ---------- Schedule and the calendar feed ----------

@bp.get("/schedule/")
@login_required
def schedule():
    overdue, days = reminders.schedule(db.session(), g.user, today())
    return render_template("schedule.html", overdue=overdue, days=days, today=today(),
                           snooze_choices=reminders.SNOOZE_CHOICES)


@bp.get("/calendar/<token>.ics")
def calendar(token):
    """No login: calendar apps can't log in. The token is the key."""
    s = db.session()
    user = s.scalar(select(User).where(User.calendar_token == token)) if len(token) >= 20 else None
    if user is None:
        abort(404)
    moment = utcnow()
    body = calendar_feed.build(s, user, moment, local_today(user.timezone, moment))
    return body, 200, {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": 'inline; filename="hirewire.ics"',
        "Cache-Control": "private, max-age=300",
        "X-Robots-Tag": "noindex",
    }


def init_app(app):
    @app.context_processor
    def menu_counts():
        """The numbers in the menu: follow-ups overdue or due today, and email suggestions waiting."""
        if g.get("user") is None:
            return {}
        waiting = db.session().scalar(select(func.count()).select_from(EmailSuggestion).where(
            EmailSuggestion.user_id == g.user.id, EmailSuggestion.status == "pending"))
        return {"attention_count": reminders.needs_attention_count(db.session(), g.user, today()),
                "suggestion_count": waiting}
