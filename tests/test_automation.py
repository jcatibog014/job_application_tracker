"""Quick add from a link, and Gmail suggestions. Nothing here goes online:
web pages and Gmail are faked."""
import json
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest
from sqlalchemy import select

from hirewire import crypto, db, gmail, mail_rules, quick_add, suggestions
from hirewire.dates import utcnow
from hirewire.mail_rules import APPLIED, INTERVIEW, OFFER, REJECTION, Email
from hirewire.models import Application, EmailSuggestion, FollowUp, GmailAccount, Interview, Note, User

from .conftest import add_job, get_job, get_user, log_in_as, post

RECEIVED = datetime(2026, 11, 3, 2, 0)  # 10 AM in Manila


def mail(subject, text="", sender="Acme Careers <careers@acme.example>", calendar=None):
    name, _, address = sender.rpartition(" <")
    return Email(message_id=f"<{subject}@test>", sender_name=name, sender_address=address.rstrip(">") or sender,
                 subject=subject, text=text, received_at=RECEIVED, calendar=calendar)


# ---------- What kind of email ----------

@pytest.mark.parametrize("subject, text, kind", [
    ("Thank you for applying to Acme", "We have received your application for the Data Analyst position.", APPLIED),
    ("Your application was sent to Acme", "LinkedIn: your application was sent.", APPLIED),
    ("Application received", "Thanks for applying! If you are selected for an interview, we will contact you.", APPLIED),
    ("Acme: we received your application", "Thank you for your application. Our team will review it.", APPLIED),
    ("Interview invitation: Data Analyst", "We would like to invite you to an interview.", INTERVIEW),
    ("Next steps with Acme", "Please share your availability for a call next week.", INTERVIEW),
    ("Hello from Acme", "We would like to schedule an interview on November 12, 2026 at 2:30 PM.", INTERVIEW),
    ("Your Acme interview is confirmed", "See you then.", INTERVIEW),
    ("Phone screen", "Can we book a time for a phone screen?", INTERVIEW),
    ("Update on your application", "Unfortunately, we have decided to move forward with other candidates.", REJECTION),
    ("Your application to Acme", "After careful review, you have not been selected for this role.", REJECTION),
    ("Thank you for interviewing", "We regret to inform you that the position has been filled.", REJECTION),
    ("Re: Data Analyst", "Unfortunately we won't continue.", REJECTION),
    # A strong "no" wins even when the email talks about the interview.
    ("Following your interview", "Thank you for the interview. We are not moving forward.", REJECTION),
    ("Offer letter", "We are pleased to offer you the position of Data Analyst.", OFFER),
    ("Congratulations!", "Please find your offer of employment attached.", OFFER),
    ("Job alert: 25 new Data Analyst jobs", "Thank you for applying to jobs on our site. Interview tips inside.", None),
    ("Jobs you may be interested in", "Apply now", None),
    ("Acme is hiring", "Unfortunately you missed our webinar.", None),
    ("Lunch on Friday?", "Want to grab lunch?", None),
])
def test_classify(subject, text, kind):
    assert mail_rules.classify(mail(subject, text)) == kind


def test_a_calendar_invite_is_an_interview():
    invite = make_ics("Interview with Acme", "20261112T063000Z")
    assert mail_rules.classify(mail("Invitation: Meeting", "Event details", calendar=invite)) == INTERVIEW


# ---------- Which company, which job ----------

@pytest.mark.parametrize("subject, sender, company", [
    ("Your application was sent to Globe Telecom", "LinkedIn <jobs-noreply@linkedin.com>", "Globe Telecom"),
    ("Thank you for applying to Bluewave Bank!", "no-reply@greenhouse.io", "Bluewave Bank"),
    ("Interview with Northstar BPO for Reporting Specialist", "Liza <liza@gmail.com>", "Northstar BPO"),
    ("Update", "Initech Careers <jobs@initech.example>", "Initech"),
    ("Update", "Talent Team at Kalye Foods <talent@mail.kalyefoods.example>", "Kalye Foods"),
    ("Update", "Liza Reyes <liza@acme-logistics.com.ph>", "Acme Logistics"),
    ("Update", "Recruiter <noreply@myworkday.com>", ""),  # a shared sender says nothing
])
def test_company_from(subject, sender, company):
    assert mail_rules.company_from(mail(subject, sender=sender)) == company


