"""Applications, companies and notes, and that nobody sees anyone else's."""
from datetime import date

import pytest
from sqlalchemy import func, select

from hirewire import db
from hirewire.dates import local_today
from hirewire.models import Application, Company, Note

from .conftest import add_job, get_job, log_in_as, post

FORM = {
    "company_name": "Globe Telecom", "role_title": "Junior Data Analyst", "stage": "applied", "applied_on": "",
    "location": "Taguig City", "work_mode": "hybrid", "salary_min": "40,000", "salary_max": "55000",
    "currency": "PHP", "source": "LinkedIn", "posting_url": "careers.example.com/jobs/12",
    "job_description": "Clean data and build dashboards.",
}


def count(app, model):
    with app.app_context():
        return db.session().scalar(select(func.count()).select_from(model))


def test_add_an_application(app, me, user_id):
    response = post(me, "/applications/new", FORM)
    assert response.status_code == 302
    job = get_job(app, int(response.location.rsplit("/", 1)[1]))
    assert job.company.name == "Globe Telecom" and job.user_id == user_id
    assert (job.salary_min, job.salary_max) == (40000, 55000)
    assert job.posting_url == "https://careers.example.com/jobs/12"
    assert job.applied_on == local_today("Asia/Manila")  # empty means today, when it's past Saved
    page = me.get(response.location).data
    assert b"Junior Data Analyst" in page and b"PHP 40,000" in page and b"Clean data" in page


def test_a_saved_job_has_no_applied_date(app, me):
    response = post(me, "/applications/new", {**FORM, "stage": "saved"})
    assert get_job(app, int(response.location.rsplit("/", 1)[1])).applied_on is None


def test_the_same_company_is_used_however_it_is_typed(app, me):
    post(me, "/applications/new", FORM)
    post(me, "/applications/new", {**FORM, "company_name": "  GLOBE   telecom "})
    assert count(app, Company) == 1
    assert count(app, Application) == 2


@pytest.mark.parametrize("change, field", [
    ({"company_name": ""}, b"A company is needed"),
    ({"role_title": ""}, b"A job title is needed"),
    ({"salary_min": "lots"}, b"whole number"),
    ({"salary_min": "60000", "salary_max": "50000"}, b"less than the lowest"),
    ({"posting_url": "javascript:alert(1)"}, b"web address"),
    ({"stage": "accepted"}, b"Choose one"),
    ({"applied_on": "13/13/2026"}, b"date like"),
])
def test_form_problems_are_explained(app, me, change, field):
    response = post(me, "/applications/new", {**FORM, **change})
    assert response.status_code == 400 and field in response.data
    assert count(app, Application) == 0


def test_edit_an_application(app, me, user_id):
    job_id = add_job(app, user_id)
    form = {**FORM, "role_title": "Senior Data Analyst", "applied_on": "2026-10-01"}
    form.pop("stage")
    assert post(me, f"/applications/{job_id}/edit", form).status_code == 302
    job = get_job(app, job_id)
    assert job.role_title == "Senior Data Analyst" and job.applied_on == date(2026, 10, 1)
    assert job.stage == "applied"  # the edit form never changes the stage
    assert b'value="Senior Data Analyst"' in me.get(f"/applications/{job_id}/edit").data


def test_notes_show_on_the_timeline_and_can_be_deleted(app, me, user_id):
    job_id = add_job(app, user_id)
    post(me, f"/applications/{job_id}/notes", {"body": "Asked about the team size."})
    assert b"Asked about the team size." in me.get(f"/applications/{job_id}").data
    note_id = get_job(app, job_id).notes[0].id
    post(me, f"/applications/notes/{note_id}/delete")
    assert count(app, Note) == 0


def test_an_empty_note_is_refused(app, me, user_id):
    job_id = add_job(app, user_id)
    post(me, f"/applications/{job_id}/notes", {"body": "   "})
    assert count(app, Note) == 0


