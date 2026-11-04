"""Times and days.

The database holds two kinds:
- moments (a stage change, an interview) as naive UTC datetimes, from utcnow();
- days (the day you applied, a follow-up's due day) as plain dates, which are
  already the person's own calendar day.

People see moments in their own time zone (users.timezone, chosen in Settings).
"""
from datetime import UTC, date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_TIMEZONE = "Asia/Manila"


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


@cache
def zone(name):
    """The time zone called name, or Manila's if that name is unknown."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


@cache
def timezone_names():
    """Every place a person can choose, like "Asia/Manila", sorted."""
    return sorted(name for name in available_timezones() if "/" in name and not name.startswith(("Etc/", "SystemV/")))


def is_timezone(name):
    return name in timezone_names() or name == "UTC"


def to_local(moment, tz_name):
    """Naive UTC from the database -> an aware datetime in that time zone."""
    return moment.replace(tzinfo=UTC).astimezone(zone(tz_name))


def to_utc(local, tz_name):
    """A naive datetime on a person's own clock -> naive UTC for the database."""
    return local.replace(tzinfo=zone(tz_name)).astimezone(UTC).replace(tzinfo=None)


def local_today(tz_name, moment=None):
    """The calendar day it is for a person now (or at moment, naive UTC)."""
    return to_local(moment or utcnow(), tz_name).date()


def parse_local(text, tz_name):
    """What a <input type="datetime-local"> sends ("2026-11-12T14:30"), on the
    person's own clock -> naive UTC. Raises ValueError if it isn't a date and time."""
    return to_utc(datetime.fromisoformat(text), tz_name)


def parse_day(text):
    """What a <input type="date"> sends ("2026-11-12") -> a date, or None if empty or wrong."""
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def day_start_utc(day, tz_name):
    """Midnight at the start of day on the person's clock, as naive UTC."""
    return to_utc(datetime(day.year, day.month, day.day), tz_name)


def week_start(day):
    """The Monday on or before day."""
    return day - timedelta(days=day.weekday())