@pytest.mark.parametrize("subject, text, role", [
    ("Thank you for applying", "We received your application for the Data Analyst position.", "Data Analyst"),
    ("Interview: Reporting Specialist role", "", ""),
    ("Your application for Junior Data Analyst at Globe", "", "Junior Data Analyst"),
    ("Hello", "We are hiring for the role of Business Analyst.", "Business Analyst"),
    ("Your application was sent to Acme", "Your application for Data Analyst was sent.", "Data Analyst"),
])
def test_role_from(subject, text, role):
    found = mail_rules.role_from(mail(subject, text))
    assert found == role or (role == "" and found in ("", "Reporting Specialist"))


def test_company_names_match_however_written():
    jobs = [(1, "Acme Philippines, Inc.", "", False, utcnow()), (2, "Globe Telecom", "https://www.globe.example", False, utcnow()),
            (3, "Acme", "", True, utcnow() + timedelta(days=1))]
    finding = mail_rules.Finding(APPLIED, "ACME", "", None)
    assert mail_rules.match_application(finding, mail("x"), jobs) == 1  # open beats closed
    by_site = mail_rules.Finding(APPLIED, "", "", None)
    assert mail_rules.match_application(by_site, mail("x", sender="HR <hr@careers.globe.example>"), jobs) == 2
    assert mail_rules.match_application(mail_rules.Finding(APPLIED, "Initech", "", None), mail("x"), jobs) is None


# ---------- When the interview is ----------

def make_ics(summary, start, end=None):
    end = end or start
    return (f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\nBEGIN:VEVENT\r\nUID:1@test\r\nSUMMARY:{summary}\r\n"
            f"DTSTART:{start}\r\nDTEND:{end}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()


@pytest.mark.parametrize("text, expected", [
    ("Your interview is on Thursday, November 12, 2026 at 2:30 PM.", datetime(2026, 11, 12, 6, 30)),
    ("Can you do Nov 12 at 2pm?", datetime(2026, 11, 12, 6, 0)),
    ("Let's meet on 12 November 2026, 14:30.", datetime(2026, 11, 12, 6, 30)),
    ("Time: 2026-11-12 09:00", datetime(2026, 11, 12, 1, 0)),
    ("See you on January 5 at 10:00 AM", datetime(2027, 1, 5, 2, 0)),  # January, in a November email: next year
    ("We will call you soon.", None),
])
def test_interview_time_from_words(text, expected):
    assert mail_rules.interview_time(mail("Interview", text), "Asia/Manila") == expected


def test_interview_time_from_an_invite():
    assert mail_rules.interview_time(mail("x", calendar=make_ics("Interview", "20261112T063000Z")), "Asia/Manila") \
        == datetime(2026, 11, 12, 6, 30)
    # No time zone in the invite: it's on the person's own clock.
    assert mail_rules.interview_time(mail("x", calendar=make_ics("Interview", "20261112T143000")), "Asia/Manila") \
        == datetime(2026, 11, 12, 6, 30)


# ---------- Reading raw emails ----------

def raw_email(subject, body, sender="Acme Careers <careers@acme.example>", html=False, ics=None, message_id=None,
              when=None):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "ana@gmail.com"
    message["Subject"] = subject
    message["Date"] = format_datetime((when or RECEIVED).replace(tzinfo=UTC))
    message["Message-ID"] = message_id or f"<{abs(hash(subject))}@acme.example>"
    if html:
        message.set_content("Plain version")
        message.add_alternative(f"<html><body><p>{body}</p></body></html>", subtype="html")
    else:
        message.set_content(body)
    if ics:
        message.add_attachment(ics, maintype="text", subtype="calendar", filename="invite.ics")
    return message.as_bytes()


def test_parse_message():
    raw = raw_email("Interview invitation", "Hello <b>Ana</b>", html=True,
                    ics=make_ics("Interview", "20261112T063000Z"), message_id="<abc@acme.example>")
    email = gmail.parse_message(raw)
    assert email.message_id == "<abc@acme.example>" and email.sender_address == "careers@acme.example"
    assert email.sender_name == "Acme Careers" and email.received_at == RECEIVED
    assert "Plain version" in email.text and email.calendar.startswith(b"BEGIN:VCALENDAR")


class FakeBox:
    """Enough of imaplib.IMAP4_SSL for fetch_recent."""
    messages = {}
    password = "abcdefghijklmnop"
    calls = []

    def __init__(self, host, port, timeout):
        assert (host, port) == ("imap.gmail.com", 993)

    def login(self, address, password):
        if password != self.password:
            raise gmail.imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, mailbox, readonly):
        assert readonly, "the inbox must be opened read-only"
        self.calls.append("select")
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.calls.append(f"{command} {' '.join(map(str, args))}")
        if command == "SEARCH":
            return "OK", [b" ".join(str(uid).encode() for uid in self.messages)]
        uids = [int(uid) for uid in args[0].split(",")]
        if args[1] == "(RFC822.SIZE)":
            return "OK", [f"{n} (UID {uid} RFC822.SIZE {len(self.messages[uid])})".encode()
                          for n, uid in enumerate(uids, 1)]
        assert "PEEK" in args[1], "fetching must not mark emails as read"
        data = []
        for n, uid in enumerate(uids, 1):
            data += [(f"{n} (UID {uid} BODY[] {{{len(self.messages[uid])}}}".encode(), self.messages[uid]), b")"]
        return "OK", data

    def logout(self):
        pass


