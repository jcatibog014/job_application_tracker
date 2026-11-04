"""Filtering, sorting and paging the Applications page, and saved views."""
import re
from datetime import date

import pytest
from sqlalchemy import select
from werkzeug.datastructures import MultiDict

from hirewire import db, filters
from hirewire.models import Note, SavedView

from .conftest import add_job, log_in_as, post


def titles(client, query=""):
    """The job titles the Applications page lists, in order."""
    page = client.get(f"/applications/{query}").get_data(as_text=True)
    return re.findall(r'class="row-link" href="/applications/\d+">([^<]+)</a>', page)


@pytest.fixture
def jobs(app, user_id):
    """A small job hunt to filter."""
    add_job(app, user_id, "Acme", "Data Analyst", "applied", location="Makati City", work_mode="hybrid",
            source="LinkedIn", salary_min=40000, salary_max=55000, applied_on=date(2026, 10, 1))
    add_job(app, user_id, "Initech", "Report Writer", "saved", location="Remote", work_mode="remote", source="Indeed")
    add_job(app, user_id, "Bluewave Bank", "Business Analyst", "interview", location="BGC, Taguig",
            work_mode="onsite", source="JobStreet", salary_min=60000, applied_on=date(2026, 10, 20),
            job_description="We use Power BI every day.")
    add_job(app, user_id, "Kalye Foods", "Data Associate", "rejected", location="Pasig", work_mode="remote",
            source="LinkedIn", salary_max=35000, applied_on=date(2026, 9, 15))
    add_job(app, user_id, "50% Off Inc", "Sales_Analyst", "offer", location="Makati City", work_mode="onsite",
            applied_on=date(2026, 10, 25))


# ---------- Reading the address ----------

def test_bad_values_are_dropped_not_errors():
    f = filters.parse_filters(MultiDict([
        ("stage", "applied"), ("stage", "promoted"), ("stage", "applied"), ("mode", "moon"),
        ("from", "yesterday"), ("pay", "lots"), ("sort", "DROP TABLE"), ("order", "up"), ("page", "-3"),
        ("q", "  data    analyst "), ("source", "LinkedIn"), ("source", "Craigslist"),
    ]))
    assert f.stages == ("applied",) and f.modes == () and f.sources == ("LinkedIn",)
    assert f.applied_from is None and f.pay_at_least is None
    assert (f.sort, f.order, f.page) == ("updated", "desc", 1)
    assert f.q == "data analyst"


def test_dates_the_wrong_way_round_are_swapped():
    f = filters.parse_filters({"from": "2026-10-31", "to": "2026-10-01"})
    assert (f.applied_from, f.applied_to) == (date(2026, 10, 1), date(2026, 10, 31))


def test_the_address_round_trips_without_defaults():
    args = MultiDict([("q", "data"), ("stage", "applied"), ("stage", "interview"), ("mode", "remote"),
                      ("pay", "40000"), ("sort", "pay"), ("order", "asc"), ("page", "2")])
    f = filters.parse_filters(args)
    assert filters.parse_filters(MultiDict(_flatten(filters.to_args(f)))) == f
    assert filters.to_args(filters.parse_filters({})) == {}
    assert filters.query_string(f, page=1) == "q=data&stage=applied&stage=interview&mode=remote&pay=40000&sort=pay&order=asc"


def _flatten(args):
    return [(name, item) for name, value in args.items() for item in (value if isinstance(value, list) else [value])]


def test_sort_links_turn_the_order_round():
    f = filters.parse_filters({"sort": "company"})
    assert filters.sort_link(f, "company")["order"] == "desc"
    assert filters.sort_link(f, "pay") == {"sort": "pay", "order": "desc"}
    assert filters.sort_link(filters.parse_filters({}), "updated") == {"sort": "updated", "order": "asc"}


def test_each_chip_removes_only_its_own_filter():
    f = filters.parse_filters(MultiDict([("stage", "applied"), ("stage", "offer"), ("mode", "remote")]))
    chips = dict(filters.chips(f))
    assert chips["Applied"] == {"stage": ["offer"], "mode": ["remote"]}
    assert chips["Remote"] == {"stage": ["applied", "offer"]}


# ---------- The list ----------

def test_closed_applications_are_hidden_unless_asked(me, jobs):
    assert "Data Associate" not in titles(me)
    assert "Data Associate" in titles(me, "?closed=1")
    assert titles(me, "?stage=rejected") == ["Data Associate"]


@pytest.mark.parametrize("query, expected", [
    ("?stage=saved&stage=offer", {"Report Writer", "Sales_Analyst"}),
    ("?mode=remote", {"Report Writer"}),
    ("?mode=remote&closed=1", {"Report Writer", "Data Associate"}),
    ("?source=LinkedIn&closed=1", {"Data Analyst", "Data Associate"}),
    ("?location=makati", {"Data Analyst", "Sales_Analyst"}),
    ("?from=2026-10-10", {"Business Analyst", "Sales_Analyst"}),
    ("?from=2026-10-01&to=2026-10-20", {"Data Analyst", "Business Analyst"}),
    ("?pay=50000&closed=1", {"Data Analyst", "Business Analyst"}),  # the top of the range counts
    ("?q=analyst", {"Data Analyst", "Business Analyst", "Sales_Analyst"}),
    ("?q=BLUEWAVE", {"Business Analyst"}),  # company names, any case
    ("?q=power bi", {"Business Analyst"}),  # the saved job description
    ("?mode=onsite&stage=interview&stage=offer&location=taguig", {"Business Analyst"}),
])
def test_filters_alone_and_together(me, jobs, query, expected):
    assert set(titles(me, query)) == expected