def test_delete_an_application_deletes_its_notes(app, me, user_id):
    job_id = add_job(app, user_id)
    post(me, f"/applications/{job_id}/notes", {"body": "x"})
    post(me, f"/applications/{job_id}/delete")
    assert count(app, Application) == count(app, Note) == 0


def test_the_list_shows_my_applications(app, me, user_id):
    add_job(app, user_id, "Acme", "Data Analyst")
    add_job(app, user_id, "Initech", "Report Writer", stage="saved")
    page = me.get("/applications/").data
    assert b"Acme" in page and b"Report Writer" in page and b"Saved" in page


# ---------- Companies ----------

def test_companies_list_counts_applications(app, me, user_id):
    add_job(app, user_id, "Acme")
    add_job(app, user_id, "Acme", "Analyst II")
    page = me.get("/companies/").data
    assert b"Acme" in page and b"2 applications" in page
    assert b"No Matching Companies" in me.get("/companies/?q=zzz").data


def test_add_and_edit_a_company(app, me):
    response = post(me, "/companies/new", {"name": "Initech", "website": "initech.example", "industry": "Software",
                                           "location": "Pasig", "notes": "Nice office."})
    company_id = int(response.location.rsplit("/", 1)[1])
    page = me.get(f"/companies/{company_id}").data
    assert b"https://initech.example" in page and b"Nice office." in page
    post(me, f"/companies/{company_id}/edit", {"name": "Initech Corp", "website": "", "industry": "",
                                                "location": "", "notes": ""})
    assert b"Initech Corp" in me.get(f"/companies/{company_id}").data


def test_two_companies_cant_share_a_name(app, me, user_id):
    add_job(app, user_id, "Acme")
    response = post(me, "/companies/new", {"name": "acme", "website": "", "industry": "", "location": "", "notes": ""})
    assert response.status_code == 400 and b"already have a company" in response.data


def test_a_company_with_applications_cant_be_deleted(app, me, user_id):
    job_id = add_job(app, user_id, "Acme")
    company_id = get_job(app, job_id).company_id
    post(me, f"/companies/{company_id}/delete")
    assert count(app, Company) == 1
    post(me, f"/applications/{job_id}/delete")
    post(me, f"/companies/{company_id}/delete")
    assert count(app, Company) == 0


def test_deleting_an_account_deletes_its_applications(app, me, user_id):
    add_job(app, user_id)
    from .conftest import PASSWORD
    post(me, "/settings/", {"action": "delete", "password": PASSWORD})
    assert count(app, Application) == count(app, Company) == 0


# ---------- Privacy ----------

def test_someone_elses_rows_are_not_found(app, client, user_id, other_id):
    job_id = add_job(app, other_id, "Secret Corp")
    company_id = get_job(app, job_id).company_id
    with app.app_context():
        s = db.session()
        s.add(Note(application_id=job_id, body="private"))
        s.commit()
        note_id = s.scalar(select(Note.id))
    log_in_as(client, user_id)
    for url in (f"/applications/{job_id}", f"/applications/{job_id}/edit", f"/companies/{company_id}",
                f"/companies/{company_id}/edit"):
        assert client.get(url).status_code == 404, url
    for url in (f"/applications/{job_id}/delete", f"/applications/{job_id}/notes",
                f"/applications/notes/{note_id}/delete", f"/companies/{company_id}/delete"):
        assert post(client, url, {"body": "x"}).status_code == 404, url
    assert b"Secret Corp" not in client.get("/applications/").data
    assert b"Secret Corp" not in client.get("/companies/").data
    assert count(app, Application) == 1 and count(app, Note) == 1


def test_my_company_names_are_mine(app, me, user_id, other_id):
    add_job(app, other_id, "Secret Corp")
    assert b"Secret Corp" not in me.get("/applications/new").data
    # Typing the same name makes my own company, not a link to theirs.
    post(me, "/applications/new", {**FORM, "company_name": "Secret Corp"})
    with app.app_context():
        owners = db.session().scalars(select(Company.user_id).where(Company.name == "Secret Corp")).all()
    assert sorted(owners) == sorted([user_id, other_id])