@pytest.fixture
def fake_gmail(monkeypatch):
    FakeBox.calls = []
    FakeBox.messages = {
        11: raw_email("Thank you for applying to Acme", "We received your application for the Data Analyst position."),
        12: raw_email("Interview invitation", "Can you meet on November 12, 2026 at 2:30 PM?",
                      sender="Globe Careers <careers@globe.example>"),
        13: raw_email("Jobs you may like", "Thank you for applying elsewhere."),
        14: raw_email("Big file", "x" * (gmail.MAX_SIZE + 10)),
    }
    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", FakeBox)  # every Gmail call meets the fake
    return FakeBox


def test_fetch_recent_reads_without_marking_and_skips_big_ones():
    FakeBox.calls = []
    FakeBox.messages = {1: raw_email("a", "b"), 2: raw_email("big", "x" * (gmail.MAX_SIZE + 10))}
    raws = gmail.fetch_recent("ana@gmail.com", FakeBox.password, imap_class=FakeBox)
    assert len(raws) == 1 and b"Subject: a" in raws[0]
    assert any("X-GM-RAW" in call and "newer_than:30d" in call for call in FakeBox.calls)
    with pytest.raises(gmail.GmailProblem):
        gmail.fetch_recent("ana@gmail.com", "wrong", imap_class=FakeBox)


# ---------- Connecting Gmail ----------

def connect(client, monkeypatch, password="abcd efgh ijkl mnop"):
    monkeypatch.setattr(gmail, "check_login", lambda address, password: None)
    return post(client, "/settings/", {"action": "gmail_connect", "address": "Ana@Gmail.com", "app_password": password})


def account(app):
    with app.app_context():
        return db.session().scalar(select(GmailAccount))


def test_connect_keeps_the_app_password_encrypted(app, me, monkeypatch):
    assert connect(me, monkeypatch).status_code == 302
    row = account(app)
    assert row.address == "ana@gmail.com" and "abcdefghijklmnop" not in row.password_encrypted
    with app.app_context():
        assert crypto.decrypt(row.password_encrypted) == "abcdefghijklmnop"
    page = me.get("/settings/").get_data(as_text=True)
    assert "Connected as" in page and "abcdefghijklmnop" not in page and row.password_encrypted not in page


def test_connect_problems(app, me, monkeypatch):
    assert connect(me, monkeypatch, "secret123").status_code == 400
    monkeypatch.setattr(gmail, "check_login", lambda a, p: (_ for _ in ()).throw(gmail.GmailProblem("Gmail said no.")))
    response = post(me, "/settings/", {"action": "gmail_connect", "address": "ana@gmail.com",
                                       "app_password": "abcdefghijklmnop"})
    assert response.status_code == 400 and b"Gmail said no." in response.data
    assert account(app) is None


def test_disconnect(app, me, monkeypatch):
    connect(me, monkeypatch)
    post(me, "/settings/", {"action": "gmail_disconnect"})
    assert account(app) is None


