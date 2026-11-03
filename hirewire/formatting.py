"""Filters for the templates: dates and money the way people read them.

Moments are shown in the logged-in person's time zone.
"""
from datetime import date, timedelta

from flask import g

from .dates import DEFAULT_TIMEZONE, local_today, to_local


def person_timezone():
    user = g.get("user")
    return user.timezone if user else DEFAULT_TIMEZONE


def nice_day(day):
    """Nov 3, 2026 (written by hand: %-d doesn't work on Windows)."""
    return f"{day:%b} {day.day}, {day.year}"


def short_day(day):
    """Nov 3 this year, Nov 3, 2025 in other years."""
    if day.year == local_today(person_timezone()).year:
        return f"{day:%b} {day.day}"
    return nice_day(day)


def nice_time(moment):
    """2:30 PM"""
    local = to_local(moment, person_timezone())
    return f"{local.hour % 12 or 12}:{local:%M %p}"


def nice_date(moment):
    return nice_day(to_local(moment, person_timezone()).date())


def nice_datetime(moment):
    """Nov 3, 2026, 2:30 PM"""
    return f"{nice_date(moment)}, {nice_time(moment)}"


def local_day(moment):
    return to_local(moment, person_timezone()).date()


def relative_day(day):
    """Today, Tomorrow, Yesterday, In 3 days, 5 days ago, or a date further away."""
    if not isinstance(day, date):
        day = local_day(day)
    days = (day - local_today(person_timezone())).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days == -1:
        return "Yesterday"
    if 1 < days < 7:
        return f"In {days} days"
    if -7 < days < -1:
        return f"{-days} days ago"
    return short_day(day)


def input_datetime(moment):
    """The value a <input type="datetime-local"> wants: 2026-11-12T14:30"""
    return f"{to_local(moment, person_timezone()):%Y-%m-%dT%H:%M}" if moment else ""


def money(amount, currency="PHP"):
    """PHP 45,000"""
    return f"{currency} {amount:,}"


def salary_range(low, high, currency="PHP"):
    if low and high and low != high:
        return f"{currency} {low:,}–{high:,}"
    if low or high:
        return money(low or high, currency)
    return ""


def init_app(app):
    for name, function in {
        "nice_day": nice_day, "short_day": short_day, "nice_time": nice_time, "nice_date": nice_date,
        "nice_datetime": nice_datetime, "local_day": local_day, "relative_day": relative_day,
        "input_datetime": input_datetime, "money": money, "salary_range": salary_range,
    }.items():
        app.jinja_env.filters[name] = function
    app.jinja_env.globals["timedelta"] = timedelta
