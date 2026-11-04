# AGENTS.md

This file guides AI coding agents (Claude Code, Codex, Cursor, Copilot and others) working in this repository.

## Overview

**Hire Wire**, a job application tracker in Python (Flask). The repo is `job_application_tracker` and the Python package is `hirewire`. People track companies, application stages, interviews and follow-ups; anyone can sign up, and each tracker is private. The plan is `docs/PLAN.md`.

It is a learning project for **filtering, status workflows and reminders**, so those parts stay easy to read: short comments that explain *why*, plain functions that the tests call directly, and no extra libraries unless the owner asks for them. Write the README in simple (A1-level) English.

Python 3.13 is at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`. Use the virtual environment:

- Install: `.venv\Scripts\python -m pip install -r requirements.txt` (create `.venv` with `python -m venv .venv` first if it's missing).
- First time: `.venv\Scripts\flask --app hirewire upgrade-db` (makes the tables).
- Run: `.venv\Scripts\flask --app hirewire run --debug --port 5006`, then open http://127.0.0.1:5006. (Ports: Swap Meter 5000, Ambon Alert 5001, Ang Gastos! 5002, Sangkap 5003, Gawi 5004, Akda 5005.)
- Test: `.venv\Scripts\python -m pytest`. Every test gets a fresh SQLite file and **never goes online**: an autouse fixture in `tests/conftest.py` makes any network connection fail, so fake Gmail (`imaplib.IMAP4_SSL`) and web pages (`quick_add.fetch`) instead. Set `TEST_DATABASE_URL` to an **empty** Neon branch to run the same tests on PostgreSQL (each test drops and remakes the tables). SQLAlchemy warnings fail the tests (`pytest.ini`).
- Other commands: `create-user <name>`, `set-password <name>`, `scan-email <name>` (checks Gmail from this computer; needs the live `DATABASE_URL` and `ENCRYPTION_KEY`).
- Screenshots: `docs/take_screenshots.py` (Playwright + Edge, from Try Demo; its top comment has the steps). Playwright isn't in this `.venv`; the owner borrows `expense_tracker`'s.

## Architecture

- **`workflow.py` is the only place a stage changes.** `TRANSITIONS` lists every allowed move; `move()` checks it, writes a `stage_changes` row (the history the timeline and stats use) and calls `reminders.on_move`. Moving back one step is allowed, and Rejected/Withdrawn/No reply can go back to where they came from. Never set `Application.stage` anywhere else. Stage names and labels live in `models.py`.
- **`filters.py`** reads filters from the address (`parse_filters`, bad values dropped, never errors), narrows a query (`apply_filters`) and writes the address back (`to_args`, defaults left out). Saved views store `view_query()` strings. Search uses `icontains(..., autoescape=True)`, so `%` and `_` are plain letters.
- **`reminders.py`**: there is no background job (Render's free plan sleeps). Follow-ups are rows with a due **day**; pages work out overdue/today/this week when opened. Automatic follow-ups (`auto_kind`) are added after applying and after an interview, and removed when they stop making sense; ones the user made are never removed. The calendar feed (`calendar_feed.py`, `/calendar/<token>.ics`) is how phones get alerts.
- **Times:** moments are naive UTC (`dates.utcnow()`); days (applied on, due on) are plain dates on the person's own calendar. Show moments with the `formatting.py` filters, which use `g.user.timezone`. Parse form times with `dates.parse_local(text, tz)`.
- **Privacy:** every query starts from the logged-in user (`ownership.mine`, `get_mine`, `get_child`). Someone else's id gives 404. `tests/test_*` have a privacy test per area; add routes to them.
- **Gmail** (`gmail.py`, `mail_rules.py`, `suggestions.py`): IMAP with an app password, read-only and `BODY.PEEK`; app passwords are encrypted with Fernet (`crypto.py`, key from `ENCRYPTION_KEY`, else `SECRET_KEY` locally). `mail_rules.py` is plain rules (phrases, checked in order: ignore, offer, strong rejection, interview, weak rejection, applied). Suggestions are only applied when the user presses Accept, and then through `workflow.move(source="email")`. Keep only a 300-character snippet of an email. Defaults like `imaplib.IMAP4_SSL` are looked up at call time so tests can fake them.
- **Quick add** (`quick_add.py`) fetches pages for the user: only http/https, only public addresses (checked again after every redirect), 10 s, 1 MB, 20 an hour.
- **Documents** are kept in the database (Render's disk is wiped) and checked by their first bytes (PDF or .docx only); downloads are `attachment`.
- **Demo:** every "Try Demo" makes its own account (`demo-xxxxxxxx`, `is_demo`), filled by `seed.fill()` and deleted after 2 hours (deleting a user cascades to everything). The demo can't change Settings or upload files. **Every page the demo can open must show an example**; `tests/test_demo.py` fails if one goes empty. Give every new feature sample data in `seed.py` in the same PR.
- **Migrations:** after changing `models.py`, run `upgrade-db`, then `.venv\Scripts\alembic revision --autogenerate --rev-id 00NN -m "what changed"` and check the file. A new NOT NULL column on an existing table needs a `server_default`. On SQLite, Alembic rebuilds a changed table by dropping it; `db.upgrade_db()` turns foreign keys off while migrating so that drop can't cascade-delete other tables (`test_an_upgrade_keeps_the_data`). `tests/test_migrations.py` checks models and migrations agree.
- The page's CSP allows no inline styles or scripts. Charts on the Stats page are SVG with sizes as attributes (`stats.columns()`); the chart teal (`--chart`) was checked for contrast in both themes.

## UI rules (the owner's)

- **Neat first:** no decorative emoji; controls the same height (`--control-height`) with bottoms aligned; the main button of a form last on the right. Sizes in `rem`; the root font steps up at 1600 / 1920 / 2300px; pages fill wide screens (the owner uses a ~2200px window). Layouts use container queries on `.page` (`container: main`).
- **Title Case** for the menu, page titles, section headings, empty-state titles and anything that names a page ("Email Suggestions", "Coming This Week"). Small words stay lowercase unless first. **Sentence case** for buttons, labels, hints and messages ("Add application", "Mark as No reply").
- **Preferences and account actions live in Settings** (theme, time zone, reminders, calendar feed, Gmail, password, recovery code, log out, delete account). The sidebar only moves between pages; Log out is also in the account menu at its bottom.
- **Look:** Plus Jakarta Sans (600 and 700, in `static/fonts/`, see its README) for headings, the name and stat numbers (`--headline`); everything else is Segoe UI. The logo (`mark()` in `_macros.html`) is always a solid tile; its wire colour comes from `--mark-wire` (button-text colour in the sidebar, `--panel` on the login panel). The login panel uses `--panel` (deep teal), never `--accent`, so white text stays readable in dark mode. `tests/test_look.py` guards this.
- Solid buttons hover to `--accent-hover` (clearly darker in light mode, lighter in dark) with a soft `--accent-ring`; the menu's current page also has a teal edge, so it isn't shown by colour alone. The demo's note is one thin line that `setUpDemoNote()` in `app.js` lets people close for the browser session.
- Stage pills always show the stage's name (never colour alone). Dark mode is defined twice in `style.css` (device setting + Settings choice): change both blocks together.
- **Every PR must keep the README's pictures up to date (the owner's standing rule).** Screenshots live in `docs/screenshots/` and every one is shown in the README. If a PR visibly changes a page, retake its pictures; if it adds a page or feature, add a picture to `docs/take_screenshots.py` and the README. `tests/test_readme.py` fails if they disagree. In a PR description, link pictures with a full `raw.githubusercontent.com` address.
- Commit messages and PR bodies go through files (`git commit -F`, `gh pr create --body-file`): PowerShell 5.1 breaks quotes in arguments.
