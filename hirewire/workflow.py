"""The status workflow: which stage an application can move to next.

    Saved → Applied → Screening → Interview → Offer → Accepted
              │           │           │          └──→ Declined
              └───────────┴───────────┴──→ Rejected / Withdrawn / No reply

TRANSITIONS lists every allowed move. Besides those:
- moving back one step is allowed, to fix a mistake;
- Rejected, Withdrawn and No reply can go back to the stage they came from
  (a click by mistake, or a late reply after all).

move() is the ONLY way a stage changes. It checks the rule, writes a
stage_changes row (the history the timeline and the stats are made from),
and lets reminders.py react (a follow-up after applying, for example).
"""
from sqlalchemy import select

from . import reminders
from .dates import local_today
from .models import (
    ACCEPTED, ACTIVE_STAGES, APPLIED, CLOSED_STAGES, DECLINED, INTERVIEW, NO_REPLY, OFFER, REJECTED, SAVED,
    SCREENING, STAGE_LABELS, WITHDRAWN, StageChange,
)

TRANSITIONS = {
    SAVED: (APPLIED, WITHDRAWN),
    APPLIED: (SCREENING, INTERVIEW, OFFER, REJECTED, WITHDRAWN, NO_REPLY, SAVED),
    SCREENING: (INTERVIEW, OFFER, REJECTED, WITHDRAWN, NO_REPLY, APPLIED),
    INTERVIEW: (OFFER, REJECTED, WITHDRAWN, NO_REPLY, SCREENING),
    OFFER: (ACCEPTED, DECLINED, REJECTED, INTERVIEW),
    ACCEPTED: (OFFER,),
    DECLINED: (OFFER,),
    REJECTED: (),
    WITHDRAWN: (),
    NO_REPLY: (SCREENING, INTERVIEW, OFFER, REJECTED),  # they answered late after all
}
# These can also go back to whatever stage they came from.
REOPENABLE = (REJECTED, WITHDRAWN, NO_REPLY)
# Where on the road each stage is. Further on means "forward"; back is a correction.
ROAD = {SAVED: 0, APPLIED: 1, SCREENING: 2, INTERVIEW: 3, OFFER: 4, ACCEPTED: 5, DECLINED: 5}
ENDINGS = (REJECTED, WITHDRAWN, NO_REPLY)


class MoveNotAllowed(ValueError):
    pass


def allowed_moves(stage, came_from=None):
    """Every stage this one may move to, in the order buttons show them."""
    moves = list(TRANSITIONS[stage])
    if stage in REOPENABLE and came_from and came_from != stage and came_from not in moves:
        moves.append(came_from)
    return moves


def can_move(stage, to_stage, came_from=None):
    return to_stage in allowed_moves(stage, came_from)


def group_moves(stage, came_from=None):
    """The allowed moves split for the buttons: forward, endings and back."""
    forward, endings, back = [], [], []
    for to in allowed_moves(stage, came_from):
        if to in ENDINGS:
            endings.append(to)
        elif stage in ROAD and to in ROAD and ROAD[to] < ROAD[stage] or stage in REOPENABLE and to == came_from:
            back.append(to)
        else:
            forward.append(to)
    return forward, endings, back


def came_from(s, job):
    """The stage before the current one (None for a new application)."""
    return s.scalar(select(StageChange.from_stage).where(StageChange.application_id == job.id)
                    .order_by(StageChange.changed_at.desc(), StageChange.id.desc()).limit(1))


def came_from_many(s, job_ids):
    """came_from() for many applications in one query: {job id: stage before}."""
    rows = s.execute(select(StageChange.application_id, StageChange.from_stage)
                     .where(StageChange.application_id.in_(job_ids))
                     .order_by(StageChange.changed_at, StageChange.id)).all()
    return dict(rows)  # later rows replace earlier ones, so the newest wins


def start(s, job, stage, moment, source="manual", user=None):
    """A new application begins at stage. Its history starts with this row.
    With the user, its automatic reminders start too."""
    if stage not in ACTIVE_STAGES:
        raise MoveNotAllowed("A new application starts at Saved, Applied, Screening, Interview or Offer.")
    job.stage = stage
    job.stage_changed_at = moment
    s.add(StageChange(application=job, from_stage=None, to_stage=stage, changed_at=moment, source=source))
    if user is not None:
        reminders.on_move(s, job, None, user, moment)


def move(s, job, to_stage, user, moment, note="", source="manual"):
    """Move job to to_stage, or raise MoveNotAllowed. The caller commits."""
    before = job.stage
    if to_stage == before:
        return
    if to_stage not in STAGE_LABELS or not can_move(before, to_stage, came_from(s, job)):
        raise MoveNotAllowed(f"An application can't go from {STAGE_LABELS[before]} to "
                             f"{STAGE_LABELS.get(to_stage, 'that stage')}.")
    s.add(StageChange(application=job, from_stage=before, to_stage=to_stage, changed_at=moment,
                      note=note[:500], source=source))
    job.stage = to_stage
    job.stage_changed_at = moment
    job.updated_at = moment
    if to_stage != SAVED and job.applied_on is None:
        job.applied_on = local_today(user.timezone, moment)
    reminders.on_move(s, job, before, user, moment)


def describe(change):
    """The timeline's words for one history row."""
    if change.from_stage is None:
        return f"Added as {STAGE_LABELS[change.to_stage]}"
    if change.to_stage in CLOSED_STAGES and change.to_stage not in (ACCEPTED, DECLINED):
        return f"Closed as {STAGE_LABELS[change.to_stage]}"
    return f"Moved to {STAGE_LABELS[change.to_stage]}"
