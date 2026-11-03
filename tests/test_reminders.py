"""Interviews, follow-ups, automatic reminders, the nudge, the Schedule and the calendar feed."""
from datetime import date, datetime, timedelta

import pytest
from icalendar import Calendar
from sqlalchemy import select

from hirewire import db, reminders
from hirewire.dates import local_today, utcnow
from hirewire.models import AFTER_APPLIED, THANK_YOU, Application, FollowUp, Interview, User

from .conftest import add_job, get_user, log_in_as, post

DAY = timedelta(days=1)


def follow_ups(app, job_id=None, **where):
    with app.app_context():
        query = select(FollowUp).order_by(FollowUp.id)
        if job_id:
            query = query.where(FollowUp.application_id == job_id)
        for name, value in where.items():
            query = query.where(getattr(FollowUp, name) == value)
        return db.session().scalars(query).all()


def interviews(app):
    with app.app_context():
        return db.session().scalars(select(Interview).order_by(Interview.id)).all()


def add_follow_up(app, job_id, due_on, note="Email them", **fields):
    with app.app_context():
        s = db.session()
        row = FollowUp(application_id=job_id, due_on=due_on, note=note, **fields)
        s.add(row)
        s.commit()
        return row.id


def add_interview(app, job_id, starts_at, **fields):
    with app.app_context():
        s = db.session()
        row = Interview(application_id=job_id, starts_at=starts_at, **fields)
        s.add(row)
        s.commit()
        return row.id


def today():
    return local_today("Asia/Manila")


def new_job(client, stage="applied", applied_on=""):
    from .test_applications import FORM
    response = post(client, "/applications/new", {**FORM, "stage": stage, "applied_on": applied_on})
    return int(response.location.rsplit("/", 1)[1])


# ---------- Automatic follow-ups ----------

def test_applying_adds_a_follow_up_a_week_later(app, me):
    job_id = new_job(me, applied_on="2026-11-02")
    [row] = follow_ups(app, job_id)
    assert row.due_on == date(2026, 11, 9) and row.auto_kind == AFTER_APPLIED


def test_saved_jobs_get_no_follow_up_until_applied(app, me):
    job_id = new_job(me, stage="saved")
    assert follow_ups(app, job_id) == []
    post(me, f"/applications/{job_id}/move", {"to": "applied"})
    assert [row.due_on for row in follow_ups(app, job_id)] == [today() + 7 * DAY]


def test_the_setting_changes_or_stops_it(app, me, user_id):
    post(me, "/settings/", {"action": "reminders", "follow_up_days": "3", "no_reply_days": "21"})
    job_id = new_job(me, applied_on="2026-11-02")
    assert follow_ups(app, job_id)[0].due_on == date(2026, 11, 5)
    post(me, "/settings/", {"action": "reminders", "follow_up_days": "0", "no_reply_days": "21"})
    assert follow_ups(app, new_job(me)) == []


def test_bad_reminder_settings_are_refused(app, me):
    response = post(me, "/settings/", {"action": "reminders", "follow_up_days": "4", "no_reply_days": "21"})
    assert response.status_code == 400
    assert get_user(app, "ana").follow_up_days == 7


def test_a_reply_removes_the_automatic_follow_up_but_not_mine(app, me):
    job_id = new_job(me)
    add_follow_up(app, job_id, today() + DAY, "Ask Tita Nena about it")
    post(me, f"/applications/{job_id}/move", {"to": "screening"})
    assert [row.note for row in follow_ups(app, job_id)] == ["Ask Tita Nena about it"]


def test_a_done_automatic_follow_up_stays_as_history(app, me):
    job_id = new_job(me)
    [row] = follow_ups(app, job_id)
    post(me, f"/follow-ups/{row.id}/done")
    post(me, f"/applications/{job_id}/move", {"to": "rejected"})
    assert len(follow_ups(app, job_id)) == 1
    assert b"Followed up" in me.get(f"/applications/{job_id}").data


# ---------- Interviews ----------

INTERVIEW_FORM = {"starts_at": "2026-11-12T14:30", "minutes": "60", "kind": "video", "with_whom": "Ms. Reyes",
                  "place": "https://meet.example.com/abc", "prep_notes": "Ask about the team."}


def test_add_an_interview_moves_the_stage_and_adds_a_thank_you(app, me):
    job_id = new_job(me)
    response = post(me, f"/applications/{job_id}/interviews/new", INTERVIEW_FORM)
    assert response.status_code == 302
    [interview] = interviews(app)
    assert interview.starts_at == datetime(2026, 11, 12, 6, 30)  # 2:30 PM in Manila is 6:30 AM UTC
    with app.app_context():
        assert db.session().get(Application, job_id).stage == "interview"
    rows = follow_ups(app, job_id)
    # The "after applied" one went (they replied); the thank-you is the next day.
    assert [(row.auto_kind, row.due_on) for row in rows] == [(THANK_YOU, date(2026, 11, 13))]
    assert "Ms. Reyes" in rows[0].note
    page = me.get(f"/applications/{job_id}").get_data(as_text=True)
    assert "2:30 PM" in page and "Join link" in page and "Ask about the team." in page


