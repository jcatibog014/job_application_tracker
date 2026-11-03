"""The Board: a column per active stage, and one Closed column.

Dragging a card posts to applications.move (the same rule as the buttons),
so a move the workflow doesn't allow is refused here too.
"""
from flask import Blueprint, render_template
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from .. import db, workflow
from ..auth import login_required
from ..models import ACTIVE_STAGES, CLOSED_STAGES, STAGE_LABELS, Application
from ..ownership import mine

bp = Blueprint("board", __name__, url_prefix="/board")

CLOSED_SHOWN = 20  # the newest ones; the Applications page has them all


@bp.get("/")
@login_required
def index():
    s = db.session()
    active = s.scalars(mine(Application).where(Application.stage.in_(ACTIVE_STAGES))
                       .options(selectinload(Application.company))
                       .order_by(Application.stage_changed_at.desc())).all()
    closed = s.scalars(mine(Application).where(Application.stage.in_(CLOSED_STAGES))
                       .options(selectinload(Application.company))
                       .order_by(Application.stage_changed_at.desc()).limit(CLOSED_SHOWN)).all()
    closed_total = s.scalar(mine(Application).where(Application.stage.in_(CLOSED_STAGES))
                            .with_only_columns(func.count()))
    before = workflow.came_from_many(s, [job.id for job in closed])
    moves = {job.id: workflow.allowed_moves(job.stage, before.get(job.id)) for job in active + closed}
    columns = [(stage, [job for job in active if job.stage == stage]) for stage in ACTIVE_STAGES]
    return render_template("board.html", columns=columns, closed=closed, closed_total=closed_total,
                           moves=moves, closed_stages=CLOSED_STAGES, labels=STAGE_LABELS)
