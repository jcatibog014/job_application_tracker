"""The demo: a fresh sample account per visitor, with an example on every page it can open."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from hirewire import auth, db
from hirewire.dates import utcnow
from hirewire.models import (
    ACTIVE_STAGES, CLOSED_STAGES, Application, Company, Contact, Document, EmailSuggestion, FollowUp, Interview,
    SavedView, User,
)

from .conftest import post


@pytest.fixture
def demo(app):
    """A browser that pressed Try Demo."""
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "x"
    response = post(client, "/demo")
    assert response.status_code == 302 and response.location.endswith("/dashboard/")
    return client


def demo_user(app):
    with app.app_context():
        return db.session().scalar(select(User).where(User.is_demo.is_(True)).order_by(User.id.desc()))


def count(app, model, *where):
    with app.app_context():
        return db.session().scalar(select(func.count()).select_from(model).where(*where))


# ---------- Starting it ----------

def test_try_demo_makes_a_sample_account(app, demo):
    user = demo_user(app)
    assert user.is_demo and user.username.startswith("demo-")
    assert user.demo_expires_at > utcnow() + timedelta(hours=1, minutes=55)
    stages = {stage for (stage,) in db_rows(app, select(Application.stage).where(Application.user_id == user.id))}
    assert stages == set(ACTIVE_STAGES) | set(CLOSED_STAGES)  # every stage has an example
    page = demo.get("/dashboard/").data
    assert b"Demo account." in page and b"Welcome to the demo" in page
    # A thin note that JavaScript lets you close (the button is hidden without it).
    assert b'data-demo-close aria-label="Hide this note" hidden' in page


def db_rows(app, query):
    with app.app_context():
        return db.session().execute(query).all()


def test_each_visitor_gets_their_own_demo(app, demo):
    other = app.test_client()
    with other.session_transaction() as session:
        session["csrf"] = "x"
    post(other, "/demo")
    assert count(app, User, User.is_demo.is_(True)) == 2
    # Pressing it again in the same browser keeps the same account.
    post(demo, "/demo")
    assert count(app, User, User.is_demo.is_(True)) == 2


def test_old_demos_are_deleted_with_everything_in_them(app, demo):
    with app.app_context():
        s = db.session()
        s.get(User, demo_user(app).id).demo_expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    other = app.test_client()
    with other.session_transaction() as session:
        session["csrf"] = "x"
    post(other, "/demo")
    assert count(app, User, User.is_demo.is_(True)) == 1
    new_id = demo_user(app).id
    for model in (Application, Company, Contact, Document, SavedView, EmailSuggestion):
        assert count(app, model, model.user_id != new_id) == 0, model.__name__
    assert count(app, Interview) > 0 and count(app, FollowUp) > 0  # only the new demo's


def test_the_demo_has_a_busy_limit(app, demo, monkeypatch):
    monkeypatch.setattr(auth, "MAX_DEMOS", 1)
    other = app.test_client()
    with other.session_transaction() as session:
        session["csrf"] = "x"
    response = post(other, "/demo", follow_redirects=True)
    assert b"very busy" in response.data


# ---------- What the demo can't do ----------

def test_the_demo_cant_change_settings_or_upload(app, demo):
    for action in ("password", "timezone", "delete", "gmail_connect", "calendar_off", "recovery"):
        assert post(demo, "/settings/", {"action": action}).status_code == 403, action
    assert post(demo, "/documents/new", {"name": "x"}).status_code == 403
    page = demo.get("/settings/").get_data(as_text=True)
    assert "disabled" in page and "/calendar/" in page  # shown as examples


def test_the_demo_can_try_everything_else(app, demo):
    job_id = db_rows(app, select(Application.id).where(Application.stage == "applied"))[0][0]
    assert post(demo, f"/applications/{job_id}/move", {"to": "screening"}).status_code == 302
    assert post(demo, f"/applications/{job_id}/notes", {"body": "Trying the demo"}).status_code == 302


def test_check_email_in_the_demo_uses_sample_emails(app, demo):
    before = count(app, EmailSuggestion)
    response = post(demo, "/email-suggestions/check", follow_redirects=True)
    assert b"No new job emails" in response.data  # the samples are already there
    assert count(app, EmailSuggestion) == before


def test_the_sample_emails_go_through_the_real_rules(app, demo):
    rows = db_rows(app, select(EmailSuggestion.kind, EmailSuggestion.company_guess, EmailSuggestion.application_id)
                   .where(EmailSuggestion.status == "pending").order_by(EmailSuggestion.received_at.desc()))
    kinds = [(kind, company, bool(job)) for kind, company, job in rows]
    assert kinds == [("interview", "Tala Health", True), ("applied", "Ulap Cloud", True),
                     ("rejection", "Lakbay Travel", True), ("applied", "Sari Analytics", False)]


def test_the_sample_files_are_real_pdfs(app, demo):
    doc_id = db_rows(app, select(Document.id))[0][0]
    response = demo.get(f"/documents/{doc_id}/file")
    assert response.data.startswith(b"%PDF-1.4") and response.data.rstrip().endswith(b"%%EOF")


# ---------- Every page has an example ----------

EMPTY_SIGNS = [
    "empty-state", "You're all caught up", "No interviews in the next two weeks", "No follow-ups in the next 7 days",
    "Nothing yet", "No Stats Yet",
]


def assert_not_empty(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    page = response.get_data(as_text=True)
    for sign in EMPTY_SIGNS:
        assert sign.replace("'", "&#39;") not in page, f"{url}: {sign}"
    return page


@pytest.mark.parametrize("url", [
    "/dashboard/", "/applications/", "/applications/?closed=1", "/board/", "/schedule/", "/companies/",
    "/contacts/", "/documents/", "/stats/", "/email-suggestions/", "/email-suggestions/?show=done", "/settings/",
])
def test_no_page_the_demo_can_open_is_empty(demo, url):
    assert_not_empty(demo, url)


def test_the_dashboard_has_every_kind_of_reminder(demo):
    page = assert_not_empty(demo, "/dashboard/")
    for words in ("Overdue", "Send the case study", "No news for", "Upcoming Interviews", "Coming This Week",
                  "Recent Activity"):
        assert words in page, words


def test_each_stat_card_opens_its_applications(demo):
    page = demo.get("/dashboard/").get_data(as_text=True)
    links = re.findall(r'<a class="stat" href="([^"]+)"', page)
    assert links[3] == "/applications/?stage=interview"
    assert "Interview: 2. Show them on the Applications page" in page
    # The card's number is what the filtered list shows.
    interviews = demo.get("/applications/?stage=interview").get_data(as_text=True)
    assert "2 applications" in interviews
    closed = demo.get(links[-1].replace("&amp;", "&")).get_data(as_text=True)
    assert "6 applications" in closed


def test_join_links_open_in_a_new_tab(demo):
    page = demo.get("/dashboard/").get_data(as_text=True)
    join = re.search(r'<a href="https://meet[^"]+"[^>]*>Join link.*?</a>', page, re.DOTALL).group(0)
    assert 'target="_blank"' in join and "noopener" in join and "(opens in a new tab)" in join


def test_every_saved_view_finds_something(app, demo):
    page = demo.get("/applications/").get_data(as_text=True)
    links = re.findall(r'href="(/applications/\?[^"]+)"', page)
    assert len(links) >= 4
    for link in links:
        assert "No Matching Applications" not in demo.get(link.replace("&amp;", "&")).get_data(as_text=True), link


def test_every_application_and_company_page_has_content(app, demo):
    for (job_id,) in db_rows(app, select(Application.id)):
        page = demo.get(f"/applications/{job_id}").get_data(as_text=True)
        assert "Added as" in page  # every timeline starts somewhere
    for (company_id,) in db_rows(app, select(Company.id)):
        page = demo.get(f"/companies/{company_id}").get_data(as_text=True)
        assert "No applications to" not in page


def test_the_demo_calendar_feed_works(app, demo):
    token = demo_user(app).calendar_token
    body = app.test_client().get(f"/calendar/{token}.ics").get_data(as_text=True)
    assert body.count("BEGIN:VEVENT") >= 4
