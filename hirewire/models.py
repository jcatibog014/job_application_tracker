"""The data model.

    users ─┬─< companies ──< applications ──< notes
           └─< applications

Every row belongs to one user, and every query starts from that user
(ownership.py), so nobody can see anyone else's job hunt. Deleting a user
deletes everything they own (ON DELETE CASCADE).

Moments are naive UTC (dates.utcnow()); days are plain dates.
"""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="applications")
    notes: Mapped[list["Note"]] = relationship(back_populates="application", cascade="all, delete-orphan",
                                               passive_deletes=True, order_by="Note.created_at.desc()")

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
