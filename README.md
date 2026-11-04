# Hire Wire

**Hire Wire** is a job application tracker. It keeps every company you applied to, the stage of each application, your interviews and your follow-ups in one calm place.

I made this project to practice three skills: **filtering** (find the right applications fast), **status workflows** (an application moves from stage to stage, with rules) and **reminders** (what to do today, and when).

![The Dashboard](docs/screenshots/dashboard.png)

## The Stages

Every application is in one stage. It moves along this road:

```
Saved → Applied → Screening → Interview → Offer → Accepted
          │           │           │          └──→ Declined
          └───────────┴───────────┴──→ Rejected / Withdrawn / No reply
```

- One table in `hirewire/workflow.py` lists every move that is allowed. A move that is not in the table is refused, on the page and on the Board.
- Every move is saved with its date. The timeline and the stats come from this history.
- You can go back one step to fix a mistake. Rejected, Withdrawn and No reply can go back to where they came from, because sometimes a company answers late.

## What It Can Do

**Applications**
- Add an application with the company, job title, pay, work mode, link and a copy of the job description.
- **Quick add from a link:** paste the job posting's address, and the form fills itself in.
- Move it with stage buttons, or drag it on the **Board**.
- See everything that happened on its **timeline**: stage changes, notes, interviews and follow-ups.

**Filtering**
- Search job titles, companies, notes and descriptions.
- Filter by stage, work mode, source, location, date, pay, "interview coming" and "follow-up due".
- Sort by any column. The filters are in the address, so you can bookmark them.
- **Saved views:** give a set of filters a name. Every account starts with Active, Needs Follow-up and Interviews This Week.

**Reminders**
- Follow-ups with a day. Press **Done**, or **Snooze** for 1 day, 3 days or 1 week.
- Hire Wire adds some by itself: "Follow up on your application" 7 days after you apply, and "Send a thank-you note" the day after an interview. They go away by themselves when they are not needed any more.
- After 21 days with no news, the Dashboard asks: "Mark as No reply?"
- The **Schedule** shows your interviews and follow-ups, day by day.
- **Calendar feed:** a private link for Google Calendar (or Apple, or Outlook). Your interviews and follow-ups go into your phone's calendar, with its alerts.

**Gmail suggestions**
- Connect Gmail with an app password. Hire Wire reads your recent job emails, like "Thank you for applying", "Interview invitation" or "Unfortunately...".
- It **suggests** a change, for example "Add an interview on Nov 12 and move it to Interview". Nothing changes until you press **Accept**.
- It only reads. Your emails stay unread, and Hire Wire keeps only a short part of each one.

**More**
- **Contacts:** recruiters, hiring managers and the friends who referred you, linked to applications.
- **Documents:** your résumé and cover letter versions (PDF or Word). See which version went with each application.
- **Stats:** response rate, how far applications got, applications per week, and the best places to find jobs.

**Accounts and safety**
- Anyone can sign up. Each tracker is private: nobody can see another person's applications.
- There is no email for passwords, so sign-up shows a **recovery code**. Save it. It lets you set a new password.
- Passwords are saved only as hashes. After 5 wrong tries, the account waits 15 minutes.
- Gmail app passwords are saved encrypted.
- **Try Demo** on the login page makes a sample account with an example on every page. It is yours alone, and it is deleted after 2 hours.

## Can It Connect to LinkedIn?

Not directly. LinkedIn lets only approved partner companies use its data, and copying its pages is against its rules. Here is what Hire Wire does instead:

| Way | How it works |
|---|---|
| Type it in | The form takes less than a minute. |
| Quick add from a link | Paste the posting's address. Most job sites work. LinkedIn often hides postings from apps, so for LinkedIn you may need to type. |
| Gmail suggestions | LinkedIn, JobStreet and company emails ("Your application was sent to...") become suggestions. |
| Calendar feed | Your interviews go into your phone's calendar. |

## Pictures

**Applications**

