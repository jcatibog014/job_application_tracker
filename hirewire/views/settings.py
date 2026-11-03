"""Settings: every preference and account action lives here, never in the menu.

Each form sends an "action" field, and each action is one small function.
The demo sees every form, switched off; the server refuses its changes anyway.
"""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .. import auth, db
from ..auth import login_required
from ..dates import is_timezone, timezone_names

bp = Blueprint("settings", __name__, url_prefix="/settings")


def back():
    return redirect(url_for("settings.index"))


def change_timezone(errors):
    name = request.form.get("timezone", "")
    if not is_timezone(name):
        errors["timezone"] = "Choose a time zone from the list."
        return None
    g.user.timezone = name
    db.session().commit()
    flash("Your time zone has been changed.")
    return back()


def change_password(errors):
    new = request.form.get("new_password", "")
    if not check_password_hash(g.user.password_hash, request.form.get("current_password", "")):
        errors["current_password"] = "That isn't your current password."
    problem = auth.password_problem(new, request.form.get("confirm_password", ""))
    if problem:
        errors["new_password"] = problem
    if errors:
        return None
    auth.set_password(g.user, new)
    db.session().commit()
    # This device stays logged in; every other one is logged out.
    session["session_version"] = g.user.session_version
    flash("Your password has been changed.")
    return back()


def new_recovery_code(errors):
    if not check_password_hash(g.user.password_hash, request.form.get("password", "")):
        errors["recovery_password"] = "That isn't your password."
        return None
    code = auth.set_recovery_code(g.user)
    db.session().commit()
    return auth.show_recovery_code(code, "settings")


def delete_account(errors):
    if not check_password_hash(g.user.password_hash, request.form.get("password", "")):
        errors["delete_password"] = "That isn't your password."
        return None
    s = db.session()
    s.delete(g.user)  # everything the user owns goes with it (ON DELETE CASCADE)
    s.commit()
    session.clear()
    flash("Your account and everything in it have been deleted.")
    return redirect(url_for("auth.login"))


ACTIONS = {
    "timezone": change_timezone,
    "password": change_password,
    "recovery": new_recovery_code,
    "delete": delete_account,
}


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    errors = {}
    if request.method == "POST":
        auth.not_for_demo("The demo account can't change its settings.")
        action = ACTIONS.get(request.form.get("action"))
        if action is None:
            return back()
        response = action(errors)
        if response is not None:
            return response
    timezones = [(name, name.replace("_", " ")) for name in timezone_names()]
    return render_template("settings.html", errors=errors, timezones=timezones), 400 if errors else 200
