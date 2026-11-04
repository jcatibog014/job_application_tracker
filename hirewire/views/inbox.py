"""Email Suggestions: what your Gmail says about your applications, for you to accept or ignore."""
import click
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask.cli import with_appcontext
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .. import auth, db, gmail, suggestions
from ..auth import login_required
from ..dates import parse_local, utcnow
from ..models import ACTIVE_STAGES, Application, EmailSuggestion, GmailAccount, User
from ..ownership import get_mine, mine

bp = Blueprint("inbox", __name__, url_prefix="/email-suggestions")


def my_account():
    return db.session().scalar(select(GmailAccount).where(GmailAccount.user_id == g.user.id))


def run_check(moment):
    """Check now, keeping any problem for the page. Returns (new count, problem or None)."""
    s = db.session()
    try:
        if g.user.is_demo:
            from .. import seed  # the demo reads sample emails, never a real inbox
            added = suggestions.add_from_raw(s, g.user, seed.sample_emails(moment), moment)
        else:
            added = suggestions.check(s, g.user, moment)
    except gmail.GmailProblem as problem:
        s.commit()  # keep the error and the time, for Settings
        return 0, str(problem)
    s.commit()
    return added, None


@bp.get("/")
@login_required
def index():
    s = db.session()
    moment = utcnow()
    account = my_account()
    problem = None
    if not g.user.is_demo and suggestions.due_for_check(account, moment):
        _, problem = run_check(moment)
    showing_done = request.args.get("show") == "done"
    if showing_done:
        rows = s.scalars(mine(EmailSuggestion).where(EmailSuggestion.status != "pending")
                         .options(selectinload(EmailSuggestion.application).selectinload(Application.company))
                         .order_by(EmailSuggestion.received_at.desc()).limit(50)).all()
    else:
        rows = suggestions.pending(s, g.user.id)
    jobs = s.scalars(mine(Application).join(Application.company).options(selectinload(Application.company))
                     .order_by(Application.stage.in_(ACTIVE_STAGES).desc(), Application.updated_at.desc())).all()
    return render_template("inbox.html", rows=rows, jobs=jobs, account=account, problem=problem or (
        account.last_error if account else None), showing_done=showing_done, describe=suggestions.describe)


@bp.post("/check")
@login_required
def check_now():
    if my_account() is None and not g.user.is_demo:
        flash("Connect Gmail in Settings first.")
        return redirect(url_for("settings.index") + "#gmail")
    added, problem = run_check(utcnow())
    if problem:
        flash(problem)
    else:
        flash(f"Found {added} new {'suggestion' if added == 1 else 'suggestions'}." if added else "No new job emails.")
    return redirect(url_for("inbox.index"))


def get_pending(suggestion_id):
    suggestion = get_mine(EmailSuggestion, suggestion_id, selectinload(EmailSuggestion.application))
    if suggestion.status != "pending":
        abort(404)
    return suggestion


@bp.post("/<int:suggestion_id>/accept")
@login_required
def accept(suggestion_id):
    suggestion = get_pending(suggestion_id)
    s = db.session()
    choice = request.form.get("application", "")
    job = get_mine(Application, int(choice)) if choice.isdigit() else None
    if job is None and choice != "new":
        flash("Choose an application, or New application.")
        return redirect(url_for("inbox.index"))
    when = None
    if suggestion.kind == "interview" and request.form.get("when"):
        try:
            when = parse_local(request.form["when"], g.user.timezone)
        except ValueError:
            flash("Use a date and time like 2026-11-12 14:00.")
            return redirect(url_for("inbox.index"))
    try:
        job = suggestions.accept(s, suggestion, g.user, utcnow(), job=job, when=when,
                                 role=request.form.get("role", "").strip())
    except suggestions.SuggestionProblem as problem:
        s.rollback()
        flash(str(problem))
        return redirect(url_for("inbox.index"))
    s.commit()
    flash(f"Done: {job.role_title} at {job.company.name} is up to date.")
    return redirect(auth.safe_next(request.form.get("next"), url_for("inbox.index")))


@bp.post("/<int:suggestion_id>/ignore")
@login_required
def ignore(suggestion_id):
    suggestion = get_pending(suggestion_id)
    suggestion.status = "ignored"
    db.session().commit()
    return redirect(url_for("inbox.index"))


@bp.post("/<int:suggestion_id>/undo")
@login_required
def undo_ignore(suggestion_id):
    """Bring an ignored suggestion back (an accepted one has already changed things)."""
    suggestion = get_mine(EmailSuggestion, suggestion_id)
    if suggestion.status == "ignored":
        suggestion.status = "pending"
        db.session().commit()
    return redirect(url_for("inbox.index"))


# ---------- From the command line (when the live site can't reach Gmail) ----------

@click.command("scan-email")
@with_appcontext
@click.argument("username")
def scan_email_command(username):
    """Check a user's Gmail now, from this computer. Works against Neon too (DATABASE_URL)."""
    s = db.session()
    user = s.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None:
        raise click.ClickException(f'There is no user "{username}".')
    try:
        added = suggestions.check(s, user, utcnow())
    except gmail.GmailProblem as problem:
        s.commit()
        raise click.ClickException(str(problem)) from None
    s.commit()
    click.echo(f"{added} new suggestions.")


def init_app(app):
    app.cli.add_command(scan_email_command)
