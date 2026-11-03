"""The data model.

Every row belongs to one user, and every query starts from that user
(ownership.py), so nobody can see anyone else's job hunt.

Moments are naive UTC (dates.utcnow()); days are plain dates.
"""
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .dates import DEFAULT_TIMEZONE, utcnow
from .db import Base


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
