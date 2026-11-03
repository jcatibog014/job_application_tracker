"""The Dashboard: what needs doing today, and how the job hunt is going."""
from flask import Blueprint, g, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .. import db, reminders, workflow
from ..auth import login_required
from ..dates import local_today, utcnow
from ..models import ACTIVE_STAGES, CLOSED_STAGES, Application, StageChange

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.get("/")
@login_required
def index():
    s = db.session()
    moment = utcnow()
    today = local_today(g.user.timezone, moment)
    counts = dict(s.execute(select(Application.stage, func.count()).where(Application.user_id == g.user.id)
                            .group_by(Application.stage)).all())
    recent = s.scalars(
        select(StageChange).join(StageChange.application).where(Application.user_id == g.user.id)
        .options(selectinload(StageChange.application).selectinload(Application.company))
        .order_by(StageChange.changed_at.desc(), StageChange.id.desc()).limit(6)).all()
    return render_template(
        "dashboard.html", today=today, due=reminders.due(s, g.user, today),
        nudges=reminders.no_reply_nudges(s, g.user, moment, today),
        interviews=reminders.upcoming_interviews(s, g.user.id, moment),
        counts=counts, closed_count=sum(counts.get(stage, 0) for stage in CLOSED_STAGES),
        active_stages=ACTIVE_STAGES, closed_stages=CLOSED_STAGES, recent=recent, describe=workflow.describe,
        snooze_choices=reminders.SNOOZE_CHOICES, moment=moment)