| | |
|---|---|
| ![The Applications page](docs/screenshots/applications.png) Applications | ![The filters, open](docs/screenshots/filters.png) Filters |
| ![The Board](docs/screenshots/board.png) The Board | ![Quick add from a link](docs/screenshots/quick-add.png) Quick add from a link |
| ![An application's page](docs/screenshots/application.png) An application | ![The timeline, people and details](docs/screenshots/timeline.png) Timeline and people |

**Reminders and email**

| | |
|---|---|
| ![The Schedule](docs/screenshots/schedule.png) Schedule | ![The Snooze menu, open](docs/screenshots/snooze.png) Snooze |
| ![Email suggestions](docs/screenshots/email-suggestions.png) Email suggestions | ![Settings: reminders, calendar feed and Gmail](docs/screenshots/settings.png) Settings |

**More pages**

| | |
|---|---|
| ![Stats](docs/screenshots/stats.png) Stats | ![Stats in dark mode](docs/screenshots/stats-dark.png) Stats, in dark mode |
| ![Contacts](docs/screenshots/contacts.png) Contacts | ![Documents](docs/screenshots/documents.png) Documents |
| ![Companies](docs/screenshots/companies.png) Companies | ![The Dashboard in dark mode](docs/screenshots/dashboard-dark.png) Dark mode |

**Accounts and phones**

| | |
|---|---|
| ![The login page](docs/screenshots/login.png) Log in | ![The sign-up page](docs/screenshots/signup.png) Sign up |
| ![The Dashboard on a phone](docs/screenshots/phone.png) On a phone | ![The menu on a phone](docs/screenshots/phone-menu.png) The menu on a phone |

All companies, people and emails in these pictures are made up. They come from Try Demo.

## Tools

| Tool | What it is | What it does here |
|---|---|---|
| Python 3.13 | Language | The whole server |
| Flask | Web framework | Pages and forms |
| SQLAlchemy | Database library | The tables, as Python classes, and the filter queries |
| Alembic | Migration tool | Changes the tables and keeps the data |
| SQLite | Database | Saves data on my computer and in tests |
| PostgreSQL (Neon) | Database | Saves data on the live site |
| imaplib, email | Python's own libraries | Read Gmail |
| icalendar | Library | Makes the calendar feed, and reads invites in emails |
| cryptography | Library | Encrypts Gmail app passwords |
| requests, Beautiful Soup | Libraries | Read job pages for Quick add |
| pytest | Test tool | Checks that everything works, without going online |
| Playwright | Browser tool | Takes the pictures for this page |
| Render | Hosting platform | Runs the live site |
| Plus Jakarta Sans | Font | Headings and the name. The two small files are inside the app. |
| HTML, CSS, JavaScript, SVG | Languages | The pages and the charts. They also work without JavaScript. |

## Run It on Your Computer

You need Python 3.13. Use these commands in PowerShell, in this folder.

1. Make the virtual environment and install the tools:

   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

2. Make the tables:

   ```
   .venv\Scripts\flask --app hirewire upgrade-db
   ```

3. Start the site, then open http://127.0.0.1:5006 and sign up (or press Try Demo):

   ```
   .venv\Scripts\flask --app hirewire run --debug --port 5006
   ```

Run the tests with:

```
.venv\Scripts\python -m pytest
```

## Put It Online

The site uses Render (it runs the program) and Neon (it keeps the data). Both have a free plan.

1. **Neon:** make a project in the Singapore region. Copy the connection string. It starts with `postgresql://`.
2. **Render:** choose **New**, then **Blueprint**, then pick this repository. Render reads `render.yaml`. When it asks for `DATABASE_URL`, paste the Neon string. Render makes `SECRET_KEY` and `ENCRYPTION_KEY` by itself.
3. Open the site and sign up.

On the free plan, the site sleeps after 15 quiet minutes. The next visit wakes it up, and this takes about 30 to 50 seconds.

If the live site can't reach Gmail, you can check your Gmail from your computer instead. Use your own Neon string, and keep it secret:

```
$env:DATABASE_URL = "postgresql://..."
$env:ENCRYPTION_KEY = "the same value as on Render"
.venv\Scripts\flask --app hirewire scan-email yourname
Remove-Item Env:DATABASE_URL, Env:ENCRYPTION_KEY
```

## Forgot Your Password?

Use the recovery code you saved when you signed up: press **Forgot your password?** on the login page. You get a new code after that.

If you lost the code too, the person who runs the site can set a new password:

```
.venv\Scripts\flask --app hirewire set-password yourname
```
