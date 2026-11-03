# Plan: "Hire Wire", a job application tracker

The plan agreed on 2026-11-03.
## Context

A new learning project for https://github.com/jcatibog014/job_application_tracker (it only has a one-line README). It tracks companies, application stages, interview dates and follow-ups. The skills to practise are **filtering, status workflows and reminders**.

Python suits it: the Flask + SQLAlchemy + Alembic setup from Akda (`Documents\Workspace\personal_blog`) already has the login, database and deploy plumbing. Python's built-in `imaplib` and `email` can also read Gmail for the automatic part.

**Can it fill itself in automatically?** Partly:
- **LinkedIn:** no live connection. Its API is for approved partners only, and copying its pages breaks its rules. (Its data download has an applications CSV, but you didn't pick that import.)
- **Gmail:** yes. It reads the inbox with an app password and **suggests** updates that you accept or ignore. It never changes data by itself.
- **Calendar:** yes. A private feed link puts interviews and follow-ups in Google Calendar, with phone alerts.

What you chose:
- **Name:** Hire Wire. Repo `job_application_tracker`, package `hirewire`, local port 5006.
- **Accounts:** open sign-up (each person has a private tracker), plus a Try Demo button.
- **Automation:** calendar feed, Gmail scan (suggestions), quick add from a job link.
- **Extras:** board view, stats, contacts and notes, documents.
- **Look:** calm office, with light and dark modes.
- **Delivery:** one PR with a commit per stage, no stops for confirmation.
- **Deploy:** Render + Neon. I prepare the files and guide you; you do the account steps.

## Stack

- Python 3.13, Flask 3, Jinja, server-rendered forms. Every page works without JavaScript; `app.js` only adds extras (drag on the board, filter auto-submit, menu, theme).
- SQLAlchemy 2.0 + Alembic. SQLite locally and in tests, Neon PostgreSQL live.
- New libraries:
  - **icalendar** writes the calendar feed and reads `.ics` invites attached to emails.
  - **cryptography** (Fernet) encrypts Gmail app passwords, with the key in the `ENCRYPTION_KEY` environment variable.
  - **requests** + **beautifulsoup4** read job pages for quick add.
  - **tzdata** gives Windows the time zone data.
- Dates are stored in UTC and shown in the user's time zone (a Settings choice, default Asia/Manila).

## Reuse from `Documents\Workspace\personal_blog` (Akda)

Copy and adapt rather than rewrite:
- `akda/db.py`: engine, per-request session, naming convention, `upgrade-db`.
- `akda/auth.py`: `check_login()` with its 5-try lock, `safe_next()`, `log_in()`, `load_user()`, CSRF, `session_version`, honeypot sign-up, rate limits, CLI (`create-user`, `set-password`).
- `akda/__init__.py`: cookie settings, ProxyFix, CSP and security headers.
- `akda/dates.py` for date display. The pattern of `akda/permissions.py` becomes ownership checks, where another user's data gives 404.
- `akda/migrations/`, `alembic.ini`, `pytest.ini`, `tests/conftest.py`, `tests/test_migrations.py`, `tests/test_demo.py`, `tests/test_readme.py`, `docs/take_screenshots.py`, `docs/make_practice_data.py`, `render.yaml`, `.python-version`, `.gitignore`, `AGENTS.md` + `CLAUDE.md`.
- The Settings page layout (one column of aligned rows) and the sidebar from Akda's Desk / Gawi.

## The status workflow (`hirewire/workflow.py`, pure functions)

```
Saved → Applied → Screening → Interview → Offer → Accepted
          │           │           │          └──→ Declined
          └───────────┴───────────┴──→ Rejected / Withdrawn / No reply
```
- One `TRANSITIONS` table lists every allowed move. `move(app, to_stage, when, note, source)` checks it, updates `applications.stage`, and writes a `stage_changes` row. Nothing else changes a stage.
- Moving back one step is allowed (to fix a mistake). "No reply" can reopen to the stage it came from, because late replies happen.
- Interview rounds are rows in `interviews`; the stage stays Interview until it moves on.
- Every application page shows a **timeline** that merges stage changes, interviews, notes and accepted email suggestions.

## Reminders (no background job, because Render's free plan sleeps)

- **Follow-ups:** a due date + note per application. Done, Snooze (+1 day, +3 days, +1 week), Edit.
- **Automatic follow-up:** moving to Applied creates one 7 days later, and an interview creates a thank-you one the next day. Both delays are Settings choices and can be switched off.
- **No reply nudge:** after 21 days in Applied or Screening with no change, the dashboard asks "Mark as No reply?". It never changes the stage by itself.
- **Where they show:** the Dashboard (Overdue, Today, This Week), a count badge on the sidebar, and the Schedule page (interviews + follow-ups by day).
- **Calendar feed:** `/calendar/<secret>.ics`, made in Settings, with "Make a new link" to cancel the old one. Interviews are timed events with an alarm 1 hour before; follow-ups are all-day events. Google refreshes subscribed feeds about every 12–24 hours, as Settings will say.

## Filtering (`hirewire/filters.py`)

- The Applications page is a table with filters kept in the URL query string, so a filtered view can be bookmarked:
  - search (role, company, notes; escaped `LIKE`);
  - stage (several), work mode (on-site/hybrid/remote), source, location;
  - applied date range, minimum salary;
  - "has upcoming interview", "follow-up due", "include closed".
- Sort by any column; 25 per page.
- **Saved views:** name the current filters (e.g. "Remote, active"). Three come with every account: Active, Needs Follow-up, Interviews This Week.
- `parse_filters(args)` → a dataclass and `apply_filters(select, f)` → a query, both pure and tested on their own. Bad values are dropped, never errors.

## Automation

**Gmail scan (suggestions only)**
- Settings → Connect Gmail: an address + app password (with step-by-step help for making one; it needs 2-step verification). The app checks the login, then stores the password encrypted.
- "Check email" on the Email Suggestions page, and automatically when that page opens if the last check was over an hour ago. It reads with IMAP in read-only mode (`BODY.PEEK`, so mail stays unread) and uses Gmail's search to only fetch likely mail from the last 30 days, at most 200 messages.
- `hirewire/mail_rules.py` (pure, tested on sample emails):
  - **Classify** as applied confirmation, interview invite, rejection, offer or ignore, using keyword rules.
  - **Find the company** from the sender name/domain and subject, and match it to an existing application.
  - **Read the interview time** from an attached `.ics` first, else a date pattern.
- Each suggestion shows the email subject, a short snippet and the proposed change, with Accept (which goes through `workflow.move` with `source='email'`), Edit then accept, or Ignore. Each Gmail message id is stored once, so a message is never suggested twice. Only a 300-character snippet is kept, never the whole email.
- Risk to check when deploying: if Render blocks IMAP (port 993), `flask scan-email` can run from your PC against Neon instead.

**Quick add from link**
- Paste a job URL, and the server fetches it (10-second timeout, 1 MB limit, http/https only, private and local addresses refused against SSRF). It reads the page's schema.org `JobPosting` data, else its `og:` tags. Then it fills in the new-application form for you to check: title, company, location, salary and a copy of the job description. If a site blocks it (LinkedIn often does), the form opens with just the link.
- Limited to 20 fetches per hour per account.

## Data model

```
users ─┬─< companies ─┬─< applications ─┬─< stage_changes
       │              │                 ├─< interviews
       │              │                 ├─< follow_ups
       │              │                 ├─< notes
       │              │                 └─< application_contacts >── contacts
       │              └─< contacts
       ├─< documents (résumé / cover letter versions, linked from applications)
       ├─< saved_views
       ├── gmail_accounts (one)
       └─< email_suggestions
```

| Table | Key columns | Notes |
|---|---|---|
| `users` | username UNIQUE, password_hash, recovery_hash, timezone, calendar_token UNIQUE, follow-up settings, is_demo, demo_expires_at, failed_logins, locked_until, session_version | |
| `companies` | user_id, name, website, industry, location, notes; UNIQUE(user_id, name) | |
| `applications` | user_id, company_id, role_title, posting_url, location, work_mode (CHECK), salary_min, salary_max, currency (PHP), source, stage (CHECK), stage_changed_at, applied_on, job_description, resume_id, cover_letter_id, created_at, updated_at | Index on (user_id, stage) |
| `stage_changes` | application_id, from_stage, to_stage, changed_at, note, source (manual/email/board) | The history and the stats |
| `interviews` | application_id, starts_at, minutes, kind, place_or_link, with_whom, prep_notes, outcome | |
| `follow_ups` | application_id, due_on, note, done_at, auto_kind | |
| `notes` | application_id, body, created_at | |
| `contacts` | user_id, company_id, name, job_title, email, phone, profile_url, notes, last_contacted_on | |
| `application_contacts` | application_id, contact_id, role (recruiter/referral/interviewer) | Many-to-many |
| `documents` | user_id, kind, name, version_label, data (deferred), mime, size | PDF/DOCX up to 2 MB, in the DB because Render's disk is wiped |
| `saved_views` | user_id, name, query | |
| `gmail_accounts` | user_id UNIQUE, address, password_encrypted, last_checked_at | |
| `email_suggestions` | user_id, message_id, sender, subject, snippet, received_at, kind, company_guess, proposed_at, application_id, status; UNIQUE(user_id, message_id) | |

Rules that avoid common bugs:
- **Privacy:** every query starts from `current_user`. Another user's id in a URL gives 404 (a test tries every route).
- **Forgotten password without email:** sign-up shows a one-time **recovery code** (stored hashed). It resets the password and is replaced by a new one.
- **Stats** come from `stage_changes` with `GROUP BY` (funnel, response rate, median days to first reply, per week, by source). The charts are plain HTML/CSS bars, so no chart library has to download.

## Demo

"Try Demo" makes a **fresh temporary account for each visitor**, filled with sample data and deleted after 2 hours (cleaned up when the next demo starts), so visitors never see each other's changes. Every page has examples:
- about 15 applications in every stage, with timelines;
- interviews and follow-ups (overdue, today, upcoming);
- contacts, document versions, saved views, stats;
- email suggestions from a built-in set of sample emails, run through the real `mail_rules.py`.

Connect Gmail is shown switched off for the demo. `tests/test_demo.py` fails if any demo page is empty.

## Layout and look

- **Sidebar** (Akda Desk / Gawi style; ☰ on phones): Dashboard, Applications, Board, Schedule, Companies, Contacts, Documents, Stats, Email Suggestions (with badge), Settings. The username sits at the bottom with an account menu (Settings, Log out).
- **Settings** (one column of aligned rows): Dark mode, Time zone, Follow-up rules, Calendar feed, Connect Gmail, Password, Recovery code, Log out.
- **Dashboard:** Overdue / Today / This Week reminders, upcoming interviews, No-reply nudges, and a small count per stage.
```
 Hire Wire     │ Dashboard                                 [+ Add application]
 ─────────     │ ┌ Needs Attention ──────────┐ ┌ Upcoming Interviews ───────┐
 Dashboard     │ │ ● Follow up: Acme  Overdue│ │ Nov 12  2:00 PM  Globex    │
 Applications  │ │ ● Thank-you: Globex Today │ │ Nov 14 10:00 AM  Initech   │
 Board         │ └───────────────────────────┘ └────────────────────────────┘
 Schedule  (3) │ Saved 4 · Applied 12 · Screening 3 · Interview 2 · Offer 1
```
- **Board:** a column per active stage, with closed stages folded into one "Closed" column. Drag a card to another column, which goes through `workflow.move`; a move that isn't allowed snaps back with a message. Without JavaScript, each card has a stage menu. On phones the columns scroll sideways.
- **Look, "calm office":** white cards on soft grey, one deep teal accent, a coloured pill per stage (with text too, never colour alone), the system font, and a matching dark mode.
- Your UI rules apply: Title Case for pages and headings, sentence case for buttons, no decorative emoji, controls of equal height with the main button last on the right, sizes in `rem`, wide-screen font steps.

## Stages (one PR on branch `build-hire-wire`, one commit per stage)

Setup: create `C:\Users\USER\Documents\Workspace\job_application_tracker` by cloning the repo, then make a `.venv`. Save this plan as `docs/PLAN.md`.

1. **Foundation:** skeleton copied from Akda, Alembic, `users`, sign-up with recovery code, login/logout, lock, CSRF, headers, sidebar, Settings (theme, time zone, password, recovery code, log out), CLI.
2. **Companies and Applications:** CRUD for both, the application page with notes and timeline, document links left empty for now.
3. **Status Workflow:** `workflow.py`, `stage_changes`, stage buttons, the Board with drag.
4. **Filtering:** `filters.py`, the Applications table with filters, sorting, paging, saved views.
5. **Interviews and Reminders:** interviews, follow-ups, snooze, automatic follow-ups, No-reply nudge, Dashboard, Schedule, calendar feed.
6. **Contacts, Documents and Stats:** the three extra groups.
7. **Automation:** quick add from link, Connect Gmail, `mail_rules.py`, Email Suggestions.
8. **Demo and Finish:** demo with sample data on every page, phone and wide-screen pass, `render.yaml` (service `hire-wire`, plus `ENCRYPTION_KEY`), a simple A1-level README with screenshots of every feature and a table of tools, `AGENTS.md` + `CLAUDE.md`. Then open the PR (body written with `--body-file`) with step-by-step Neon and Render instructions, and update memory.

## Verification

- **Automated (`pytest`, never online; IMAP and HTTP are faked):**
  - `test_workflow.py`: every stage pair against `TRANSITIONS`, plus history rows and reopening from No reply.
  - `test_filters.py`: each filter alone and combined, bad values, escaped wildcards, sort and paging, saved views.
  - `test_reminders.py`: automatic follow-ups, snooze, overdue/today/this-week boundaries across time zones, the No-reply nudge after 21 days, and calendar feed content and token reset.
  - `test_mail_rules.py`: about 20 sample emails (confirmations, invites with and without `.ics`, rejections, offers, newsletters that must be ignored), company matching, no duplicates.
  - `test_quick_add.py`: JobPosting and `og:` pages, private-address refusal, size limit, blocked site falls back.
  - **Privacy:** user B gets 404 on every one of user A's routes; the encrypted Gmail password never appears in a page.
  - **Login:** lock, recovery code, CSRF, `safe_next()`, honeypot.
  - `test_demo.py`, `test_migrations.py`, `test_readme.py` as in Akda.
- **Real browser (Playwright from `expense_tracker`'s `.venv`):** run on port 5006, then:
  - sign up, quick-add a job from a real posting link, drag it across the board, add an interview, and filter and save a view;
  - connect your own Gmail with an app password and check that the suggestions make sense (you do this part, since it's your inbox);
  - subscribe to the calendar feed in Google Calendar;
  - take screenshots at phone, laptop and ~2200px widths, in light and dark, and check alignment.
- **PostgreSQL:** you run the same tests against an empty Neon branch through `TEST_DATABASE_URL`, as before.
