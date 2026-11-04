"""The data model.

    users ─┬─< companies ──< applications ─┬─< notes
           ├─< applications                ├─< stage_changes
           ├─< contacts ──────────────┐    ├─< interviews
           ├─< documents              │    ├─< follow_ups
           └─< saved_views            └──< application_contacts (with a role)

    applications.resume_id / cover_letter_id ──> documents

Every row belongs to one user, and every query starts from that user
(ownership.py), so nobody can see anyone else's job hunt. Deleting a user
deletes everything they own (ON DELETE CASCADE).

Moments are naive UTC (dates.utcnow()); days are plain dates.
"""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dates import DEFAULT_TIMEZONE, utcnow
from .db import Base

# ---------- Stages (workflow.py says which moves between them are allowed) ----------

SAVED = "saved"
APPLIED = "applied"
SCREENING = "screening"
INTERVIEW = "interview"
OFFER = "offer"
ACCEPTED = "accepted"
DECLINED = "declined"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
NO_REPLY = "no_reply"

# The road an application travels, in order.
ACTIVE_STAGES = (SAVED, APPLIED, SCREENING, INTERVIEW, OFFER)
# Where it can end. Accepted and Declined end well; the others end the search.
CLOSED_STAGES = (ACCEPTED, DECLINED, REJECTED, WITHDRAWN, NO_REPLY)
STAGES = ACTIVE_STAGES + CLOSED_STAGES
STAGE_LABELS = {
    SAVED: "Saved", APPLIED: "Applied", SCREENING: "Screening", INTERVIEW: "Interview", OFFER: "Offer",
    ACCEPTED: "Accepted", DECLINED: "Declined", REJECTED: "Rejected", WITHDRAWN: "Withdrawn", NO_REPLY: "No reply",
}

WORK_MODES = {"onsite": "On-site", "hybrid": "Hybrid", "remote": "Remote"}
SOURCES = ("LinkedIn", "JobStreet", "Indeed", "Kalibrr", "OnlineJobs.ph", "Company site", "Referral",
           "Recruiter", "Job fair", "Other")
CURRENCIES = ("PHP", "USD", "SGD", "AUD", "EUR", "GBP", "JPY")


def sql_list(values):
    return ", ".join(f"'{value}'" for value in values)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # There is no email service, so a forgotten password is reset with this
    # one-time code (shown once at sign-up). Only its hash is kept.
    recovery_hash: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default=DEFAULT_TIMEZONE)
    is_demo: Mapped[bool] = mapped_column(default=False)
    # Every "Try Demo" makes its own account, deleted after this moment.
    demo_expires_at: Mapped[datetime | None]
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    # A copy sits in the login cookie. Adding 1 here ends every session at once
    # (after a password change), because old cookies stop matching.
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Reminders (Settings). 0 days means "off".
    follow_up_days: Mapped[int] = mapped_column(default=7)  # a follow-up this many days after applying
    thank_you_notes: Mapped[bool] = mapped_column(default=True)  # a thank-you the day after an interview
    no_reply_days: Mapped[int] = mapped_column(default=21)  # then ask "Mark as No reply?"
    # The secret part of the calendar feed's address (/calendar/<token>.ics). Empty when off.
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True)


