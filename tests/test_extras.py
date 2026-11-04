"""Contacts, documents and stats."""
import io
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from hirewire import db, stats, workflow
from hirewire.dates import local_today, utcnow
from hirewire.models import Application, ApplicationContact, Contact, Document, User

from .conftest import add_job, get_job, log_in_as, post

PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
DOCX = b"PK\x03\x04" + b"\x00" * 100


def contacts(app):
    with app.app_context():
        return db.session().scalars(select(Contact).order_by(Contact.id)).all()


def links(app):
    with app.app_context():
        return [(row.application_id, row.contact_id, row.role) for row in db.session().scalars(select(ApplicationContact))]


def add_contact(app, user_id, name="Ms. Reyes", **fields):
    with app.app_context():
        s = db.session()
        row = Contact(user_id=user_id, name=name, **fields)
        s.add(row)
        s.commit()
        return row.id


CONTACT_FORM = {"name": "Liza Reyes", "job_title": "Recruiter", "email": "liza@acme.example", "phone": "+63 917 123 4567",
                "profile_url": "linkedin.com/in/liza", "notes": "Met at the job fair.", "last_contacted_on": "2026-10-30",
                "company_id": ""}


# ---------- Contacts ----------

def test_add_edit_and_find_a_contact(app, me, user_id):
    job_id = add_job(app, user_id, "Acme")
    company_id = get_job(app, job_id).company_id
    assert post(me, "/contacts/new", {**CONTACT_FORM, "company_id": str(company_id)}).status_code == 302
    [person] = contacts(app)
    assert person.company_id == company_id and person.profile_url == "https://linkedin.com/in/liza"
    page = me.get("/contacts/").get_data(as_text=True)
    assert "Liza Reyes" in page and "Recruiter at Acme" in page and "mailto:liza@acme.example" in page
    assert "Liza Reyes" in me.get(f"/companies/{company_id}").get_data(as_text=True)
    assert "Liza Reyes" in me.get("/contacts/?q=acme").get_data(as_text=True)
    assert "No Matching People" in me.get("/contacts/?q=zzz").get_data(as_text=True)
    post(me, f"/contacts/{person.id}/edit", {**CONTACT_FORM, "name": "Liza Reyes-Cruz"})
    assert contacts(app)[0].name == "Liza Reyes-Cruz"


@pytest.mark.parametrize("change, problem", [
    ({"name": ""}, b"A name is needed"),
    ({"email": "not an email"}, b"email address like"),
    ({"phone": "call me"}, b"digits"),
    ({"profile_url": "javascript:alert(1)"}, b"web address"),
])
def test_contact_form_problems(app, me, change, problem):
    response = post(me, "/contacts/new", {**CONTACT_FORM, **change})
    assert response.status_code == 400 and problem in response.data
    assert contacts(app) == []


def test_someone_elses_company_cant_be_chosen(app, me, other_id):
    job_id = add_job(app, other_id, "Their Corp")
    post(me, "/contacts/new", {**CONTACT_FORM, "company_id": str(get_job(app, job_id).company_id)})
    assert contacts(app)[0].company_id is None


def test_talked_today(app, me, user_id):
    contact_id = add_contact(app, user_id)
    post(me, f"/contacts/{contact_id}/contacted")
    assert contacts(app)[0].last_contacted_on == local_today("Asia/Manila")


def test_link_people_to_an_application(app, me, user_id):
    job_id = add_job(app, user_id)
    contact_id = add_contact(app, user_id, email="reyes@acme.example")
    post(me, f"/contacts/link/{job_id}", {"contact_id": str(contact_id), "role": "hiring_manager"})
    assert links(app) == [(job_id, contact_id, "hiring_manager")]
    page = me.get(f"/applications/{job_id}").get_data(as_text=True)
    assert "Ms. Reyes" in page and "Hiring manager" in page
    post(me, f"/contacts/link/{job_id}", {"contact_id": str(contact_id), "role": "interviewer"})
    assert links(app) == [(job_id, contact_id, "interviewer")]  # the same person once, with the new role
    post(me, f"/contacts/unlink/{job_id}/{contact_id}")
    assert links(app) == [] and len(contacts(app)) == 1


