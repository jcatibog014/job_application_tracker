"""Reading form fields: trimmed text, whole numbers, dates and web links.

Each helper returns (value, problem). The problem is None when the value is fine,
else a short sentence for the page.
"""
import re
from urllib.parse import urlsplit

from .dates import parse_day

OTHER_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:(?!\d)", re.IGNORECASE)


def text(form, name, limit, required=False, label="This"):
    value = (form.get(name) or "").replace("\r\n", "\n").strip()
    if required and not value:
        return value, f"{label} is needed."
    if len(value) > limit:
        return value, f"Use at most {limit:,} characters."
    return value, None


def whole_number(form, name, low=0, high=1_000_000_000):
    """Digits with optional commas ("45,000") -> 45000. Empty -> None."""
    raw = (form.get(name) or "").replace(",", "").replace(" ", "").strip()
    if not raw:
        return None, None
    if not raw.isdigit() or not low <= int(raw) <= high:
        return None, f"Use a whole number from {low:,} to {high:,}."
    return int(raw), None


def day(form, name, required=False):
    raw = (form.get(name) or "").strip()
    if not raw:
        return None, "Choose a date." if required else None
    value = parse_day(raw)
    return value, None if value else "Use a date like 2026-11-12."


def web_link(form, name):
    """An http(s) address, or empty. "acme.com/jobs" gets https:// in front."""
    value = (form.get(name) or "").strip()
    if not value:
        return "", None
    problem = "Use a web address like https://example.com/jobs/123."
    if "://" not in value:
        # "javascript:..." or "mailto:..." already name another kind of link.
        # A port ("localhost:5006") is digits after the colon, so it isn't one.
        if OTHER_SCHEME.match(value):
            return value, problem
        value = "https://" + value
    parts = urlsplit(value)
    try:
        parts.port  # noqa: B018  (raises ValueError for a port like :abc)
    except ValueError:
        return value, problem
    if parts.scheme not in ("http", "https") or not parts.hostname or " " in value:
        return value, problem
    if len(value) > 500:
        return value, "That address is too long (at most 500 characters)."
    return value, None


def choice(form, name, allowed, default=""):
    value = form.get(name, default)
    return (value, None) if value in allowed else (default, "Choose one from the list.")
