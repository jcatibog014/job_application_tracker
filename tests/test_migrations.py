"""The Alembic migrations make exactly the tables that models.py describes."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from hirewire import create_app, db
from hirewire.db import Base


def test_upgrade_on_an_empty_database_matches_the_models(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "fresh.sqlite"), "DATABASE_URL": None})
    with app.app_context():
        db.upgrade_db()
        db.upgrade_db()  # running it again changes nothing
        with db.engine().connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
            tables = set(inspect(connection).get_table_names())
    # Nothing left for "alembic revision --autogenerate" to write: the
    # migrations and the models agree. If this fails after changing
    # models.py, make a new migration (see AGENTS.md).
    assert differences == []
    assert {"users", "alembic_version"} <= tables


def test_an_upgrade_keeps_the_data(tmp_path):
    """SQLite rebuilds a changed table by dropping the old one. That must never
    delete the rows that point at it (it once emptied every table here)."""
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "old.sqlite"), "DATABASE_URL": None})
    with app.app_context():
        db.upgrade_db("0004")  # before users and applications got new columns
        with db.engine().begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, password_hash, recovery_hash, timezone, is_demo, failed_logins, "
                "session_version, created_at) VALUES (1, 'ana', 'x', 'x', 'Asia/Manila', 0, 0, 1, '2026-11-01')")
            connection.exec_driver_sql(
                "INSERT INTO companies (id, user_id, name, name_key, website, industry, location, notes, created_at) "
                "VALUES (1, 1, 'Acme', 'acme', '', '', '', '', '2026-11-01')")
            connection.exec_driver_sql(
                "INSERT INTO applications (id, user_id, company_id, role_title, posting_url, location, work_mode, "
                "currency, source, stage, stage_changed_at, job_description, created_at, updated_at) VALUES "
                "(1, 1, 1, 'Analyst', '', '', '', 'PHP', '', 'applied', '2026-11-01', '', '2026-11-01', '2026-11-01')")
            connection.exec_driver_sql(
                "INSERT INTO notes (id, application_id, body, created_at) VALUES (1, 1, 'hello', '2026-11-01')")
        db.upgrade_db()
        with db.engine().connect() as connection:
            counts = {table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
                      for table in ("users", "companies", "applications", "notes")}
            follow_up_days = connection.exec_driver_sql("SELECT follow_up_days FROM users").scalar()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert counts == {"users": 1, "companies": 1, "applications": 1, "notes": 1}
    assert follow_up_days == 7  # old accounts get the same reminder settings as new ones
    assert foreign_keys == 1  # switched back on afterwards


def test_upgrade_db_command(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "cli.sqlite"), "DATABASE_URL": None})
    result = app.test_cli_runner().invoke(args=["upgrade-db"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