def test_add_a_new_person_from_an_application(app, me, user_id):
    job_id = add_job(app, user_id, "Acme")
    page = me.get(f"/contacts/new?job={job_id}").get_data(as_text=True)
    assert "They will be linked to Data Analyst" in page
    response = post(me, "/contacts/new", {**CONTACT_FORM, "job": str(job_id), "role": "referral"})
    assert response.location.endswith(f"/applications/{job_id}#people")
    assert links(app) == [(job_id, contacts(app)[0].id, "referral")]


def test_deleting_a_person_or_company(app, me, user_id):
    job_id = add_job(app, user_id, "Acme")
    company_id = get_job(app, job_id).company_id
    contact_id = add_contact(app, user_id, company_id=company_id)
    post(me, f"/contacts/link/{job_id}", {"contact_id": str(contact_id), "role": "recruiter"})
    post(me, f"/applications/{job_id}/delete")
    post(me, f"/companies/{company_id}/delete")
    assert contacts(app)[0].company_id is None  # the person stays, without the company
    post(me, f"/contacts/{contact_id}/delete")
    assert contacts(app) == []


# ---------- Documents ----------

def upload(client, data=PDF, filename="My Résumé (final).pdf", **fields):
    form = {"name": "Résumé", "version_label": "v3", "kind": "resume", **fields,
            "file": (io.BytesIO(data), filename)}
    return post(client, "/documents/new", form, content_type="multipart/form-data")


def documents(app):
    with app.app_context():
        return db.session().scalars(select(Document).order_by(Document.id)).all()


def test_upload_download_and_use_a_document(app, me, user_id):
    assert upload(me).status_code == 302
    [doc] = documents(app)
    assert doc.filename == "My-R-sum-final.pdf" and doc.mime == "application/pdf"
    response = me.get(f"/documents/{doc.id}/file")
    assert response.data == PDF and "attachment" in response.headers["Content-Disposition"]
    # Choose it on an application.
    from .test_applications import FORM
    response = post(me, "/applications/new", {**FORM, "resume_id": str(doc.id)})
    job_id = int(response.location.rsplit("/", 1)[1])
    assert get_job(app, job_id).resume_id == doc.id
    assert "Résumé (v3)" in me.get(f"/applications/{job_id}").get_data(as_text=True)
    assert "1 application" in me.get("/documents/").get_data(as_text=True)
    # Deleting the file keeps the application.
    post(me, f"/documents/{doc.id}/delete")
    assert documents(app) == [] and get_job(app, job_id).resume_id is None


def test_each_file_has_a_download_button(app, me):
    upload(me)
    doc = documents(app)[0]
    page = me.get("/documents/").get_data(as_text=True)
    assert f'href="/documents/{doc.id}/file" aria-label="Download Résumé (v3)"' in page
    assert 'aria-label="Edit Résumé (v3)"' in page


def test_companies_show_their_letter(app, me, user_id):
    job_id = add_job(app, user_id, "Initech")
    company_id = get_job(app, job_id).company_id
    badge = f'<span class="company-badge company-badge-{company_id % 6}" aria-hidden="true">I</span>'
    assert badge in me.get("/companies/").get_data(as_text=True)
    assert badge in me.get(f"/companies/{company_id}").get_data(as_text=True)


def test_word_files_too(app, me):
    assert upload(me, DOCX, "cover.docx", kind="cover_letter").status_code == 302
    assert documents(app)[0].filename == "cover.docx"


@pytest.mark.parametrize("data, filename", [
    (b"<script>alert(1)</script>", "evil.pdf"),  # the name says PDF, the bytes don't
    (b"MZ\x90\x00", "program.exe"),
    (DOCX, "archive.zip"),  # a zip that isn't a Word file
    (b"%PDF-" + b"x" * (2 * 1024 * 1024), "huge.pdf"),
])
def test_only_small_pdf_and_word_files(app, me, data, filename):
    response = upload(me, data, filename)
    assert response.status_code == 400
    assert documents(app) == []


