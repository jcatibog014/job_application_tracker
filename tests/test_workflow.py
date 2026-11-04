"""The status workflow: every move is checked, recorded, and shown."""
import itertools

import pytest
from sqlalchemy import select

from hirewire import db, workflow
from hirewire.models import (
    ACCEPTED, APPLIED, CLOSED_STAGES, DECLINED, INTERVIEW, NO_REPLY, OFFER, REJECTED, SAVED, SCREENING, STAGES,
    WITHDRAWN, StageChange,
)

from .conftest import add_job, get_job, post

# Every move the workflow allows (without a "came from"). Anything else must be refused.
ALLOWED = {
    (SAVED, APPLIED), (SAVED, WITHDRAWN),
    (APPLIED, SCREENING), (APPLIED, INTERVIEW), (APPLIED, OFFER), (APPLIED, REJECTED), (APPLIED, WITHDRAWN),
    (APPLIED, NO_REPLY), (APPLIED, SAVED),
    (SCREENING, INTERVIEW), (SCREENING, OFFER), (SCREENING, REJECTED), (SCREENING, WITHDRAWN),
    (SCREENING, NO_REPLY), (SCREENING, APPLIED),
    (INTERVIEW, OFFER), (INTERVIEW, REJECTED), (INTERVIEW, WITHDRAWN), (INTERVIEW, NO_REPLY), (INTERVIEW, SCREENING),
    (OFFER, ACCEPTED), (OFFER, DECLINED), (OFFER, REJECTED), (OFFER, INTERVIEW),
    (ACCEPTED, OFFER), (DECLINED, OFFER),
    (NO_REPLY, SCREENING), (NO_REPLY, INTERVIEW), (NO_REPLY, OFFER), (NO_REPLY, REJECTED),
}


@pytest.mark.parametrize("before, after", [pair for pair in itertools.permutations(STAGES, 2)])
def test_every_pair_of_stages_against_the_table(before, after):
    assert workflow.can_move(before, after) == ((before, after) in ALLOWED)


def test_closed_stages_can_go_back_where_they_came_from():
    assert workflow.allowed_moves(REJECTED) == []
    assert workflow.allowed_moves(REJECTED, came_from=INTERVIEW) == [INTERVIEW]
    assert workflow.allowed_moves(WITHDRAWN, came_from=SAVED) == [SAVED]
    assert workflow.allowed_moves(NO_REPLY, came_from=APPLIED) == [SCREENING, INTERVIEW, OFFER, REJECTED, APPLIED]
    # Only the closing stages reopen: Applied doesn't gain a move from its past.
    assert workflow.allowed_moves(APPLIED, came_from=INTERVIEW) == workflow.allowed_moves(APPLIED)


def test_buttons_are_grouped_forward_endings_and_back():
    assert workflow.group_moves(SCREENING) == ([INTERVIEW, OFFER], [REJECTED, WITHDRAWN, NO_REPLY], [APPLIED])
    assert workflow.group_moves(OFFER) == ([ACCEPTED, DECLINED], [REJECTED], [INTERVIEW])
    assert workflow.group_moves(NO_REPLY, came_from=APPLIED) == ([SCREENING, INTERVIEW, OFFER], [REJECTED], [APPLIED])


def history(app, job_id):
    with app.app_context():
        return [(row.from_stage, row.to_stage, row.source) for row in db.session().scalars(
            select(StageChange).where(StageChange.application_id == job_id).order_by(StageChange.id))]


def test_a_move_writes_history_and_shows_on_the_timeline(app, me, user_id):
    job_id = add_job(app, user_id)
    response = post(me, f"/applications/{job_id}/move", {"to": SCREENING, "note": "Recruiter called."})
    assert response.status_code == 302
    assert get_job(app, job_id).stage == SCREENING
    assert history(app, job_id) == [(None, APPLIED, "manual"), (APPLIED, SCREENING, "manual")]
    page = me.get(f"/applications/{job_id}").data
    assert b"Moved to Screening" in page and b"Recruiter called." in page and b"Added as Applied" in page


def test_a_move_that_isnt_allowed_changes_nothing(app, me, user_id):
    job_id = add_job(app, user_id, stage=SAVED)
    response = post(me, f"/applications/{job_id}/move", {"to": OFFER}, follow_redirects=True)
    assert b"can&#39;t go from Saved to Offer" in response.data
    assert get_job(app, job_id).stage == SAVED
    assert len(history(app, job_id)) == 1
    post(me, f"/applications/{job_id}/move", {"to": "promoted"})
    assert get_job(app, job_id).stage == SAVED


def test_leaving_saved_sets_the_applied_date(app, me, user_id):
    job_id = add_job(app, user_id, stage=SAVED)
    assert get_job(app, job_id).applied_on is None
    post(me, f"/applications/{job_id}/move", {"to": APPLIED})
    assert get_job(app, job_id).applied_on is not None


def test_reopen_a_rejection_made_by_mistake(app, me, user_id):
    job_id = add_job(app, user_id, stage=INTERVIEW)
    post(me, f"/applications/{job_id}/move", {"to": REJECTED})
    page = me.get(f"/applications/{job_id}").data
    assert b"Closed as Rejected" in page and b"Back to Interview" in page
    post(me, f"/applications/{job_id}/move", {"to": INTERVIEW})
    assert get_job(app, job_id).stage == INTERVIEW


def test_the_board_drag_gets_json(app, me, user_id):
    job_id = add_job(app, user_id)
    response = post(me, f"/applications/{job_id}/move", {"to": INTERVIEW, "from": "board"},
                    headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.json == {"stage": INTERVIEW, "label": "Interview",
                             "moves": [OFFER, REJECTED, WITHDRAWN, NO_REPLY, SCREENING]}
    assert history(app, job_id)[-1] == (APPLIED, INTERVIEW, "board")
    refused = post(me, f"/applications/{job_id}/move", {"to": SAVED, "from": "board"},
                   headers={"Accept": "application/json"})
    assert refused.status_code == 409 and "can't go from Interview to Saved" in refused.json["error"]


def test_the_board_shows_columns_and_closed(app, me, user_id):
    add_job(app, user_id, "Acme", "Analyst", stage=SCREENING)
    add_job(app, user_id, "Initech", "Writer", stage=REJECTED)
    page = me.get("/board/").get_data(as_text=True)
    for label in ("Saved", "Applied", "Screening", "Interview", "Offer", "Closed"):
        assert label in page
    assert "Analyst" in page and "Writer" in page
    # Each card only offers the moves it may make.
    assert 'data-moves="interview offer rejected withdrawn no_reply applied"' in page
    assert 'data-moves="applied"' in page  # the rejected one can go back to Applied


def test_the_board_move_menu_works_without_javascript(app, me, user_id):
    job_id = add_job(app, user_id)
    response = post(me, f"/applications/{job_id}/move", {"to": SCREENING, "from": "board", "next": "/board/"})
    assert response.location.endswith("/board/")
    unsafe = post(me, f"/applications/{job_id}/move", {"to": INTERVIEW, "next": "https://evil.example"})
    assert unsafe.location.endswith(f"/applications/{job_id}")


def test_new_applications_start_their_history(app, me):
    from .test_applications import FORM
    response = post(me, "/applications/new", {**FORM, "stage": INTERVIEW})
    job_id = int(response.location.rsplit("/", 1)[1])
    assert history(app, job_id) == [(None, INTERVIEW, "manual")]


def test_closed_stages_are_known():
    assert set(CLOSED_STAGES) == {ACCEPTED, DECLINED, REJECTED, WITHDRAWN, NO_REPLY}
