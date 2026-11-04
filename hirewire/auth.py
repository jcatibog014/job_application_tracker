"""Signing up, logging in and out, recovery codes, and protection for every form.

Anyone can sign up, and each account is a private tracker. Passwords are
stored only as hashes. There is no email service, so sign-up shows a
one-time RECOVERY CODE: with it you can set a new password (/forgot), and
then you get a new code.

The login cookie holds the user's id and their session_version; load_user()
checks both on every request, so an old cookie is logged out straight away.
"""
import functools
import hmac
import re
import secrets
from datetime import timedelta

import click
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from flask.cli import with_appcontext
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, filters
from .dates import utcnow
from .models import User

bp = Blueprint("auth", __name__)

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 40
PASSWORD_MIN_LENGTH = 8
USERNAME_PATTERN = re.compile(r"[a-z0-9_-]+")
# Nobody may sign up with a name that looks like it speaks for the site.
# Names starting with "demo" belong to Try Demo.
RESERVED_USERNAMES = {"admin", "administrator", "owner", "hirewire", "moderator", "support"}
# After 5 wrong passwords (or recovery codes) in a row, the account waits
# 15 minutes. This makes guessing on the live site very slow.
MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)

# Letters and digits that can't be mixed up when copied by hand (no 0/O, 1/I/L).
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_LENGTH = 16

DEMO_LIFETIME = timedelta(hours=2)
MAX_DEMOS = 300  # demo accounts alive at once, so a script can't fill the database

WRONG_LOGIN = "Wrong username or password."
WRONG_RECOVERY = "Wrong username or recovery code."
LOCKED = "Too many failed attempts. Please wait 15 minutes and try again."


# ---------- Users in the database ----------

def clean_username(text):
    return (text or "").strip().lower()


def username_problem(username):
    """Why this (cleaned) username can't be used, or None if it is fine."""
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        return f"Use {USERNAME_MIN_LENGTH} to {USERNAME_MAX_LENGTH} characters."
    if not USERNAME_PATTERN.fullmatch(username):
        return "Use only letters, numbers, - and _."
    if username in RESERVED_USERNAMES or username.startswith("demo"):
        return "That username is not available."
    return None


def password_problem(password, confirm):
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if password != confirm:
        return "The two passwords are not the same."
    return None


def new_recovery_code():
    """ABCD-EFGH-JKMN-PQRS: easy to write down, about 79 bits of chance."""
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, RECOVERY_LENGTH, 4))


def clean_recovery_code(text):
    """People type it with spaces, dashes or small letters. Compare only the letters."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def set_recovery_code(user):
    """Give the user a fresh code and return it. Only its hash is kept, so show it now."""
    code = new_recovery_code()
    user.recovery_hash = generate_password_hash(clean_recovery_code(code))
    return code


def find_user(s, username):
    """A real (not demo) user by username, or None."""
    return s.scalar(select(User).where(User.username == clean_username(username), User.is_demo.is_(False)))


def create_user(s, username, password, is_demo=False):
    """Add a user. Returns (user, recovery code). The caller commits."""
    user = User(username=clean_username(username), password_hash=generate_password_hash(password), is_demo=is_demo)
    code = set_recovery_code(user)
    s.add(user)
    s.flush()
    filters.add_starter_views(s, user)  # every account starts with a few saved views
    return user, code


def set_password(user, password):
    user.password_hash = generate_password_hash(password)
    user.failed_logins = 0
    user.locked_until = None
    user.session_version += 1  # every other device is logged out


def check_secret(s, user, secret, field, moment):
    """True if secret matches the user's password or recovery code (field).
    Wrong guesses count towards the lock, and so do guesses while locked."""
    if user.locked_until and user.locked_until > moment:
        return False
    if not check_password_hash(getattr(user, field), secret):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins, user.locked_until = 0, moment + LOCK_TIME
        s.commit()
        return False
    user.failed_logins, user.locked_until = 0, None
    return True


def check_login(s, username, password, moment):
    """Return (user, None) if the password is right, else (None, message).
    The message never says whether the username exists."""
    user = find_user(s, username)
    if user is None:
        return None, WRONG_LOGIN
    if user.locked_until and user.locked_until > moment:
        return None, LOCKED
    if not check_secret(s, user, password or "", "password_hash", moment):
        return None, WRONG_LOGIN
    s.commit()
    return user, None


def safe_next(target, default=None):
    """Only go back to a page on this site (after logging in or saving a form).

    "/applications/7" is fine. "https://evil.example" and "//evil.example"
    are not: a fake link could send people there after a real login. Browsers
    drop tabs and newlines and read a backslash as a slash, so those are out too.
    """
    if (target and target.startswith("/") and not target.startswith("//")
            and "\\" not in target and not any(ord(c) < 32 for c in target)):
        return target
    return default or url_for("dashboard.index")


def log_in(user):
    session.clear()  # a new session for the new user (old cookies can't be reused)
    session.permanent = True  # stay logged in for PERMANENT_SESSION_LIFETIME
    session["user_id"] = user.id
    session["session_version"] = user.session_version


# ---------- Every request ----------

@bp.before_app_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = db.session().get(User, user_id)
    if user is None or session.get("session_version") != user.session_version:
        # Keep the CSRF token: only the login part of this cookie is out of date.
        session.pop("user_id", None)
        session.pop("session_version", None)
        return
    g.user = user


def csrf_token():
    """A secret per session, put into every form as a hidden field.

    Another website could make your browser send a form to this site (your
    login cookie goes with it). It can't read this secret, so its form fails.
    """
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.before_app_request
def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf", "")
    # compare_digest takes the same time for every wrong guess.
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "This form has expired. Please go back, reload the page and try again.")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            # Only a GET can be repeated after logging in.
            next_page = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=next_page))
        return view(*args, **kwargs)
    return wrapped


def not_for_demo(message="The demo can't change this."):
    if g.user.is_demo:
        abort(403, message)


def show_recovery_code(code, reason):
    """The code is only on the next page, then gone (it isn't in the database)."""
    session["new_recovery_code"] = code
    session["recovery_reason"] = reason
    return redirect(url_for("auth.recovery_code"))


# ---------- Pages ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("dashboard.index"))
    next_page = request.values.get("next", "")
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "")[:USERNAME_MAX_LENGTH]
        user, error = check_login(db.session(), username, request.form.get("password", ""), utcnow())
        if user:
            log_in(user)
            return redirect(safe_next(next_page))
    status = 401 if error else 200
    return render_template("login.html", error=error, username=username, next=next_page), status


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None:
        return redirect(url_for("dashboard.index"))
    errors = {}
    username = ""
    if request.method == "POST":
        # A hidden field people never see. Only robots fill it in, and they get
        # sent away like a success, so they learn nothing from it.
        if request.form.get("website"):
            return redirect(url_for("auth.login"))
        username = clean_username(request.form.get("username", ""))[:USERNAME_MAX_LENGTH + 1]
        password = request.form.get("password", "")
        problem = username_problem(username)
        if problem:
            errors["username"] = problem
        problem = password_problem(password, request.form.get("confirm_password", ""))
        if problem:
            errors["password"] = problem
        if not errors:
            s = db.session()
            try:
                user, code = create_user(s, username, password)
                s.commit()
            except IntegrityError:
                s.rollback()
                errors["username"] = "That username is already taken."
            else:
                log_in(user)
                return show_recovery_code(code, "signup")
    return render_template("signup.html", errors=errors, username=username), 400 if errors else 200