class Company(Base):
    __tablename__ = "companies"
    # One "Acme" per person, however it is typed ("ACME ", "acme").
    __table_args__ = (UniqueConstraint("user_id", "name_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    name_key: Mapped[str] = mapped_column(String(120))  # companies.name_key(): small letters, single spaces
    website: Mapped[str] = mapped_column(String(500), default="")
    industry: Mapped[str] = mapped_column(String(80), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    applications: Mapped[list["Application"]] = relationship(back_populates="company")


class Application(Base):
    """One job you applied for (or saved to apply for later)."""
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(f"stage IN ({sql_list(STAGES)})", name="stage_known"),
        CheckConstraint(f"work_mode IN ('', {sql_list(WORK_MODES)})", name="work_mode_known"),
        CheckConstraint("salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max", name="salary_in_order"),
        # The Applications page and the Board always ask "this user's, in these stages".
        Index("ix_applications_user_id_stage", "user_id", "stage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # No cascade: a company with applications can't be deleted (companies.py says so).
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role_title: Mapped[str] = mapped_column(String(150))
    posting_url: Mapped[str] = mapped_column(String(500), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    work_mode: Mapped[str] = mapped_column(String(10), default="")
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    currency: Mapped[str] = mapped_column(String(3), default="PHP")
    source: Mapped[str] = mapped_column(String(40), default="")
    # Only workflow.py changes these two.
    stage: Mapped[str] = mapped_column(String(12), default=SAVED)
    stage_changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    applied_on: Mapped[date | None]
    # A saved copy, because postings disappear once the job is filled.
    job_description: Mapped[str] = mapped_column(Text, default="", deferred=True)
    # "Keep waiting" on the No reply nudge hides it until this day.
    quiet_until: Mapped[date | None]
    # Which version went with this application. Deleting the file keeps the application.
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    cover_letter_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="applications")
    notes: Mapped[list["Note"]] = relationship(back_populates="application", cascade="all, delete-orphan",
                                               passive_deletes=True, order_by="Note.created_at.desc()")
    stage_changes: Mapped[list["StageChange"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True,
        order_by="StageChange.changed_at")
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Interview.starts_at")
    follow_ups: Mapped[list["FollowUp"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True,
        order_by="FollowUp.due_on")
    contact_links: Mapped[list["ApplicationContact"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True)
    resume: Mapped["Document | None"] = relationship(foreign_keys=[resume_id])
    cover_letter: Mapped["Document | None"] = relationship(foreign_keys=[cover_letter_id])

    @property
    def stage_label(self):
        return STAGE_LABELS[self.stage]

    @property
    def is_closed(self):
        return self.stage in CLOSED_STAGES


class Note(Base):
    """Something to remember about an application. Shown on its timeline."""
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    application: Mapped[Application] = relationship(back_populates="notes")


INTERVIEW_KINDS = {
    "phone": "Phone screen", "video": "Video call", "onsite": "On-site", "technical": "Technical",
    "hr": "HR interview", "final": "Final interview",
}
OUTCOMES = {"pending": "Not known yet", "passed": "Passed", "failed": "Not passed", "cancelled": "Cancelled"}


class Interview(Base):
    """One interview round. The stage stays Interview until it moves on."""
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_list(INTERVIEW_KINDS)})", name="kind_known"),
        CheckConstraint(f"outcome IN ({sql_list(OUTCOMES)})", name="outcome_known"),
        CheckConstraint("minutes BETWEEN 5 AND 600", name="minutes_sensible"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(index=True)
    minutes: Mapped[int] = mapped_column(default=60)
    kind: Mapped[str] = mapped_column(String(12), default="video")
    place: Mapped[str] = mapped_column(String(500), default="")  # an address, or a video call link
    with_whom: Mapped[str] = mapped_column(String(200), default="")
    prep_notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    application: Mapped[Application] = relationship(back_populates="interviews")

    @property
    def kind_label(self):
        return INTERVIEW_KINDS[self.kind]

    @property
    def place_is_link(self):
        return self.place.startswith(("https://", "http://"))


AFTER_APPLIED = "after_applied"
THANK_YOU = "thank_you"


class FollowUp(Base):
    """A reminder to do something about an application on a day (reminders.py)."""
    __tablename__ = "follow_ups"
    __table_args__ = (CheckConstraint(f"auto_kind IN ('', '{AFTER_APPLIED}', '{THANK_YOU}')", name="auto_kind_known"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    due_on: Mapped[date] = mapped_column(index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    done_at: Mapped[datetime | None]
    # Made by Hire Wire itself ("" when you made it). Automatic ones go away by
    # themselves when they stop making sense (reminders.on_move).
    auto_kind: Mapped[str] = mapped_column(String(15), default="")
    # A thank-you belongs to its interview: deleting the interview deletes it.
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    application: Mapped[Application] = relationship(back_populates="follow_ups")
    interview: Mapped["Interview | None"] = relationship()


CONTACT_ROLES = {
    "recruiter": "Recruiter", "hiring_manager": "Hiring manager", "interviewer": "Interviewer",
    "referral": "Referral", "other": "Other",
}


class Contact(Base):
    """Someone you talked to: a recruiter, a hiring manager, a friend who referred you."""
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Deleting the company keeps the person.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    job_title: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    profile_url: Mapped[str] = mapped_column(String(500), default="")  # LinkedIn or similar
    notes: Mapped[str] = mapped_column(Text, default="")
    last_contacted_on: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped["Company | None"] = relationship()
    application_links: Mapped[list["ApplicationContact"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", passive_deletes=True)


class ApplicationContact(Base):
    """Many-to-many with a role: this person was the recruiter for that application."""
    __tablename__ = "application_contacts"
    __table_args__ = (CheckConstraint(f"role IN ({sql_list(CONTACT_ROLES)})", name="role_known"),)

    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(15), default="recruiter")

    application: Mapped[Application] = relationship(back_populates="contact_links")
    contact: Mapped[Contact] = relationship(back_populates="application_links")

    @property
    def role_label(self):
        return CONTACT_ROLES[self.role]


DOCUMENT_KINDS = {"resume": "Résumé", "cover_letter": "Cover letter", "other": "Other"}


class Document(Base):
    """A résumé or cover letter version (PDF or Word), kept in the database
    because Render's free disk is wiped on every restart."""
    __tablename__ = "documents"
    __table_args__ = (CheckConstraint(f"kind IN ({sql_list(DOCUMENT_KINDS)})", name="kind_known"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(15), default="resume")
    name: Mapped[str] = mapped_column(String(120))
    version_label: Mapped[str] = mapped_column(String(60), default="")  # "v3, data roles"
    filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)  # deferred: only a download loads it
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def kind_label(self):
        return DOCUMENT_KINDS[self.kind]

    @property
    def title(self):
        return f"{self.name} ({self.version_label})" if self.version_label else self.name


class SavedView(Base):
    """A named set of filters for the Applications page (filters.py), like "Remote"."""
    __tablename__ = "saved_views"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    query: Mapped[str] = mapped_column(String(1000), default="")  # "stage=applied&mode=remote"
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class StageChange(Base):
    """One move from a stage to another (workflow.move). The first row of an
    application has no from_stage. The timeline and the stats come from these."""
    __tablename__ = "stage_changes"
    __table_args__ = (
        CheckConstraint(f"to_stage IN ({sql_list(STAGES)})", name="to_stage_known"),
        CheckConstraint(f"from_stage IS NULL OR from_stage IN ({sql_list(STAGES)})", name="from_stage_known"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(12))
    to_stage: Mapped[str] = mapped_column(String(12))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    note: Mapped[str] = mapped_column(String(500), default="")
    # manual (a button), board (a drag), email (an accepted email suggestion)
    source: Mapped[str] = mapped_column(String(10), default="manual")

    application: Mapped[Application] = relationship(back_populates="stage_changes")