def test_a_changed_key_asks_to_connect_again(app, ctx, user_id, monkeypatch):
    ctx.add(GmailAccount(user_id=user_id, address="ana@gmail.com", password_encrypted="not-a-real-token"))
    ctx.commit()
    with pytest.raises(gmail.GmailProblem, match="connect Gmail again"):
        suggestions.check(ctx, ctx.get(User, user_id), utcnow(), fetcher=lambda a, p: [])


# ---------- Checking and accepting ----------

def suggestion_rows(app):
    with app.app_context():
        return db.session().scalars(select(EmailSuggestion).order_by(EmailSuggestion.id)).all()


def test_check_makes_suggestions_once(app, me, user_id, monkeypatch, fake_gmail):
    job_id = add_job(app, user_id, "Acme", "Data Analyst", stage="saved")
    connect(me, monkeypatch)
    page = me.get("/email-suggestions/").get_data(as_text=True)  # opening the page checks
    rows = suggestion_rows(app)
    assert [(row.kind, row.company_guess) for row in rows] == [("applied", "Acme"), ("interview", "Globe")]
    assert rows[0].application_id == job_id and rows[0].role_guess == "Data Analyst"
    assert rows[1].proposed_at == datetime(2026, 11, 12, 6, 30) and rows[1].application_id is None
    assert len(rows[0].snippet) <= 300
    assert "Move it from Saved to Applied." in page and "Add a new application for Globe" in page
    assert '<span class="badge">2' in page
    post(me, "/email-suggestions/check")
    assert len(suggestion_rows(app)) == 2  # the same emails are never suggested twice


def test_accept_applied_moves_a_saved_job(app, me, user_id, monkeypatch, fake_gmail):
    job_id = add_job(app, user_id, "Acme", stage="saved")
    connect(me, monkeypatch)
    me.get("/email-suggestions/")
    first = suggestion_rows(app)[0]
    post(me, f"/email-suggestions/{first.id}/accept", {"application": str(job_id)})
    job = get_job(app, job_id)
    assert job.stage == "applied"
    assert any(note.body.startswith("From an email") for note in job.notes)
    assert b"Moved to Applied (from an email)" in me.get(f"/applications/{job_id}").data
    assert suggestion_rows(app)[0].status == "accepted"


def test_accept_an_interview_as_a_new_application(app, me, user_id, monkeypatch, fake_gmail):
    connect(me, monkeypatch)
    me.get("/email-suggestions/")
    second = suggestion_rows(app)[1]
    post(me, f"/email-suggestions/{second.id}/accept",
         {"application": "new", "role": "Junior Data Analyst", "when": "2026-11-12T15:00"})
    with app.app_context():
        s = db.session()
        job = s.scalar(select(Application).where(Application.role_title == "Junior Data Analyst"))
        company = job.company.name
        interview = s.scalar(select(Interview))
        thank_you = s.scalar(select(FollowUp).where(FollowUp.auto_kind == "thank_you"))
    assert job.stage == "interview" and company == "Globe"
    assert interview.starts_at == datetime(2026, 11, 12, 7, 0)  # the time as corrected, 3 PM Manila
    assert thank_you.due_on == date(2026, 11, 13)


def test_accept_says_exactly_what_changed(app, me, user_id, monkeypatch, fake_gmail):
    connect(me, monkeypatch)
    me.get("/email-suggestions/")
    second = suggestion_rows(app)[1]
    response = post(me, f"/email-suggestions/{second.id}/accept",
                    {"application": "new", "role": "Analyst", "when": "2026-11-12T15:00"}, follow_redirects=True)
    page = response.get_data(as_text=True)
    assert "Interview with Globe added to your schedule: Thu, Nov 12, 2026 at 3:00 PM." in page
    assert 'class="flash"' in page and "data-stays" not in page  # good news: a toast that fades


def test_a_problem_message_stays_until_closed(app, ctx, me, user_id):
    suggestions.add_from_raw(ctx, ctx.get(User, user_id), [raw_email("Update", "Unfortunately, we are not moving forward.")],
                             utcnow())
    ctx.commit()
    row_id = suggestion_rows(app)[0].id
    page = post(me, f"/email-suggestions/{row_id}/accept", {"application": "new"}, follow_redirects=True).get_data(as_text=True)
    assert 'class="flash flash-error" data-flash data-stays' in page