@bp.get("/recovery-code")
@login_required
def recovery_code():
    code = session.pop("new_recovery_code", None)
    reason = session.pop("recovery_reason", "")
    if code is None:
        return redirect(url_for("dashboard.index"))
    response = render_template("recovery_code.html", code=code, reason=reason)
    # Never keep this page in a cache: the code is a password.
    return response, 200, {"Cache-Control": "no-store"}


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    """Set a new password with the recovery code. The old code stops working."""
    errors = {}
    username = ""
    if request.method == "POST":
        s = db.session()
        username = request.form.get("username", "")[:USERNAME_MAX_LENGTH]
        new = request.form.get("new_password", "")
        problem = password_problem(new, request.form.get("confirm_password", ""))
        if problem:
            errors["new_password"] = problem
        user = find_user(s, username)
        moment = utcnow()
        if user and user.locked_until and user.locked_until > moment:
            errors["code"] = LOCKED
        elif not errors and (user is None or not check_secret(
                s, user, clean_recovery_code(request.form.get("code")), "recovery_hash", moment)):
            locked_now = user is not None and user.locked_until is not None and user.locked_until > moment
            errors["code"] = LOCKED if locked_now else WRONG_RECOVERY
        if not errors:
            set_password(user, new)
            code = set_recovery_code(user)
            s.commit()
            log_in(user)
            return show_recovery_code(code, "forgot")
    return render_template("forgot.html", errors=errors, username=username), 400 if errors else 200


@bp.post("/demo")
def demo():
    """A fresh sample account for this visitor alone, deleted after DEMO_LIFETIME.
    Nobody sees anyone else's changes, and the next visitor starts clean."""
    s = db.session()
    moment = utcnow()
    if g.user is not None and g.user.is_demo:
        return redirect(url_for("dashboard.index"))  # this browser already has one
    # Old demos go first. Deleting the user deletes everything in it (ON DELETE CASCADE).
    s.execute(delete(User).where(User.is_demo.is_(True), User.demo_expires_at < moment)
              .execution_options(synchronize_session=False))
    s.commit()
    if s.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True))) >= MAX_DEMOS:
        flash("The demo is very busy right now. Please try again in a little while.")
        return redirect(url_for("auth.login"))
    from . import seed
    # Nobody knows this password: a demo account is only opened with the button.
    user, _ = create_user(s, f"demo-{secrets.token_hex(4)}", secrets.token_urlsafe(32), is_demo=True)
    user.demo_expires_at = moment + DEMO_LIFETIME
    seed.fill(s, user, moment)
    s.commit()
    log_in(user)
    flash("Welcome to the demo! This sample job hunt is yours for 2 hours, so try anything.")
    return redirect(url_for("dashboard.index"))


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have logged out.")
    return redirect(url_for("auth.login"))


# ---------- Command line ----------

def ask_password():
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise click.ClickException(f"Use at least {PASSWORD_MIN_LENGTH} characters.")
    return password


@click.command("create-user")
@with_appcontext
@click.argument("username")
def create_user_command(username):
    """Make a login (the same as signing up on the site)."""
    s = db.session()
    username = clean_username(username)
    problem = username_problem(username)
    if problem:
        raise click.ClickException(problem)
    if s.scalar(select(User).where(User.username == username)):
        raise click.ClickException(f'"{username}" already exists. Use set-password to change the password.')
    _, code = create_user(s, username, ask_password())
    s.commit()
    click.echo(f'Made "{username}". Recovery code (write it down): {code}')


@click.command("set-password")
@with_appcontext
@click.argument("username")
def set_password_command(username):
    """Change a user's password (and unlock the account). Also ends their sessions."""
    s = db.session()
    user = find_user(s, username)
    if user is None:
        raise click.ClickException(f'There is no user "{username}".')
    set_password(user, ask_password())
    s.commit()
    click.echo("The password is changed.")


def init_app(app):
    app.jinja_env.globals["csrf_token"] = csrf_token
    for command in (create_user_command, set_password_command):
        app.cli.add_command(command)
