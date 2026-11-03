"""Filtering the Applications page.

The filters live in the address (?stage=applied&mode=remote&sort=pay), so a
filtered view can be bookmarked, shared with yourself, or saved by name.

    parse_filters(request.args)  -> Filters  (bad values are dropped, never an error)
    apply_filters(query, f, today) -> the same query, narrowed and sorted
    to_args(f)                   -> the address again, without the defaults

Both are plain functions, so the tests check them without a browser.
"""
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import urlencode

from sqlalchemy import case, func, or_, select
from werkzeug.datastructures import MultiDict

from .dates import parse_day
from .models import ACTIVE_STAGES, STAGE_LABELS, STAGES, SOURCES, WORK_MODES, Application, Company, Note, SavedView

PER_PAGE = 25
TEXT_LIMIT = 100
SORTS = {
    # name in the address: (column header, what to sort by)
    "company": "Company",
    "role": "Job title",
    "stage": "Stage",
    "applied": "Applied",
    "pay": "Pay",
    "updated": "Last change",
}
DEFAULT_SORT = ("updated", "desc")


@dataclass(frozen=True)
class Filters:
    q: str = ""
    stages: tuple = ()
    modes: tuple = ()
    sources: tuple = ()
    location: str = ""
    applied_from: date | None = None
    applied_to: date | None = None
    pay_at_least: int | None = None
    closed: bool = False  # with no stage chosen, also show closed ones
    sort: str = DEFAULT_SORT[0]
    order: str = DEFAULT_SORT[1]
    page: int = 1


def _choices(args, name, allowed):
    """Every value of a repeated field that is allowed, once each, in the allowed order."""
    chosen = set(args.getlist(name))
    return tuple(value for value in allowed if value in chosen)


def _text(args, name):
    return " ".join((args.get(name) or "").split())[:TEXT_LIMIT]


def _whole(args, name, low=1, high=10**9):
    raw = (args.get(name) or "").replace(",", "").strip()
    return int(raw) if raw.isdigit() and low <= int(raw) <= high else None


def parse_filters(args):
    """The address's filters -> Filters. Anything wrong is quietly left out."""
    if not isinstance(args, MultiDict):
        args = MultiDict(args)
    applied_from, applied_to = parse_day(args.get("from")), parse_day(args.get("to"))
    if applied_from and applied_to and applied_from > applied_to:
        applied_from, applied_to = applied_to, applied_from  # surely meant the other way round
    sort = args.get("sort") if args.get("sort") in SORTS else DEFAULT_SORT[0]
    order = args.get("order") if args.get("order") in ("asc", "desc") else ("desc" if sort in ("updated", "applied", "pay") else "asc")
    return Filters(
        q=_text(args, "q"),
        stages=_choices(args, "stage", STAGES),
        modes=_choices(args, "mode", tuple(WORK_MODES)),
        sources=_choices(args, "source", SOURCES),
        location=_text(args, "location"),
        applied_from=applied_from,
        applied_to=applied_to,
        pay_at_least=_whole(args, "pay"),
        closed=args.get("closed") == "1",
        sort=sort,
        order=order,
        page=_whole(args, "page", high=100_000) or 1,
    )


def to_args(f, **changes):
    """Filters -> the address's fields (a dict; lists repeat), leaving out defaults.
    changes replace fields first, so to_args(f, page=2) is the next page's link."""
    f = replace(f, **changes)
    args = {}
    if f.q:
        args["q"] = f.q
    if f.stages:
        args["stage"] = list(f.stages)
    if f.modes:
        args["mode"] = list(f.modes)
    if f.sources:
        args["source"] = list(f.sources)
    if f.location:
        args["location"] = f.location
    if f.applied_from:
        args["from"] = f.applied_from.isoformat()
    if f.applied_to:
        args["to"] = f.applied_to.isoformat()
    if f.pay_at_least:
        args["pay"] = str(f.pay_at_least)
    if f.closed and not f.stages:
        args["closed"] = "1"
    if (f.sort, f.order) != DEFAULT_SORT:
        args["sort"], args["order"] = f.sort, f.order
    if f.page > 1:
        args["page"] = str(f.page)
    return args


def query_string(f, **changes):
    return urlencode(to_args(f, **changes), doseq=True)


def is_filtered(f):
    """True if anything narrows the list (sorting and paging don't)."""
    return bool(to_args(f, sort=DEFAULT_SORT[0], order=DEFAULT_SORT[1], page=1))


