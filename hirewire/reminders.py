"""Reminders: follow-ups, automatic ones, snoozing, and the No reply nudge.

There is no background job (Render's free plan sleeps), so nothing here runs
on a timer. Reminders are rows with a due DAY, and every page works out what
is overdue, due today or due this week when it is opened. To get a ping on
your phone, subscribe to the calendar feed (calendar_feed.py).

Automatic follow-ups (Settings can switch both off):
- moving to Applied adds "Follow up on your application" N days later;
- adding an interview adds "Send a thank-you note" the day after it.
They go away by themselves when they stop making sense: leaving Applied
removes the first kind, closing an application removes both, and a cancelled
interview removes its thank-you. Ones you made yourself are never removed.
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import selectinload

from .dates import day_start_utc, local_today, to_local
from .models import (
    AFTER_APPLIED, APPLIED, CLOSED_STAGES, SCREENING, THANK_YOU, Application, FollowUp, Interview,
)

SNOOZE_CHOICES = {1: "1 day", 3: "3 days", 7: "1 week"}
WEEK = 7
FOLLOW_UP_DAY_CHOICES = (0, 3, 5, 7, 10, 14)
NO_REPLY_DAY_CHOICES = (0, 14, 21, 30, 45, 60)
KEEP_WAITING_DAYS = 7


# ---------- Automatic follow-ups ----------

def open_auto(s, job, kind):
    return s.scalars(select(FollowUp).where(FollowUp.application_id == job.id, FollowUp.auto_kind == kind,
                                            FollowUp.done_at.is_(None))).all()


def drop_open_auto(s, job, *kinds):
    """Delete automatic follow-ups that aren't done yet. Done ones stay as history."""
    s.execute(delete(FollowUp).where(FollowUp.application_id == job.id, FollowUp.auto_kind.in_(kinds),
                                     FollowUp.done_at.is_(None)))


def on_move(s, job, before, user, moment):
    """workflow.py calls this after every stage change (and when an application starts)."""
    if job.id is not None:
        s.flush()
        if before == APPLIED:
            drop_open_auto(s, job, AFTER_APPLIED)  # they answered, or it closed: no need to chase
        if job.stage in CLOSED_STAGES:
            drop_open_auto(s, job, AFTER_APPLIED, THANK_YOU)
    if job.stage == APPLIED and user.follow_up_days and not (job.id and open_auto(s, job, AFTER_APPLIED)):
        start = job.applied_on or local_today(user.timezone, moment)
        s.add(FollowUp(application=job, due_on=start + timedelta(days=user.follow_up_days),
                       note="Follow up on your application", auto_kind=AFTER_APPLIED, created_at=moment))


def interview_day(interview, user):
    return to_local(interview.starts_at, user.timezone).date()


def after_interview_saved(s, interview, user, moment):
    """Add, move or remove the interview's thank-you, to match the interview now."""
    s.flush()
    existing = s.scalars(select(FollowUp).where(FollowUp.interview_id == interview.id,
                                                FollowUp.auto_kind == THANK_YOU, FollowUp.done_at.is_(None))).all()
    wanted = user.thank_you_notes and interview.outcome != "cancelled" and not interview.application.is_closed
    if not wanted:
        for follow_up in existing:
            s.delete(follow_up)
        return
    due = interview_day(interview, user) + timedelta(days=1)
    if existing:
        for follow_up in existing:
            follow_up.due_on = due
    elif not s.scalar(select(exists().where(FollowUp.interview_id == interview.id, FollowUp.auto_kind == THANK_YOU))):
        # (If its thank-you is already done, don't ask again.)
        who = f" to {interview.with_whom}" if interview.with_whom else ""
        s.add(FollowUp(application=interview.application, interview_id=interview.id, due_on=due,
                       note=f"Send a thank-you note{who}"[:300], auto_kind=THANK_YOU, created_at=moment))


# ---------- Doing something with a follow-up ----------

def mark_done(follow_up, moment):
    follow_up.done_at = moment