def test_the_interview_time_follows_my_time_zone(app, me, user_id):
    post(me, "/settings/", {"action": "timezone", "timezone": "America/New_York"})
    job_id = new_job(me)
    post(me, f"/applications/{job_id}/interviews/new", INTERVIEW_FORM)
    assert interviews(app)[0].starts_at == datetime(2026, 11, 12, 19, 30)  # EST is UTC-5


def test_moving_the_interview_moves_its_thank_you(app, me):
    job_id = new_job(me)
    post(me, f"/applications/{job_id}/interviews/new", INTERVIEW_FORM)
    interview_id = interviews(app)[0].id
    post(me, f"/interviews/{interview_id}/edit", {**INTERVIEW_FORM, "starts_at": "2026-11-20T09:00", "outcome": "pending"})
    assert [row.due_on for row in follow_ups(app, job_id, auto_kind=THANK_YOU)] == [date(2026, 11, 21)]
    post(me, f"/interviews/{interview_id}/edit", {**INTERVIEW_FORM, "outcome": "cancelled"})
    assert follow_ups(app, job_id, auto_kind=THANK_YOU) == []


def test_a_bad_interview_form_is_explained(app, me):
    job_id = new_job(me)
    response = post(me, f"/applications/{job_id}/interviews/new", {**INTERVIEW_FORM, "starts_at": "soon"})
    assert response.status_code == 400 and b"date and time like" in response.data
    assert interviews(app) == []


def test_how_did_it_go_and_delete(app, me, user_id):
    job_id = add_job(app, user_id, stage="interview")
    interview_id = add_interview(app, job_id, utcnow() - DAY)
    assert b"How did it go?" in me.get(f"/applications/{job_id}").data
    post(me, f"/interviews/{interview_id}/outcome", {"outcome": "passed"})
    assert interviews(app)[0].outcome == "passed"
    assert post(me, f"/interviews/{interview_id}/outcome", {"outcome": "hired"}).status_code == 400
    post(me, f"/interviews/{interview_id}/delete")
    assert interviews(app) == []


# ---------- Follow-ups by hand ----------

def test_add_snooze_done_undo_edit_delete(app, me, user_id):
    job_id = add_job(app, user_id)
    post(me, f"/applications/{job_id}/follow-ups", {"note": "Call HR", "due_on": "2026-01-01"})
    [row] = follow_ups(app, job_id)
    assert b"Overdue" in me.get(f"/applications/{job_id}").data
    post(me, f"/follow-ups/{row.id}/snooze", {"days": "3"})
    assert follow_ups(app, job_id)[0].due_on == today() + 3 * DAY  # from today, not from the old day
    assert post(me, f"/follow-ups/{row.id}/snooze", {"days": "100"}).status_code == 400
    post(me, f"/follow-ups/{row.id}/done")
    assert follow_ups(app, job_id)[0].done_at is not None
    post(me, f"/follow-ups/{row.id}/not-done")
    assert follow_ups(app, job_id)[0].done_at is None
    post(me, f"/follow-ups/{row.id}/edit", {"note": "Call HR again", "due_on": "2026-12-01"})
    assert follow_ups(app, job_id)[0].note == "Call HR again"
    post(me, f"/follow-ups/{row.id}/delete")
    assert follow_ups(app, job_id) == []


def test_a_follow_up_needs_a_note_and_a_day(app, me, user_id):
    job_id = add_job(app, user_id)
    post(me, f"/applications/{job_id}/follow-ups", {"note": "", "due_on": "2026-12-01"})
    post(me, f"/applications/{job_id}/follow-ups", {"note": "x", "due_on": ""})
    assert follow_ups(app, job_id) == []


def test_buttons_go_back_to_the_page_they_were_on(app, me, user_id):
    job_id = add_job(app, user_id)
    row_id = add_follow_up(app, job_id, today())
    assert post(me, f"/follow-ups/{row_id}/done", {"next": "/dashboard/"}).location.endswith("/dashboard/")
    assert post(me, f"/follow-ups/{row_id}/not-done", {"next": "//evil.example"}).location.endswith(
        f"/applications/{job_id}#follow-ups")


# ---------- What is due ----------