def test_someone_elses_document_cant_be_chosen_or_opened(app, client, user_id, other_id):
    with app.app_context():
        s = db.session()
        theirs = Document(user_id=other_id, name="Theirs", filename="t.pdf", mime="application/pdf", size=3, data=PDF)
        s.add(theirs)
        s.commit()
        theirs_id = theirs.id
    log_in_as(client, user_id)
    assert client.get(f"/documents/{theirs_id}/file").status_code == 404
    assert post(client, f"/documents/{theirs_id}/delete").status_code == 404
    from .test_applications import FORM
    response = post(client, "/applications/new", {**FORM, "resume_id": str(theirs_id)})
    assert get_job(app, int(response.location.rsplit("/", 1)[1])).resume_id is None
    assert b"Theirs" not in client.get("/documents/").data


# ---------- Stats ----------

def history(app, user_id, path, source="LinkedIn", started=None):
    """An application that went along path (a list of stages), a day per step."""
    moment = started or utcnow() - timedelta(days=30)
    with app.app_context():
        s = db.session()
        user = s.get(User, user_id)
        from hirewire import companies
        job = Application(user_id=user_id, role_title="Job", source=source, created_at=moment, updated_at=moment,
                          applied_on=moment.date() if path[0] != "saved" else None)
        job.company = companies.find_or_add(s, user_id, "Co")
        s.add(job)
        workflow.start(s, job, path[0], moment)
        for step, stage in enumerate(path[1:], 1):
            s.flush()
            workflow.move(s, job, stage, user, moment + timedelta(days=step * 2))
        s.commit()


def test_the_funnel_counts_the_furthest_step(app, ctx, user_id):
    history(app, user_id, ["applied"])
    history(app, user_id, ["applied", "rejected"])
    history(app, user_id, ["applied", "interview", "rejected"])  # skipped Screening: still counts
    history(app, user_id, ["applied", "screening", "interview", "offer", "accepted"], source="Referral")
    history(app, user_id, ["saved"])  # never sent: not counted
    history(app, user_id, ["interview"], source="Referral")  # added straight in at Interview
    summary = stats.summary(ctx, user_id, local_today("Asia/Manila"))
    assert summary.funnel == [("Applied", 5, 100), ("Got a reply", 3, 60), ("Interview", 3, 60),
                              ("Offer", 1, 20), ("Accepted", 1, 20)]
    # Replies: the rejection, the two that reached Interview by moving, and the one added at Interview.
    assert summary.replied == 4 and summary.response_rate == 80
    # Days to the first reply: 2 (rejected), 2 (interview), 2 (screening).
    assert summary.median_days == 2
    assert summary.sources == [("LinkedIn", 3, 1), ("Referral", 2, 2)]
    assert dict(summary.endings)["Rejected"] == 2 and dict(summary.endings)["Accepted"] == 1


def test_applications_per_week(app, ctx, user_id):
    today = date(2026, 11, 4)  # a Wednesday
    for day in (date(2026, 11, 2), date(2026, 11, 3), date(2026, 10, 28), date(2026, 5, 1)):
        add_job(app, user_id, applied_on=day)
    weeks = dict(stats.per_week(ctx, user_id, today))
    assert len(weeks) == stats.WEEKS
    assert weeks[date(2026, 11, 2)] == 2 and weeks[date(2026, 10, 26)] == 1
    assert sum(weeks.values()) == 3  # May is too long ago


def test_column_shapes():
    shapes = stats.columns([0, 2, 4], width=300, height=100)
    assert shapes[0][1] == ""  # nothing to draw for 0
    assert shapes[2][2] == 0 and shapes[1][2] == 50  # the tallest reaches the top
    assert all(path.endswith("V100 Z") for _, path, _ in shapes[1:])  # square on the baseline


def test_the_stats_page(app, me, user_id):
    assert b"No Stats Yet" in me.get("/stats/").data
    history(app, user_id, ["applied", "screening"])
    page = me.get("/stats/").get_data(as_text=True)
    for words in ("Applications sent", "Response rate", "100%", "How Far They Got", "Sent per Week",
                  "Show as a table", "Where You Found Them", "How They Ended"):
        assert words in page, words


def test_stats_are_private(app, client, user_id, other_id):
    history(app, other_id, ["applied", "offer"], source="Secret Source")
    log_in_as(client, user_id)
    assert b"Secret Source" not in client.get("/stats/").data