def mark_not_done(follow_up):
    follow_up.done_at = None


def snooze(follow_up, days, today):
    """Ask again in a few days, counted from today (an overdue one doesn't stay overdue)."""
    follow_up.due_on = today + timedelta(days=days)


# ---------- What is due ----------

@dataclass
class Due:
    overdue: list
    today: list
    this_week: list

    @property
    def needs_attention(self):
        return len(self.overdue) + len(self.today)


def open_follow_ups(s, user_id, until_day):
    """The user's open follow-ups due on or before until_day, oldest first."""
    return s.scalars(
        select(FollowUp).join(FollowUp.application)
        .where(Application.user_id == user_id, FollowUp.done_at.is_(None), FollowUp.due_on <= until_day)
        .options(selectinload(FollowUp.application).selectinload(Application.company))
        .order_by(FollowUp.due_on, FollowUp.id)).all()


def due(s, user, today):
    """Open follow-ups split into overdue, today and the next 7 days."""
    rows = open_follow_ups(s, user.id, today + timedelta(days=WEEK))
    return Due(overdue=[row for row in rows if row.due_on < today],
               today=[row for row in rows if row.due_on == today],
               this_week=[row for row in rows if row.due_on > today])


def needs_attention_count(s, user, today):
    """For the badge in the menu: overdue plus due today."""
    return len(open_follow_ups(s, user.id, today))


def upcoming_interviews(s, user_id, moment, days=14):
    """Interviews from an hour ago (one that's on now) to days ahead, not cancelled."""
    return s.scalars(
        select(Interview).join(Interview.application)
        .where(Application.user_id == user_id, Interview.outcome != "cancelled",
               Interview.starts_at >= moment - timedelta(hours=1),
               Interview.starts_at <= moment + timedelta(days=days))
        .options(selectinload(Interview.application).selectinload(Application.company))
        .order_by(Interview.starts_at)).all()


def no_reply_nudges(s, user, moment, today):
    """Applications quiet for too long in Applied or Screening, with no interview
    coming. The dashboard asks "Mark as No reply?"; it never changes the stage itself."""
    if not user.no_reply_days:
        return []
    coming = select(Interview.id).where(Interview.application_id == Application.id,
                                        Interview.starts_at >= moment, Interview.outcome != "cancelled")
    return s.scalars(
        select(Application)
        .where(Application.user_id == user.id, Application.stage.in_((APPLIED, SCREENING)),
               Application.stage_changed_at <= moment - timedelta(days=user.no_reply_days),
               (Application.quiet_until.is_(None)) | (Application.quiet_until <= today),
               ~coming.exists())
        .options(selectinload(Application.company))
        .order_by(Application.stage_changed_at)).all()


def keep_waiting(job, today):
    job.quiet_until = today + timedelta(days=KEEP_WAITING_DAYS)


def schedule(s, user, today, days=60):
    """The Schedule page: overdue follow-ups, then every day with something on it.
    Returns (overdue follow-ups, [(day, [(kind, row), ...]), ...])."""
    last_day = today + timedelta(days=days)
    follow_ups = open_follow_ups(s, user.id, last_day)
    interviews = s.scalars(
        select(Interview).join(Interview.application)
        .where(Application.user_id == user.id, Interview.outcome != "cancelled",
               Interview.starts_at >= day_start_utc(today, user.timezone),
               Interview.starts_at < day_start_utc(last_day + timedelta(days=1), user.timezone))
        .options(selectinload(Interview.application).selectinload(Application.company))
        .order_by(Interview.starts_at)).all()
    days_found = {}
    for interview in interviews:
        days_found.setdefault(interview_day(interview, user), []).append(("interview", interview))
    for follow_up in follow_ups:
        if follow_up.due_on >= today:
            days_found.setdefault(follow_up.due_on, []).append(("follow_up", follow_up))
    overdue = [row for row in follow_ups if row.due_on < today]
    return overdue, sorted(days_found.items())
