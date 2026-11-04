"""Stats: how the job hunt is going, worked out from the stage history.

Each application's furthest point on the road is the highest LEVEL any of its
stage changes reached (Applied 1, Screening 2, Interview 3, Offer 4,
Accepted 5). An application that jumped from Applied to Interview still
counts as having passed Screening. Closing stages (Rejected, Withdrawn,
No reply) don't move it forward, so they don't count.
"""
import statistics
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import case, func, select

from .dates import week_start
from .models import (
    ACCEPTED, APPLIED, CLOSED_STAGES, DECLINED, INTERVIEW, OFFER, REJECTED, SCREENING, STAGE_LABELS, Application,
    StageChange,
)

LEVELS = {APPLIED: 1, SCREENING: 2, INTERVIEW: 3, OFFER: 4, DECLINED: 4, ACCEPTED: 5}
FUNNEL = [(1, "Applied"), (2, "Got a reply"), (3, "Interview"), (4, "Offer"), (5, "Accepted")]
# A reply is anything that isn't silence: a call, an interview, an offer, or a "no".
REPLIES = (SCREENING, INTERVIEW, OFFER, ACCEPTED, DECLINED, REJECTED)
WEEKS = 12


def levels_query(user_id):
    """One row per application: (application id, its source, the furthest level it reached)."""
    level = func.max(case(LEVELS, value=StageChange.to_stage, else_=0))
    return (select(Application.id, Application.source, level.label("level"))
            .join(StageChange, StageChange.application_id == Application.id)
            .where(Application.user_id == user_id)
            .group_by(Application.id, Application.source))


def funnel(s, user_id):
    """[(label, count, percent of applied)] for each step of the road."""
    levels = levels_query(user_id).subquery()
    by_level = dict(s.execute(select(levels.c.level, func.count()).group_by(levels.c.level)).all())
    reached = {step: sum(count for level, count in by_level.items() if level >= step) for step, _ in FUNNEL}
    applied = reached[1]
    return [(label, reached[step], round(100 * reached[step] / applied) if applied else 0) for step, label in FUNNEL]


def replied_count(s, user_id):
    """Applications that heard anything back after applying: got past Applied,
    or were rejected (a "no" is an answer too)."""
    levels = levels_query(user_id).subquery()
    rejected = select(StageChange.id).where(StageChange.application_id == levels.c.id,
                                            StageChange.to_stage == REJECTED)
    return s.scalar(select(func.count()).select_from(levels)
                    .where(levels.c.level >= 1, (levels.c.level >= 2) | rejected.exists()))


def days_to_first_reply(s, user_id):
    """For each application that was Applied and later got a reply: the days between."""
    rows = s.execute(select(StageChange.application_id, StageChange.to_stage, StageChange.changed_at)
                     .join(Application, StageChange.application_id == Application.id)
                     .where(Application.user_id == user_id)
                     .order_by(StageChange.application_id, StageChange.changed_at, StageChange.id)).all()
    applied_at, answered, days = {}, set(), []
    for job_id, stage, moment in rows:
        if stage == APPLIED and job_id not in applied_at:
            applied_at[job_id] = moment
        elif stage in REPLIES and job_id in applied_at and job_id not in answered:
            answered.add(job_id)
            days.append((moment - applied_at[job_id]).total_seconds() / 86400)
    return days


def per_week(s, user_id, today):
    """Applications sent in each of the last WEEKS weeks (Monday to Sunday): [(monday, count)]."""
    first = week_start(today) - timedelta(weeks=WEEKS - 1)
    rows = s.execute(select(Application.applied_on, func.count())
                     .where(Application.user_id == user_id, Application.applied_on >= first)
                     .group_by(Application.applied_on)).all()
    weeks = {first + timedelta(weeks=n): 0 for n in range(WEEKS)}
    for day, count in rows:
        weeks[week_start(day)] = weeks.get(week_start(day), 0) + count
    return sorted(weeks.items())


def by_source(s, user_id):
    """[(source, applied, reached interview)] for sources with at least one application, busiest first."""
    levels = levels_query(user_id).subquery()
    applied = func.sum(case((levels.c.level >= 1, 1), else_=0))
    interviews = func.sum(case((levels.c.level >= 3, 1), else_=0))
    rows = s.execute(select(levels.c.source, applied, interviews).group_by(levels.c.source)).all()
    rows = [(source or "Not known", int(sent or 0), int(got or 0)) for source, sent, got in rows if sent]
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def endings(s, user_id):
    """How closed applications ended: [(label, count)], in the order of CLOSED_STAGES."""
    counts = dict(s.execute(select(Application.stage, func.count())
                            .where(Application.user_id == user_id, Application.stage.in_(CLOSED_STAGES))
                            .group_by(Application.stage)).all())
    return [(STAGE_LABELS[stage], counts.get(stage, 0)) for stage in CLOSED_STAGES]


@dataclass
class Summary:
    funnel: list
    applied: int
    replied: int
    interviews: int
    offers: int
    median_days: float | None
    weeks: list
    sources: list
    endings: list

    @property
    def response_rate(self):
        return round(100 * self.replied / self.applied) if self.applied else 0


def summary(s, user_id, today):
    steps = funnel(s, user_id)
    days = days_to_first_reply(s, user_id)
    return Summary(
        funnel=steps, applied=steps[0][1], replied=replied_count(s, user_id), interviews=steps[2][1],
        offers=steps[3][1], median_days=statistics.median(days) if days else None,
        weeks=per_week(s, user_id, today), sources=by_source(s, user_id), endings=endings(s, user_id),
    )


# ---------- Drawing the bars (as SVG numbers, because the page allows no inline styles) ----------

def columns(values, width=600, height=150, bar=24, radius=4):
    """Column shapes for a small chart: [(x, path, top)], each with a rounded top
    and a square foot on the baseline. Bars are at most `bar` wide, centred in their slot."""
    top_value = max(values, default=0) or 1
    slot = width / max(len(values), 1)
    shapes = []
    for index, value in enumerate(values):
        x = index * slot + (slot - bar) / 2
        tall = height * value / top_value
        y = height - tall
        r = min(radius, tall / 2, bar / 2)
        if value:
            path = (f"M{x:.1f},{height} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                    f"H{x + bar - r:.1f} Q{x + bar:.1f},{y:.1f} {x + bar:.1f},{y + r:.1f} V{height} Z")
        else:
            path = ""
        shapes.append((x + bar / 2, path, y))
    return shapes