def test_search_finds_notes(app, me, user_id, jobs):
    job_id = add_job(app, user_id, "Zeta", "Clerk")
    with app.app_context():
        db.session().add(Note(application_id=job_id, body="Referred by Tita Nena"))
        db.session().commit()
    assert titles(me, "?q=nena") == ["Clerk"]


def test_wildcards_in_a_search_are_plain_letters(me, jobs):
    assert titles(me, "?q=50%25") == ["Sales_Analyst"]  # %25 is "%"
    assert titles(me, "?q=s_a") == ["Sales_Analyst"]  # "_" matches only "_", not any letter


def test_sorting(me, jobs):
    assert titles(me, "?sort=company&order=asc") == ["Sales_Analyst", "Data Analyst", "Business Analyst",
                                                    "Report Writer"]
    # Pay: highest first, jobs with no pay at the end either way.
    by_pay = titles(me, "?sort=pay&order=desc")
    assert by_pay[:2] == ["Business Analyst", "Data Analyst"]
    assert set(by_pay[2:]) == {"Sales_Analyst", "Report Writer"}
    assert titles(me, "?sort=pay&order=asc")[:2] == ["Data Analyst", "Business Analyst"]
    assert titles(me, "?sort=stage&order=asc") == ["Report Writer", "Data Analyst", "Business Analyst",
                                                  "Sales_Analyst"]
    assert titles(me, "?sort=applied&order=asc")[0] == "Data Analyst"
    assert titles(me, "?sort=applied&order=asc")[-1] == "Report Writer"  # no date: last


def test_paging(app, me, user_id):
    for number in range(filters.PER_PAGE + 3):
        add_job(app, user_id, f"Company {number:02}", f"Job {number:02}")
    first = titles(me, "?sort=company&order=asc")
    assert len(first) == filters.PER_PAGE and first[0] == "Job 00"
    page = me.get("/applications/?sort=company&order=asc").get_data(as_text=True)
    assert "Showing 1–25 of 28" in page and "page=2" in page
    assert titles(me, "?sort=company&order=asc&page=2") == ["Job 25", "Job 26", "Job 27"]
    assert titles(me, "?sort=company&order=asc&page=99") == ["Job 25", "Job 26", "Job 27"]  # the last page


def test_empty_results_say_why(me, jobs):
    page = me.get("/applications/?q=astronaut").data
    assert b"No Matching Applications" in page and b"Clear all" in page


# ---------- Saved views ----------

def test_new_accounts_get_starter_views(app, client):
    post(client, "/signup", {"username": "carla", "password": "long enough", "confirm_password": "long enough"})
    page = client.get("/applications/").get_data(as_text=True)
    assert ">Active</a>" in page and ">Needs Follow-up</a>" in page and ">Interviews This Week</a>" in page


def test_save_and_open_a_view(app, me, jobs):
    response = post(me, "/applications/views", {"name": "Remote jobs", "query": "mode=remote&closed=1&page=3"})
    assert response.location.endswith("/applications/?mode=remote&closed=1")
    with app.app_context():
        view = db.session().scalar(select(SavedView).where(SavedView.name == "Remote jobs"))
    assert view.query == "mode=remote&closed=1"  # cleaned, and without the page
    page = me.get("/applications/?mode=remote&closed=1").get_data(as_text=True)
    assert 'aria-current="page">Remote jobs</a>' in page
    assert "Delete the view Remote jobs" in page


def test_saving_the_same_name_replaces_the_view(app, me):
    post(me, "/applications/views", {"name": "Mine", "query": "mode=remote"})
    post(me, "/applications/views", {"name": "Mine", "query": "mode=onsite"})
    with app.app_context():
        views = db.session().scalars(select(SavedView).where(SavedView.name == "Mine")).all()
    assert [view.query for view in views] == ["mode=onsite"]


def test_a_view_needs_a_name(app, me):
    post(me, "/applications/views", {"name": " ", "query": "mode=onsite"})
    with app.app_context():
        assert db.session().scalar(select(SavedView).where(SavedView.query == "mode=onsite")) is None


def test_delete_a_view_and_privacy(app, client, user_id, other_id):
    with app.app_context():
        s = db.session()
        s.add_all([SavedView(user_id=other_id, name="Theirs", query="mode=remote"),
                   SavedView(user_id=user_id, name="Mine", query="mode=onsite")])
        s.commit()
        theirs, mine = (s.scalar(select(SavedView.id).where(SavedView.name == name)) for name in ("Theirs", "Mine"))
    log_in_as(client, user_id)
    assert b"Theirs" not in client.get("/applications/").data
    assert post(client, f"/applications/views/{theirs}/delete").status_code == 404
    post(client, f"/applications/views/{mine}/delete")
    with app.app_context():
        names = db.session().scalars(select(SavedView.name).where(SavedView.name.in_(["Theirs", "Mine"]))).all()
    assert names == ["Theirs"]