def test_due_groups_and_their_edges(app, ctx, user_id):
    user = ctx.get(User, user_id)
    job_id = add_job(app, user_id)
    for days in (-2, -1, 0, 1, 7, 8):
        add_follow_up(app, job_id, today() + days * DAY, f"day {days}")
    add_follow_up(app, job_id, today(), "already done", done_at=utcnow())
    groups = reminders.due(ctx, user, today())
    assert [row.note for row in groups.overdue] == ["day -2", "day -1"]
    assert [row.note for row in groups.today] == ["day 0"]
    assert [row.note for row in groups.this_week] == ["day 1", "day 7"]
    assert groups.needs_attention == 3


def test_today_depends_on_the_time_zone(app, ctx, user_id):
    # 23:30 UTC on Nov 3 is already Nov 4 in Manila, but still Nov 3 in New York.
    moment = datetime(2026, 11, 3, 23, 30)
    assert local_today("Asia/Manila", moment) == date(2026, 11, 4)
    assert local_today("America/New_York", moment) == date(2026, 11, 3)


def test_the_menu_badge_counts_overdue_and_today(app, me, user_id):
    job_id = add_job(app, user_id)
    add_follow_up(app, job_id, today() - DAY)
    add_follow_up(app, job_id, today())
    add_follow_up(app, job_id, today() + DAY)
    page = me.get("/dashboard/").get_data(as_text=True)
    assert '<span class="badge">2<span class="visually-hidden"> waiting</span>' in page


# ---------- The No reply nudge ----------

def test_the_nudge_after_21_quiet_days(app, me, user_id):
    old = utcnow() - timedelta(days=22)
    add_job(app, user_id, "Quiet Corp", "Analyst", moment=old)
    add_job(app, user_id, "Fresh Corp", "Analyst", moment=utcnow() - timedelta(days=20))
    page = me.get("/dashboard/").get_data(as_text=True)
    assert "Quiet Corp" in page and "No news for 22 days" in page
    assert page.count("No news for") == 1  # Fresh Corp has waited only 20 days


def test_no_nudge_with_an_interview_coming(app, me, user_id):
    job_id = add_job(app, user_id, "Quiet Corp", stage="screening", moment=utcnow() - timedelta(days=30))
    add_interview(app, job_id, utcnow() + DAY)
    assert b"No news for" not in me.get("/dashboard/").data


def test_keep_waiting_and_mark_no_reply(app, me, user_id):
    job_id = add_job(app, user_id, "Quiet Corp", moment=utcnow() - timedelta(days=30))
    post(me, f"/applications/{job_id}/keep-waiting")
    assert b"No news for" not in me.get("/dashboard/").data
    with app.app_context():
        s = db.session()
        s.get(Application, job_id).quiet_until = today()  # a week later...
        s.commit()
    assert b"No news for" in me.get("/dashboard/").data
    post(me, f"/applications/{job_id}/no-reply")
    with app.app_context():
        assert db.session().get(Application, job_id).stage == "no_reply"


def test_the_nudge_can_be_switched_off(app, me, user_id):
    add_job(app, user_id, "Quiet Corp", moment=utcnow() - timedelta(days=60))
    post(me, "/settings/", {"action": "reminders", "follow_up_days": "7", "no_reply_days": "0"})
    assert b"No news for" not in me.get("/dashboard/").data


# ---------- Dashboard and Schedule ----------

def test_the_dashboard(app, me, user_id):
    assert b"Welcome to Hire Wire" in me.get("/dashboard/").data
    job_id = add_job(app, user_id, "Acme", "Data Analyst")
    add_interview(app, job_id, utcnow() + 2 * DAY, with_whom="Mr. Tan")
    add_follow_up(app, job_id, today(), "Send portfolio")
    page = me.get("/dashboard/").get_data(as_text=True)
    for words in ("Needs Attention", "Send portfolio", "Upcoming Interviews", "Mr. Tan", "Recent Activity",
                  "Added as Applied"):
        assert words in page


def test_the_schedule_groups_by_day(app, me, user_id):
    assert b"Nothing Scheduled" in me.get("/schedule/").data
    job_id = add_job(app, user_id, "Acme")
    add_follow_up(app, job_id, today() - 3 * DAY, "Late one")
    add_follow_up(app, job_id, today() + 2 * DAY, "Soon one")
    add_interview(app, job_id, utcnow() + 2 * DAY)
    page = me.get("/schedule/").get_data(as_text=True)
    assert page.index("Overdue") < page.index("Late one") < page.index("Soon one")
    assert "In 2 days" in page and "Video call" in page


# ---------- Filters that use interviews and follow-ups ----------