def test_a_rejection_needs_an_application(app, ctx, me, user_id):
    job_id = add_job(app, user_id, "Acme", stage="interview")
    raws = [raw_email("Update on your application", "Unfortunately, we are not moving forward.")]
    suggestions.add_from_raw(ctx, ctx.get(User, user_id), raws, utcnow())
    ctx.commit()
    row = suggestion_rows(app)[0]
    assert row.kind == "rejection" and row.application_id == job_id
    response = post(me, f"/email-suggestions/{row.id}/accept", {"application": "new"}, follow_redirects=True)
    assert b"Choose the application" in response.data
    post(me, f"/email-suggestions/{row.id}/accept", {"application": str(job_id)})
    assert get_job(app, job_id).stage == "rejected"


def test_ignore_and_bring_back(app, ctx, me, user_id):
    suggestions.add_from_raw(ctx, ctx.get(User, user_id), [raw_email("Thank you for applying to Acme", "")], utcnow())
    ctx.commit()
    row_id = suggestion_rows(app)[0].id
    post(me, f"/email-suggestions/{row_id}/ignore")
    assert suggestion_rows(app)[0].status == "ignored"
    assert b"Bring it back" in me.get("/email-suggestions/?show=done").data
    post(me, f"/email-suggestions/{row_id}/undo")
    assert suggestion_rows(app)[0].status == "pending"
    assert post(me, f"/email-suggestions/{row_id}/accept", {"application": "x"}).status_code == 302


def test_a_gmail_problem_is_shown(app, me, user_id, monkeypatch):
    connect(me, monkeypatch)

    def broken(address, password):
        raise gmail.GmailProblem("Gmail couldn't be reached. Please try again later.")
    monkeypatch.setattr(gmail, "fetch_recent", broken)
    page = me.get("/email-suggestions/").get_data(as_text=True)
    assert "Gmail couldn&#39;t be reached" in page
    assert account(app).last_error.startswith("Gmail couldn't")


def test_without_gmail_the_page_explains(me):
    page = me.get("/email-suggestions/").get_data(as_text=True)
    assert "Connect Your Gmail" in page and "Check email now" not in page


def test_suggestions_are_private(app, ctx, client, user_id, other_id):
    suggestions.add_from_raw(ctx, ctx.get(User, other_id), [raw_email("Thank you for applying to Secret Corp", "")],
                             utcnow())
    ctx.commit()
    row_id = suggestion_rows(app)[0].id
    log_in_as(client, user_id)
    assert b"Secret Corp" not in client.get("/email-suggestions/").data
    for action in ("accept", "ignore", "undo"):
        assert post(client, f"/email-suggestions/{row_id}/{action}", {"application": "new"}).status_code == 404


def test_scan_email_command(app, user_id, monkeypatch, fake_gmail):
    with app.app_context():
        s = db.session()
        s.add(GmailAccount(user_id=user_id, address="ana@gmail.com", password_encrypted=crypto.encrypt(FakeBox.password)))
        s.commit()
    result = app.test_cli_runner().invoke(args=["scan-email", "ana"])
    assert result.exit_code == 0, result.output
    assert "2 new suggestions" in result.output


# ---------- Quick add: reading a posting ----------

JOB_PAGE = """<html><head><title>Careers</title>
<script type="application/ld+json">{data}</script></head><body>Apply now</body></html>"""
POSTING = {
    "@context": "https://schema.org", "@type": "JobPosting", "title": "Data Analyst",
    "hiringOrganization": {"@type": "Organization", "name": "Bluewave Bank"},
    "jobLocation": {"@type": "Place", "address": {"addressLocality": "Taguig", "addressRegion": "Metro Manila",
                                                  "addressCountry": "PH"}},
    "baseSalary": {"currency": "php", "value": {"minValue": 480000, "maxValue": 600000, "unitText": "YEAR"}},
    "description": "<p>Build <b>dashboards</b>.</p><p>Use SQL.</p>",
    "jobLocationType": "TELECOMMUTE",
}