def sort_link(f, column):
    """The header's link: sort by this column, or turn the order round if it already is."""
    if f.sort == column:
        return to_args(f, order="asc" if f.order == "desc" else "desc", page=1)
    return to_args(f, sort=column, order="desc" if column in ("updated", "applied", "pay") else "asc", page=1)


def chips(f):
    """One small label per filter in use, each with the address that removes it."""
    found = []
    if f.q:
        found.append((f'"{f.q}"', to_args(f, q="", page=1)))
    for stage in f.stages:
        found.append((STAGE_LABELS[stage], to_args(f, stages=tuple(s for s in f.stages if s != stage), page=1)))
    for mode in f.modes:
        found.append((WORK_MODES[mode], to_args(f, modes=tuple(m for m in f.modes if m != mode), page=1)))
    for source in f.sources:
        found.append((source, to_args(f, sources=tuple(s for s in f.sources if s != source), page=1)))
    if f.location:
        found.append((f"In {f.location}", to_args(f, location="", page=1)))
    if f.applied_from:
        found.append((f"Applied from {f.applied_from:%b} {f.applied_from.day}", to_args(f, applied_from=None, page=1)))
    if f.applied_to:
        found.append((f"Applied until {f.applied_to:%b} {f.applied_to.day}", to_args(f, applied_to=None, page=1)))
    if f.pay_at_least:
        found.append((f"Pay at least {f.pay_at_least:,}", to_args(f, pay_at_least=None, page=1)))
    if f.closed and not f.stages:
        found.append(("With closed", to_args(f, closed=False, page=1)))
    return found


def stage_order():
    """Sort by stage along the road (Saved first), not by the alphabet."""
    return case({stage: index for index, stage in enumerate(STAGES)}, value=Application.stage)


def apply_filters(query, f, today):
    """Narrow and sort a SELECT of Application that already joins Company."""
    if f.stages:
        query = query.where(Application.stage.in_(f.stages))
    elif not f.closed:
        query = query.where(Application.stage.in_(ACTIVE_STAGES))
    if f.q:
        notes = select(Note.id).where(Note.application_id == Application.id, Note.body.icontains(f.q, autoescape=True))
        query = query.where(or_(
            Application.role_title.icontains(f.q, autoescape=True),
            Company.name.icontains(f.q, autoescape=True),
            Application.location.icontains(f.q, autoescape=True),
            Application.job_description.icontains(f.q, autoescape=True),
            notes.exists(),
        ))
    if f.modes:
        query = query.where(Application.work_mode.in_(f.modes))
    if f.sources:
        query = query.where(Application.source.in_(f.sources))
    if f.location:
        query = query.where(Application.location.icontains(f.location, autoescape=True))
    if f.applied_from:
        query = query.where(Application.applied_on >= f.applied_from)
    if f.applied_to:
        query = query.where(Application.applied_on <= f.applied_to)
    if f.pay_at_least:
        # The top of the range counts; a job with only one number uses that one.
        top = func.coalesce(Application.salary_max, Application.salary_min)
        query = query.where(top >= f.pay_at_least)
    for narrow in EXTRA_FILTERS:
        query = narrow(query, f, today)
    return query.order_by(*sort_columns(f))


def sort_columns(f):
    column = {
        "company": Company.name_key,
        "role": func.lower(Application.role_title),
        "stage": stage_order(),
        "applied": Application.applied_on,
        "pay": func.coalesce(Application.salary_max, Application.salary_min),
        "updated": Application.updated_at,
    }[f.sort]
    column = column.desc() if f.order == "desc" else column.asc()
    # Empty dates and pay go last either way, and equal rows keep a steady order.
    return [column.nulls_last(), Application.id.desc()]


# Later stages add filters here: functions (query, f, today) -> query.
EXTRA_FILTERS = []


# ---------- Saved views ----------

STARTER_VIEWS = [
    ("Active", {"stage": ["applied", "screening", "interview", "offer"]}),
    ("Remote", {"mode": ["remote"]}),
]
VIEW_NAME_LIMIT = 60


def add_starter_views(s, user):
    """Every new account gets a few views to start with (it can delete them)."""
    for name, args in STARTER_VIEWS:
        s.add(SavedView(user_id=user.id, name=name, query=query_string(parse_filters(args))))


def view_query(args):
    """The part of an address a saved view keeps: the filters and the sort, not the page."""
    return query_string(parse_filters(args), page=1)
