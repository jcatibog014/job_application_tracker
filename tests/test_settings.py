"""Settings: time zone, password, recovery code, deleting the account."""
from hirewire.dates import to_local

from .conftest import PASSWORD, get_user, is_logged_in, log_in_as, post


def test_settings_page_has_every_section(me):
    page = me.get("/settings/").data
    for heading in (b"Appearance", b"Time Zone", b"Your Password", b"Recovery Code", b"Your Account",
                    b"Delete Account"):
        assert heading in page
    assert b"Log out" in page


def test_change_time_zone(app, me):
    response = post(me, "/settings/", {"action": "timezone", "timezone": "Asia/Tokyo"})
    assert response.status_code == 302
    assert get_user(app, "ana").timezone == "Asia/Tokyo"


def test_an_unknown_time_zone_is_refused(app, me):
    response = post(me, "/settings/", {"action": "timezone", "timezone": "Mars/Olympus"})
    assert response.status_code == 400
    assert get_user(app, "ana").timezone == "Asia/Manila"


def test_change_password_keeps_this_device_logged_in(app, me):
    response = post(me, "/settings/", {"action": "password", "current_password": PASSWORD,
                                       "new_password": "another one", "confirm_password": "another one"})
    assert response.status_code == 302
    assert is_logged_in(me)


def test_change_password_needs_the_current_one(me):
    response = post(me, "/settings/", {"action": "password", "current_password": "wrong",
                                       "new_password": "another one", "confirm_password": "another one"})
    assert response.status_code == 400 and b"current password" in response.data


def test_a_new_recovery_code_needs_the_password(app, me):
    old = get_user(app, "ana").recovery_hash
    assert post(me, "/settings/", {"action": "recovery", "password": "wrong"}).status_code == 400
    response = post(me, "/settings/", {"action": "recovery", "password": PASSWORD})
    assert response.location.endswith("/recovery-code")
    assert b"Your old code no longer works" in me.get("/recovery-code").data
    assert get_user(app, "ana").recovery_hash != old


def test_delete_account(app, me, other_id):
    assert post(me, "/settings/", {"action": "delete", "password": "wrong"}).status_code == 400
    assert get_user(app, "ana") is not None
    response = post(me, "/settings/", {"action": "delete", "password": PASSWORD})
    assert response.status_code == 302
    assert get_user(app, "ana") is None
    assert get_user(app, "ben") is not None
    assert not is_logged_in(me)


def test_dates_follow_the_time_zone():
    from datetime import datetime
    moment = datetime(2026, 11, 3, 20, 0)  # 8 PM UTC
    assert to_local(moment, "Asia/Manila").day == 4  # already the next morning
    assert to_local(moment, "America/New_York").day == 3
    assert to_local(moment, "Not/AZone").day == 4  # unknown falls back to Manila


def test_settings_links_in_the_menu(client, user_id):
    page = log_in_as(client, user_id).get("/dashboard/").data
    assert b'href="/settings/"' in page
    assert b"Account menu for" in page