def test_filter_by_interview_and_follow_up(app, me, user_id):
    from .test_filters import titles
    soon = add_job(app, user_id, "A", "Soon Interview")
    later = add_job(app, user_id, "B", "Later Interview")
    due = add_job(app, user_id, "C", "Due Follow-up")
    add_job(app, user_id, "D", "Nothing")
    add_interview(app, soon, utcnow() + 2 * DAY)
    add_interview(app, later, utcnow() + 20 * DAY)
    add_interview(app, later, utcnow() - 20 * DAY)
    add_follow_up(app, due, today())
    add_follow_up(app, soon, today() + DAY)
    assert set(titles(me, "?interview=week")) == {"Soon Interview"}
    assert set(titles(me, "?interview=upcoming")) == {"Soon Interview", "Later Interview"}
    assert set(titles(me, "?followup=due")) == {"Due Follow-up"}


# ---------- The calendar feed ----------

def test_the_calendar_feed(app, me, client, user_id):
    post(me, "/settings/", {"action": "calendar_on"})
    token = get_user(app, "ana").calendar_token
    assert token and token.encode() in me.get("/settings/").data
    job_id = add_job(app, user_id, "Acme", "Data Analyst")
    add_interview(app, job_id, datetime(2030, 1, 15, 2, 0), minutes=45, place="https://meet.example.com/x")
    add_interview(app, job_id, datetime(2030, 1, 16, 2, 0), outcome="cancelled")
    add_follow_up(app, job_id, date(2030, 1, 20), "Email Ms. Reyes")
    add_follow_up(app, job_id, date(2030, 1, 21), "Done already", done_at=utcnow())

    with client.session_transaction() as session:
        session.clear()  # calendar apps never log in
    response = client.get(f"/calendar/{token}.ics")
    assert response.status_code == 200 and response.mimetype == "text/calendar"
    calendar = Calendar.from_ical(response.data)
    events = {str(event["summary"]): event for event in calendar.walk("VEVENT")}
    assert set(events) == {"Interview: Data Analyst at Acme", "Follow up: Acme (Data Analyst)"}
    interview = events["Interview: Data Analyst at Acme"]
    assert interview.decoded("dtstart") == datetime(2030, 1, 15, 2, 0, tzinfo=interview.decoded("dtstart").tzinfo)
    assert (interview.decoded("dtend") - interview.decoded("dtstart")) == timedelta(minutes=45)
    assert interview.walk("VALARM")  # a reminder an hour before
    assert events["Follow up: Acme (Data Analyst)"].decoded("dtstart") == date(2030, 1, 20)


def test_a_new_link_stops_the_old_one(app, me, client):
    post(me, "/settings/", {"action": "calendar_on"})
    old = get_user(app, "ana").calendar_token
    post(me, "/settings/", {"action": "calendar_on"})
    new = get_user(app, "ana").calendar_token
    assert old != new
    assert client.get(f"/calendar/{old}.ics").status_code == 404
    assert client.get(f"/calendar/{new}.ics").status_code == 200
    post(me, "/settings/", {"action": "calendar_off"})
    assert client.get(f"/calendar/{new}.ics").status_code == 404
    assert client.get("/calendar/x.ics").status_code == 404


# ---------- Privacy ----------

def test_someone_elses_interviews_and_follow_ups(app, client, user_id, other_id):
    job_id = add_job(app, other_id, "Secret Corp")
    interview_id = add_interview(app, job_id, utcnow() + DAY)
    follow_up_id = add_follow_up(app, job_id, today(), "secret note")
    log_in_as(client, user_id)
    for url in (f"/applications/{job_id}/interviews/new", f"/interviews/{interview_id}/edit",
                f"/follow-ups/{follow_up_id}/edit"):
        assert client.get(url).status_code == 404, url
    for url in (f"/applications/{job_id}/interviews/new", f"/interviews/{interview_id}/edit",
                f"/interviews/{interview_id}/outcome", f"/interviews/{interview_id}/delete",
                f"/applications/{job_id}/follow-ups", f"/follow-ups/{follow_up_id}/done",
                f"/follow-ups/{follow_up_id}/not-done", f"/follow-ups/{follow_up_id}/snooze",
                f"/follow-ups/{follow_up_id}/edit", f"/follow-ups/{follow_up_id}/delete",
                f"/applications/{job_id}/no-reply", f"/applications/{job_id}/keep-waiting"):
        assert post(client, url, {"days": "1", "outcome": "passed"}).status_code == 404, url
    for url in ("/dashboard/", "/schedule/"):
        assert b"Secret Corp" not in client.get(url).data
    assert len(interviews(app)) == 1 and len(follow_ups(app)) == 1


@pytest.mark.parametrize("url", ["/schedule/", "/dashboard/"])
def test_pages_need_a_login(client, url):
    assert "/login" in client.get(url).location
