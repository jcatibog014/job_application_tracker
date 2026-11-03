"""Signing up, logging in, the lock, recovery codes and form safety."""
import re
from datetime import timedelta

from werkzeug.security import check_password_hash

from hirewire import auth
from hirewire.dates import utcnow

from .conftest import PASSWORD, get_user, is_logged_in, log_in_as, make_user, post


def sign_up(client, username="carla", password="long enough", confirm=None, **extra):
    return post(client, "/signup", {"username": username, "password": password,
                                     "confirm_password": confirm or password, **extra})


def recovery_code_page(client):
    page = client.get("/recovery-code").get_data(as_text=True)
    return re.search(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", page).group(0)


# ---------- Sign up ----------

def test_sign_up_logs_in_and_shows_the_recovery_code_once(app, client):
    response = sign_up(client)
    assert response.status_code == 302 and response.location.endswith("/recovery-code")
    assert is_logged_in(client)
    code = recovery_code_page(client)
    user = get_user(app, "carla")
    assert check_password_hash(user.recovery_hash, auth.clean_recovery_code(code))
    assert code not in user.recovery_hash  # only the hash is kept
    # The second visit has nothing to show.
    assert client.get("/recovery-code").status_code == 302


def test_the_recovery_page_is_never_cached(client):
    sign_up(client)
    assert client.get("/recovery-code").headers["Cache-Control"] == "no-store"


def test_sign_up_problems_are_explained(client, user_id):
    assert b"already taken" in sign_up(client, "ana").data
    assert b"3 to 40" in sign_up(client, "ab").data
    assert b"letters, numbers" in sign_up(client, "two words").data
    assert b"not available" in sign_up(client, "demo-x").data
    assert b"not available" in sign_up(client, "admin").data
    assert b"at least 8" in sign_up(client, password="short").data
    assert b"not the same" in sign_up(client, confirm="something else").data


def test_usernames_are_kept_in_small_letters(app, client):
    sign_up(client, "  Carla ")
    assert get_user(app, "carla") is not None


def test_a_robot_filling_the_hidden_field_makes_no_account(app, client):
    response = sign_up(client, website="http://spam.example")
    assert response.status_code == 302
    assert get_user(app, "carla") is None


# ---------- Log in and out ----------

def test_log_in_and_out(client, user_id):
    response = post(client, "/login", {"username": "ana", "password": PASSWORD})
    assert response.status_code == 302 and response.location.endswith("/dashboard/")
    assert is_logged_in(client)
    post(client, "/logout")
    assert not is_logged_in(client)


def test_a_wrong_password_says_nothing_about_the_username(client, user_id):
    wrong_password = post(client, "/login", {"username": "ana", "password": "nope"})
    no_such_user = post(client, "/login", {"username": "nobody", "password": "nope"})
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert auth.WRONG_LOGIN.encode() in wrong_password.data
    assert auth.WRONG_LOGIN.encode() in no_such_user.data


def test_five_wrong_passwords_lock_the_account(app, client, user_id):
    for _ in range(auth.MAX_FAILED_LOGINS):
        post(client, "/login", {"username": "ana", "password": "nope"})
    response = post(client, "/login", {"username": "ana", "password": PASSWORD})
    assert b"Too many failed attempts" in response.data
    assert get_user(app, "ana").locked_until > utcnow()


def test_the_lock_ends_after_15_minutes(app, client):
    make_user(app, "ana", locked_until=utcnow() - timedelta(seconds=1))
    assert post(client, "/login", {"username": "ana", "password": PASSWORD}).status_code == 302


def test_login_goes_back_to_the_page_asked_for(client, user_id):
    response = client.get("/settings/")
    assert response.status_code == 302 and "next=" in response.location
    response = post(client, "/login", {"username": "ana", "password": PASSWORD, "next": "/settings/"})
    assert response.location.endswith("/settings/")


def test_safe_next_refuses_other_sites(app):
    with app.test_request_context():
        assert auth.safe_next("/applications/3") == "/applications/3"
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example", "/\tx", None, ""):
            assert auth.safe_next(bad) == "/dashboard/"


def test_an_old_cookie_stops_working_after_a_password_change(app, client, user_id):
    log_in_as(client, user_id)
    with app.app_context():
        from hirewire import db
        user = db.session().get(auth.User, user_id)
        auth.set_password(user, "a new password")
        db.session().commit()
    assert not is_logged_in(client)


def test_pages_need_a_login(client):
    for url in ("/dashboard/", "/settings/"):
        response = client.get(url)
        assert response.status_code == 302 and "/login" in response.location
    assert client.get("/").location.endswith("/login")


# ---------- Forgot password ----------

def forgot(client, code, username="carla", new="brand new password"):
    return post(client, "/forgot", {"username": username, "code": code,
                                     "new_password": new, "confirm_password": new})


def test_the_recovery_code_sets_a_new_password_and_gives_a_new_code(app, client):
    sign_up(client)
    code = recovery_code_page(client)
    post(client, "/logout")
    # Typed by hand: small letters and spaces still work.
    response = forgot(client, code.lower().replace("-", " "))
    assert response.status_code == 302 and response.location.endswith("/recovery-code")
    new_code = recovery_code_page(client)
    assert new_code != code
    post(client, "/logout")
    assert post(client, "/login", {"username": "carla", "password": "brand new password"}).status_code == 302
    # The old code was used up.
    post(client, "/logout")
    assert b"Wrong username or recovery code" in forgot(client, code).data


def test_a_wrong_recovery_code_changes_nothing_and_counts_towards_the_lock(app, client, user_id):
    for _ in range(auth.MAX_FAILED_LOGINS):
        response = forgot(client, "AAAA-BBBB-CCCC-DDDD", username="ana")
        assert response.status_code == 400
    assert b"Too many failed attempts" in response.data
    assert post(client, "/login", {"username": "ana", "password": PASSWORD}).status_code == 401


def test_recovery_codes_are_easy_to_copy():
    code = auth.new_recovery_code()
    assert re.fullmatch(r"([A-Z2-9]{4}-){3}[A-Z2-9]{4}", code)
    assert not set("01ILO") & set(code)


# ---------- Every form is protected ----------

def test_a_post_without_the_csrf_token_fails(client, user_id):
    log_in_as(client, user_id)
    assert client.post("/logout").status_code == 400
    assert client.post("/login", data={"username": "ana", "password": PASSWORD}).status_code == 400


def test_security_headers(client):
    headers = client.get("/login").headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_create_user_command(app):
    result = app.test_cli_runner().invoke(args=["create-user", "dina"], input="long password\nlong password\n")
    assert result.exit_code == 0, result.output
    assert "Recovery code" in result.output
    assert get_user(app, "dina") is not None
