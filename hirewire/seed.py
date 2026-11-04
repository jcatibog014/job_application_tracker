"""The demo's sample job hunt: an example on every page the demo can open.

Every "Try Demo" gets its own fresh account (auth.py), filled in here with
made-up companies and people, dated around today, so the Dashboard, the
Schedule and the Stats always look alive. The sample emails go through the
real mail_rules.py, so the Email Suggestions page shows how it really works.
"""
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

from . import calendar_feed, companies, reminders, suggestions, workflow
from .dates import local_today, to_utc
from .models import (
    Application, ApplicationContact, Contact, Document, EmailSuggestion, FollowUp, Interview, Note, SavedView,
)

# (company, website, industry, location)
COMPANIES = {
    "Bluewave Bank": ("https://bluewave-bank.example", "Banking", "Taguig City"),
    "Northstar BPO": ("https://northstar-bpo.example", "Outsourcing", "Cebu City"),
    "Pacific Data Co": ("https://pacificdata.example", "Analytics", "Makati City"),
    "Kalye Foods": ("https://kalyefoods.example", "Food and drinks", "Pasig City"),
    "Lakbay Travel": ("https://lakbay-travel.example", "Travel", "Quezon City"),
    "Tala Health": ("https://tala-health.example", "Healthcare", "Mandaluyong City"),
    "Sinag Solar": ("https://sinagsolar.example", "Energy", "Taguig City"),
    "Ulap Cloud": ("https://ulapcloud.example", "Software", "Remote"),
    "Mabuhay Insurance": ("https://mabuhay-insurance.example", "Insurance", "Makati City"),
    "Daloy Fintech": ("https://daloy.example", "Finance technology", "Pasig City"),
    "Habi Textiles": ("https://habitextiles.example", "Manufacturing", "Marikina City"),
    "Bayanihan Retail": ("https://bayanihan-retail.example", "Retail", "Quezon City"),
    "Tanglaw Schools": ("https://tanglaw.example", "Education", "Manila"),
    "Acme Logistics": ("https://acme-logistics.example", "Logistics", "Parañaque City"),
    "Initech": ("https://initech.example", "Software", "Remote"),
}

DESCRIPTION = """About the role
You will turn data into clear reports for the operations team.

What you will do
- Build weekly dashboards in Power BI
- Write SQL to clean and join data
- Explain what the numbers mean to managers

What we are looking for
- 1 to 3 years with SQL and Excel
- Clear writing in English and Filipino
"""

# Each job: company, title, steps [(stage, days from today, note)], and its details.
JOBS = [
    ("Bluewave Bank", "Business Analyst",
     [("applied", -26, ""), ("screening", -20, "Liza called. Nice first chat."), ("interview", -12, ""),
      ("offer", -3, "Offer by email: PHP 68,000 a month.")],
     dict(work_mode="hybrid", salary_min=55000, salary_max=70000, source="LinkedIn")),
    ("Northstar BPO", "Reporting Specialist",
     [("applied", -18, ""), ("screening", -14, ""), ("interview", -6, "")],
     dict(work_mode="remote", salary_min=45000, salary_max=50000, source="Referral")),
    ("Pacific Data Co", "Junior Data Analyst",
     [("applied", -9, ""), ("interview", -2, "They skipped the phone screen.")],
     dict(work_mode="hybrid", salary_min=40000, salary_max=55000, source="JobStreet")),
    ("Kalye Foods", "Data Associate",
     [("applied", -30, ""), ("rejected", -15, "A short, polite email.")],
     dict(work_mode="onsite", salary_min=30000, salary_max=35000, source="Indeed")),
    ("Lakbay Travel", "Operations Analyst",
     [("applied", -25, "")],
     dict(work_mode="onsite", salary_min=35000, salary_max=42000, source="JobStreet")),
    ("Tala Health", "Data Analyst",
     [("applied", -4, "")],
     dict(work_mode="hybrid", salary_min=50000, salary_max=60000, source="Company site")),
    ("Sinag Solar", "Business Intelligence Analyst",
     [("saved", -3, "")],
     dict(work_mode="onsite", salary_min=60000, salary_max=75000, source="LinkedIn")),
    ("Ulap Cloud", "Product Analyst",
     [("saved", -1, "")],
     dict(work_mode="remote", source="Kalibrr")),
    ("Mabuhay Insurance", "Junior Actuarial Analyst",
     [("applied", -40, ""), ("screening", -35, ""), ("no_reply", -10, "No news after the screening call.")],
     dict(work_mode="onsite", salary_min=38000, salary_max=45000, source="Job fair")),
    ("Daloy Fintech", "Data Analyst",
     [("applied", -35, ""), ("interview", -28, ""), ("rejected", -20, "They wanted more Python.")],
     dict(work_mode="hybrid", salary_min=55000, salary_max=65000, source="LinkedIn")),
    ("Habi Textiles", "Inventory Analyst",
     [("applied", -33, ""), ("withdrawn", -27, "Too far to travel every day.")],
     dict(work_mode="onsite", salary_min=28000, salary_max=32000, source="Indeed")),
    ("Bayanihan Retail", "Sales Analyst",
     [("applied", -14, ""), ("screening", -7, "They sent a small case study.")],
     dict(work_mode="hybrid", salary_min=42000, salary_max=48000, source="JobStreet")),
    ("Tanglaw Schools", "Data Coordinator",
     [("applied", -21, ""), ("screening", -16, ""), ("interview", -10, ""), ("offer", -6, ""),
      ("declined", -2, "Chose to wait for Bluewave.")],
     dict(work_mode="onsite", salary_min=32000, salary_max=36000, source="Company site")),
    ("Acme Logistics", "Supply Chain Analyst",
     [("applied", -11, "")],
     dict(work_mode="onsite", salary_min=36000, salary_max=40000, source="LinkedIn")),
    ("Initech", "Freelance Report Developer",
     [("applied", -45, ""), ("interview", -38, ""), ("offer", -30, ""), ("accepted", -28, "A 3-month project.")],
     dict(work_mode="remote", salary_min=25000, salary_max=25000, source="OnlineJobs.ph")),
]