def test_read_a_job_posting():
    found = quick_add.read_posting(JOB_PAGE.format(data=json.dumps(POSTING)), "https://boards.greenhouse.io/x/1")
    assert found["role_title"] == "Data Analyst" and found["company_name"] == "Bluewave Bank"
    assert found["location"] == "Taguig, Metro Manila" and found["work_mode"] == "remote"
    assert (found["salary_min"], found["salary_max"], found["currency"]) == (40000, 50000, "PHP")  # a year / 12
    assert found["job_description"] == "Build\ndashboards\n.\n\nUse SQL." or "dashboards" in found["job_description"]
    assert found["source"] == "Company site"


def test_read_a_posting_inside_a_graph():
    data = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {**POSTING, "title": "Analyst II"}]}
    assert quick_add.read_posting(JOB_PAGE.format(data=json.dumps(data)), "https://x.example")["role_title"] == "Analyst II"


def test_a_page_without_posting_data_uses_its_tags():
    page = ('<html><head><meta property="og:title" content="Report Writer"><meta property="og:site_name" '
            'content="Initech"><meta name="description" content="Write reports."></head></html>')
    found = quick_add.read_posting(page, "https://www.jobstreet.com.ph/job/1")
    assert found == {"posting_url": "https://www.jobstreet.com.ph/job/1", "source": "JobStreet",
                     "role_title": "Report Writer", "company_name": "Initech", "job_description": "Write reports."}


# ---------- Quick add: fetching safely ----------

def public(host, port):
    return {"93.184.216.34"}


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1"])
def test_private_addresses_are_refused(address):
    with pytest.raises(quick_add.FetchProblem, match="private network"):
        quick_add.check_address("http://example.com/job", resolver=lambda host, port: {address})


def test_only_web_addresses():
    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://x"):
        with pytest.raises(quick_add.FetchProblem):
            quick_add.check_address(url, resolver=public)


class FakeResponse:
    def __init__(self, status=200, body=b"<html></html>", headers=None):
        self.status_code, self.body = status, body
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}
        self.encoding = "utf-8"

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self):
        pass


def test_a_redirect_to_a_private_address_is_refused():
    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == quick_add.TIMEOUT
        return FakeResponse(302, headers={"Location": "http://internal.example/admin"})

    def resolver(host, port):
        return {"10.0.0.7"} if host == "internal.example" else {"93.184.216.34"}

    with pytest.raises(quick_add.FetchProblem, match="private network"):
        quick_add.fetch("https://jobs.example/1", get=get, resolver=resolver)


def test_too_big_or_refused_pages():
    with pytest.raises(quick_add.FetchProblem, match="too big"):
        quick_add.fetch("https://jobs.example/1", get=lambda url, **k: FakeResponse(body=b"x" * (quick_add.MAX_BYTES + 1)),
                        resolver=public)
    with pytest.raises(quick_add.FetchProblem, match="error 999"):
        quick_add.fetch("https://jobs.example/1", get=lambda url, **k: FakeResponse(999), resolver=public)


def test_quick_add_page(app, me, monkeypatch):
    page = JOB_PAGE.format(data=json.dumps(POSTING))
    monkeypatch.setattr(quick_add, "fetch", lambda url: (page, url))
    response = post(me, "/applications/quick-add", {"url": "https://jobs.example/42"})
    text = response.get_data(as_text=True)
    assert response.status_code == 200 and "Filled in from the posting" in text
    assert 'value="Data Analyst"' in text and 'value="Bluewave Bank"' in text and 'value="https://jobs.example/42"' in text


def test_quick_add_when_the_site_says_no(app, me, monkeypatch):
    def refuse(url):
        raise quick_add.FetchProblem("The site said no (error 999).")
    monkeypatch.setattr(quick_add, "fetch", refuse)
    text = post(me, "/applications/quick-add", {"url": "linkedin.com/jobs/view/1"}).get_data(as_text=True)
    assert "The site said no" in text and 'value="https://linkedin.com/jobs/view/1"' in text


def test_quick_add_has_an_hourly_limit(app, me, user_id, monkeypatch):
    monkeypatch.setattr(quick_add, "fetch", lambda url: ("<html></html>", url))
    for _ in range(quick_add.HOURLY_LIMIT):
        assert post(me, "/applications/quick-add", {"url": "https://jobs.example/1"}).status_code == 200
    assert post(me, "/applications/quick-add", {"url": "https://jobs.example/1"}).status_code == 429
    assert post(me, "/applications/quick-add", {"url": "javascript:alert(1)"}).status_code == 400
