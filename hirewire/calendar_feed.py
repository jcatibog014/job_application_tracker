"""The calendar feed: interviews and follow-ups as an .ics file.

Google Calendar (or Apple, or Outlook) subscribes to the private address
/calendar/<token>.ics and puts the events on your phone, with its own
reminders. That is how Hire Wire gets real notifications without running
anything in the background.

The token in the address is the only key, so Settings can make a new one
(the old address stops working) or turn the feed off.
"""
import secrets
from datetime import UTC, timedelta

from icalendar import Alarm, Calendar, Event
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import Application, FollowUp, Interview

PAST_DAYS = 30  # keep a month of history in the calendar, so it doesn't vanish the day after
DESCRIPTION_LIMIT = 1000


def new_token():
    return secrets.token_urlsafe(24)


def aware(moment):
    return moment.replace(tzinfo=UTC)


def interview_event(interview, stamp):
    job = interview.application
    event = Event()
    event.add("uid", f"interview-{interview.id}@hirewire")
    event.add("dtstamp", stamp)
    event.add("dtstart", aware(interview.starts_at))
    event.add("dtend", aware(interview.starts_at + timedelta(minutes=interview.minutes)))
    event.add("summary", f"Interview: {job.role_title} at {job.company.name}")
    lines = [interview.kind_label]
    if interview.with_whom:
        lines.append(f"With {interview.with_whom}")
    if interview.prep_notes:
        lines += ["", interview.prep_notes]
    event.add("description", "\n".join(lines)[:DESCRIPTION_LIMIT])
    if interview.place_is_link:
        event.add("url", interview.place)
        event.add("location", interview.place)
    elif interview.place:
        event.add("location", interview.place)
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Interview with {job.company.name} in 1 hour")
    alarm.add("trigger", timedelta(hours=-1))
    event.add_component(alarm)
    return event


def follow_up_event(follow_up, stamp):
    job = follow_up.application
    event = Event()
    event.add("uid", f"followup-{follow_up.id}@hirewire")
    event.add("dtstamp", stamp)
    event.add("dtstart", follow_up.due_on)  # a date: an all-day event
    event.add("dtend", follow_up.due_on + timedelta(days=1))
    event.add("summary", f"Follow up: {job.company.name} ({job.role_title})")
    event.add("description", follow_up.note[:DESCRIPTION_LIMIT])
    event.add("transp", "TRANSPARENT")  # a reminder, not a busy hour
    return event


def build(s, user, moment, today):
    """The whole calendar for one user, as bytes."""
    calendar = Calendar()
    calendar.add("prodid", "-//Hire Wire//Job applications//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Hire Wire")
    calendar.add("x-wr-caldesc", "Interviews and follow-ups from Hire Wire")
    # Hints to check again every 6 hours. Most calendar apps decide for themselves.
    calendar.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "PT6H")
    stamp = aware(moment)
    interviews = s.scalars(
        select(Interview).join(Interview.application)
        .where(Application.user_id == user.id, Interview.outcome != "cancelled",
               Interview.starts_at >= moment - timedelta(days=PAST_DAYS))
        .options(selectinload(Interview.application).selectinload(Application.company))
        .order_by(Interview.starts_at)).all()
    follow_ups = s.scalars(
        select(FollowUp).join(FollowUp.application)
        .where(Application.user_id == user.id, FollowUp.done_at.is_(None),
               FollowUp.due_on >= today - timedelta(days=PAST_DAYS))
        .options(selectinload(FollowUp.application).selectinload(Application.company))
        .order_by(FollowUp.due_on)).all()
    for interview in interviews:
        calendar.add_component(interview_event(interview, stamp))
    for follow_up in follow_ups:
        calendar.add_component(follow_up_event(follow_up, stamp))
    return calendar.to_ical()