def sample_pdf(title, lines):
    """A tiny real PDF with a few lines of text, so the demo's files open."""
    text = "\n".join(f"({line.replace('(', '[').replace(')', ']')}) Tj T*" for line in [title, ""] + lines)
    stream = f"BT /F1 12 Tf 16 TL 72 720 Td {text} ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    table = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    return out


def email_raw(number, subject, body, sender, sent_at):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, "demo@hirewire.example", subject
    message["Date"] = format_datetime(sent_at.replace(tzinfo=UTC))
    message["Message-ID"] = f"<demo-{number}@hirewire.example>"
    message.set_content(body)
    return message.as_bytes()


def sample_emails(moment, tz_name="Asia/Manila"):
    """Raw sample emails, as if they had just arrived. Their ids never change,
    so "Check email now" in the demo finds nothing new the second time."""
    day = local_today(tz_name, moment) + timedelta(days=5)
    when = f"{day:%A}, {day:%B} {day.day}, {day.year} at 9:00 AM"
    return [
        email_raw(1, "Interview invitation: Data Analyst",
                  f"Hi! Thank you for applying. We would like to invite you to an interview on {when} "
                  "by video call. Please reply to confirm.", "Tala Health Careers <careers@tala-health.example>",
                  moment - timedelta(hours=2)),
        email_raw(2, "Thank you for applying to Ulap Cloud",
                  "We have received your application for the Product Analyst position. We will get back to you "
                  "within two weeks.", "Ulap Cloud Careers <jobs@ulapcloud.example>", moment - timedelta(hours=20)),
        email_raw(3, "Update on your application",
                  "Thank you for your interest in Lakbay Travel. Unfortunately, we have decided to move forward "
                  "with other candidates for the Operations Analyst role.",
                  "Lakbay Travel Recruitment <hr@lakbay-travel.example>", moment - timedelta(days=1, hours=3)),
        email_raw(4, "Your application was sent to Sari Analytics",
                  "Your application for Junior BI Developer was sent to Sari Analytics.",
                  "LinkedIn <jobs-noreply@linkedin.com>", moment - timedelta(days=2)),
    ]


