"""Reading Gmail with an app password, over IMAP, without changing anything.

Why IMAP and an app password, not "Sign in with Google": Google lets an app
read Gmail through its API only after a long security review. An app
password (made in your Google account, after turning on 2-Step
Verification) works with Python's own imaplib straight away.

Only reading: the inbox is opened read-only and messages are fetched with
BODY.PEEK, so nothing is marked as read. Gmail's own search picks likely
emails from the last 30 days, and at most 200 of them are looked at.
"""
import email
import hashlib
import imaplib
import re
import socket
from datetime import UTC
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from .mail_rules import Email

HOST = "imap.gmail.com"
PORT = 993
TIMEOUT = 20
LIMIT = 200
MAX_SIZE = 1_500_000  # bigger ones are attachments, not news about a job
# Gmail search words (X-GM-RAW). {a b} means a OR b.
SEARCH = '"newer_than:30d {application applying applied interview candidacy offer position role}"'
APP_PASSWORD = re.compile(r"[a-z]{16}")


class GmailProblem(Exception):
    """Why Gmail couldn't be read, in words for the person."""


def clean_app_password(text):
    """Google shows it as "abcd efgh ijkl mnop"; it works without the spaces."""
    return re.sub(r"\s+", "", text or "").lower()


def open_box(address, password, imap_class=None):
    # Looked up now, not when Python read this file, so tests can put a fake in its place.
    imap_class = imap_class or imaplib.IMAP4_SSL
    try:
        box = imap_class(HOST, PORT, timeout=TIMEOUT)
    except (OSError, socket.timeout):
        raise GmailProblem("Gmail couldn't be reached. Please try again later.") from None
    try:
        box.login(address, password)
    except imaplib.IMAP4.error:
        box.logout()
        raise GmailProblem("Gmail didn't accept that address and app password. Check both, and that "
                           "2-Step Verification is on.") from None
    return box


def check_login(address, password, imap_class=None):
    open_box(address, password, imap_class).logout()


def fetch_recent(address, password, imap_class=None, limit=LIMIT):
    """The raw bytes of recent, likely job emails, newest last."""
    box = open_box(address, password, imap_class)
    try:
        box.select("INBOX", readonly=True)
        status, data = box.uid("SEARCH", "X-GM-RAW", SEARCH)
        if status != "OK":
            raise GmailProblem("Gmail couldn't search the inbox.")
        uids = (data[0] or b"").split()[-limit:]
        if not uids:
            return []
        # Sizes first, so a 20 MB attachment is never downloaded.
        status, data = box.uid("FETCH", b",".join(uids).decode(), "(RFC822.SIZE)")
        small = []
        for line in data:
            text = line.decode() if isinstance(line, bytes) else ""
            uid, size = re.search(r"UID (\d+)", text), re.search(r"RFC822\.SIZE (\d+)", text)
            if uid and size and int(size.group(1)) <= MAX_SIZE:
                small.append(uid.group(1))
        messages = []
        for start in range(0, len(small), 20):
            status, data = box.uid("FETCH", ",".join(small[start:start + 20]), "(BODY.PEEK[])")
            messages += [part[1] for part in data if isinstance(part, tuple) and len(part) == 2]
        return messages
    except (imaplib.IMAP4.error, OSError):
        raise GmailProblem("Gmail stopped answering while we read the inbox. Please try again.") from None
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def parse_message(raw):
    """Raw email bytes -> an Email (only what the rules need)."""
    message = email.message_from_bytes(raw, policy=policy.default)
    name, address = parseaddr(str(message.get("From", "")))
    try:
        received = parsedate_to_datetime(str(message.get("Date"))).astimezone(UTC).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        received = None
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            text = body.get_content()
        except (LookupError, UnicodeDecodeError):
            text = ""
        if body.get_content_type() == "text/html":
            text = BeautifulSoup(text, "html.parser").get_text("\n")
    calendar = None
    for part in message.walk():
        if part.get_content_type() == "text/calendar" or (part.get_filename() or "").lower().endswith(".ics"):
            calendar = part.get_payload(decode=True)
            break
    # The same email must get the same id every time, or it would be suggested again.
    message_id = str(message.get("Message-ID", "")).strip() or f"<no-id-{hashlib.sha256(raw).hexdigest()[:32]}>"
    return Email(message_id=message_id[:300], sender_name=name, sender_address=address.lower(),
                 subject=str(message.get("Subject", "")).strip(), text=text, received_at=received, calendar=calendar)
