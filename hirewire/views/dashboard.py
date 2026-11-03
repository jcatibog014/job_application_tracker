"""The Dashboard: what needs doing today, and how the job hunt is going."""
from flask import Blueprint, render_template

from ..auth import login_required

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.get("/")
@login_required
def index():
    return render_template("dashboard.html")