def fill(s, user, moment):
    """Put the sample job hunt into a fresh demo account. The caller commits."""
    today = local_today(user.timezone, moment)

    def at(days, hour=10, minute=0):
        local = datetime(today.year, today.month, today.day, hour, minute) + timedelta(days=days)
        return to_utc(local, user.timezone)

    for name, (website, industry, location) in COMPANIES.items():
        company = companies.find_or_add(s, user.id, name)
        company.website, company.industry, company.location = website, industry, location

    files = {
        "cv3": Document(user_id=user.id, kind="resume", name="Résumé", version_label="v3, data roles",
                        filename="resume-v3.pdf", mime="application/pdf",
                        data=sample_pdf("Juana Dela Cruz - Data Analyst", ["SQL, Power BI, Excel", "Sample file"])),
        "cv2": Document(user_id=user.id, kind="resume", name="Résumé", version_label="v2", filename="resume-v2.pdf",
                        mime="application/pdf", data=sample_pdf("Juana Dela Cruz", ["Older version", "Sample file"])),
        "letter": Document(user_id=user.id, kind="cover_letter", name="Cover letter", version_label="Bluewave Bank",
                           filename="cover-letter-bluewave.pdf", mime="application/pdf",
                           data=sample_pdf("Cover letter", ["Dear Hiring Team,", "Sample file"])),
        "portfolio": Document(user_id=user.id, kind="other", name="Portfolio", version_label="Dashboards",
                              filename="portfolio.pdf", mime="application/pdf",
                              data=sample_pdf("Portfolio", ["Three dashboards", "Sample file"])),
    }
    for document in files.values():
        document.size = len(document.data)
        s.add(document)
    s.flush()

    jobs = {}
    for company, title, steps, details in JOBS:
        first_stage, first_day, _ = steps[0]
        start = at(first_day, 9)
        sent = first_stage != "saved"
        # The older applications went out with the older résumé.
        resume = None if not sent else files["cv2"] if first_day <= -32 else files["cv3"]
        job = Application(user_id=user.id, role_title=title, created_at=start, updated_at=start,
                          location=COMPANIES[company][2], job_description=DESCRIPTION,
                          posting_url=f"{COMPANIES[company][0]}/careers/{len(jobs) + 101}",
                          applied_on=today + timedelta(days=first_day) if sent else None,
                          resume_id=resume.id if resume else None, **details)
        job.company = companies.find_or_add(s, user.id, company)
        s.add(job)
        workflow.start(s, job, first_stage, start)  # without the user: the demo's reminders are set below
        for stage, day, note in steps[1:]:
            s.flush()
            workflow.move(s, job, stage, user, at(day, 15), note=note)
        jobs[company] = job
    s.flush()
    jobs["Bluewave Bank"].cover_letter_id = files["letter"].id

    # Interviews: past ones with how they went, and two coming up.
    def interview(company, days, hour, kind, outcome="pending", **fields):
        row = Interview(application=jobs[company], starts_at=at(days, hour), kind=kind, outcome=outcome,
                        created_at=at(min(days, 0) - 2), **fields)
        s.add(row)
        return row

    interview("Bluewave Bank", -12, 10, "video", "passed", with_whom="Liza Reyes",
              place="https://meet.example.com/bluewave")
    interview("Bluewave Bank", -8, 14, "final", "passed", with_whom="Mr. Santos, Head of Strategy",
              place="Bluewave Tower, 5th Avenue, Taguig")
    interview("Northstar BPO", -6, 11, "phone", "passed", with_whom="Marco Tan")
    final = interview("Northstar BPO", 2, 10, "onsite", with_whom="Marco Tan and the analytics team",
                      place="Northstar Building, Cebu IT Park",
                      prep_notes="Bring the printed portfolio.\nPrepare a 5-minute talk on the call-volume dashboard.")
    soon = interview("Pacific Data Co", 1, 14, "video", with_whom="Ana Lim, Analytics Lead",
                     place="https://meet.example.com/pacific-data", minutes=45,
                     prep_notes="Ask about the team size and tools (Power BI?).\nShow the sales dashboard story.")
    interview("Daloy Fintech", -28, 15, "technical", "failed", with_whom="Two senior engineers")
    interview("Tanglaw Schools", -10, 9, "hr", "passed", with_whom="Ms. Garcia")
    interview("Initech", -38, 16, "video", "passed", with_whom="Bill L.")
    s.flush()
    for row in (final, soon):
        reminders.after_interview_saved(s, row, user, moment)

    # Follow-ups: one overdue, one today, some this week, one done.
    def follow_up(company, days, note, **fields):
        s.add(FollowUp(application=jobs[company], due_on=today + timedelta(days=days), note=note,
                       created_at=moment - timedelta(days=1), **fields))

    follow_up("Lakbay Travel", -18, "Follow up on your application", auto_kind="after_applied")
    follow_up("Bayanihan Retail", 0, "Send the case study")
    follow_up("Tala Health", 3, "Follow up on your application", auto_kind="after_applied")
    follow_up("Sinag Solar", 2, "Apply before the posting closes on Friday")
    follow_up("Bluewave Bank", 4, "Answer the offer (ask about the HMO)")
    follow_up("Northstar BPO", 1, "Print the portfolio")
    follow_up("Acme Logistics", -4, "Follow up on your application", auto_kind="after_applied",
              done_at=moment - timedelta(days=2))
    follow_up("Kalye Foods", -14, "Thank Jose for his time", done_at=moment - timedelta(days=14))

    # Notes for the timelines.
    for company, days, body in [
        ("Bluewave Bank", -2, "Offer details: PHP 68,000 a month, HMO from day one, 2 days a week in the office."),
        ("Pacific Data Co", -1, "Read their blog post about moving to Power BI."),
        ("Northstar BPO", -5, "Nena says the analytics team is small and friendly."),
        ("Lakbay Travel", -12, "Sent a polite follow-up email. No answer yet."),
    ]:
        s.add(Note(application=jobs[company], body=body, created_at=at(days, 18)))

    # People, and who they were in which application.
    people = {
        "liza": Contact(user_id=user.id, company_id=jobs["Bluewave Bank"].company_id, name="Liza Reyes",
                        job_title="Talent acquisition lead", email="liza.reyes@bluewave-bank.example",
                        phone="+63 917 555 0101", profile_url="https://www.linkedin.com/in/example-liza",
                        notes="Very kind. Prefers email.", last_contacted_on=today - timedelta(days=3)),
        "marco": Contact(user_id=user.id, company_id=jobs["Northstar BPO"].company_id, name="Marco Tan",
                         job_title="Head of analytics", email="marco.tan@northstar-bpo.example",
                         last_contacted_on=today - timedelta(days=6)),
        "nena": Contact(user_id=user.id, name="Nena Cruz", job_title="Data engineer (a friend)",
                        phone="+63 918 555 0123", notes="Referred me to Northstar. Treat her to coffee!",
                        last_contacted_on=today - timedelta(days=5)),
        "ana": Contact(user_id=user.id, company_id=jobs["Pacific Data Co"].company_id, name="Ana Lim",
                       job_title="Analytics lead", email="ana.lim@pacificdata.example"),
        "jose": Contact(user_id=user.id, company_id=jobs["Kalye Foods"].company_id, name="Jose Ramos",
                        job_title="HR officer", email="jose.ramos@kalyefoods.example",
                        last_contacted_on=today - timedelta(days=15)),
    }
    s.add_all(people.values())
    s.flush()
    for company, person, role in [("Bluewave Bank", "liza", "recruiter"), ("Northstar BPO", "marco", "hiring_manager"),
                                  ("Northstar BPO", "nena", "referral"), ("Pacific Data Co", "ana", "interviewer"),
                                  ("Kalye Foods", "jose", "recruiter")]:
        s.add(ApplicationContact(application=jobs[company], contact=people[person], role=role))

    # One more saved view, besides the starter ones every account gets.
    s.add(SavedView(user_id=user.id, name="Remote", query="mode=remote"))

    # Email suggestions: the sample inbox through the real rules, plus two already handled.
    s.flush()
    suggestions.add_from_raw(s, user, sample_emails(moment, user.timezone), moment)
    s.add_all([
        EmailSuggestion(user_id=user.id, message_id="<demo-old-1@hirewire.example>", kind="applied",
                        sender="Tala Health Careers <careers@tala-health.example>",
                        subject="Thank you for applying to Tala Health",
                        snippet="We have received your application for the Data Analyst position.",
                        received_at=at(-4, 9), company_guess="Tala Health", role_guess="Data Analyst",
                        application_id=jobs["Tala Health"].id, status="accepted"),
        EmailSuggestion(user_id=user.id, message_id="<demo-old-2@hirewire.example>", kind="applied",
                        sender="Habi Textiles <jobs@habitextiles.example>", subject="Thank you for your application",
                        snippet="Thank you for your application. Our team will review it soon.",
                        received_at=at(-32, 9), company_guess="Habi Textiles", status="ignored"),
    ])

    # The calendar link, so Settings shows what it looks like.
    user.calendar_token = calendar_feed.new_token()
