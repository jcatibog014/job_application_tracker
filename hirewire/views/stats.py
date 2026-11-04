"""Stats: the funnel, response rate, weekly pace and the best sources."""
from flask import Blueprint, g, render_template

from .. import db, stats
from ..auth import login_required
from ..dates import local_today

bp = Blueprint("stats", __name__, url_prefix="/stats")


@bp.get("/")
@login_required
def index():
    summary = stats.summary(db.session(), g.user.id, local_today(g.user.timezone))
    week_counts = [count for _, count in summary.weeks]
    # One row per week: the Monday, how many were sent, and where its column goes.
    weekly = [(monday, count, *shape) for (monday, count), shape in zip(summary.weeks, stats.columns(week_counts))]
    return render_template("stats.html", summary=summary, weekly=weekly, week_top=max(week_counts, default=0))
