"""Reading job emails: what kind they are, which company, which job, and when.

Plain rules, no AI: lists of phrases, checked in an order that avoids the
usual traps. "Thank you for applying ... if you are selected for an
interview" is a confirmation, not an interview; "Unfortunately ..." is a
rejection unless the email clearly sets up an interview.

Everything here is a plain function of an Email, so the tests feed it
sample emails. The result is only ever a SUGGESTION: the person accepts it.
"""
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from icalendar import Calendar

from .dates import to_utc

APPLIED = "applied"
INTERVIEW = "interview"
REJECTION = "rejection"
OFFER = "offer"

IGNORE_IN_SUBJECT = ("job alert", "jobs for you", "recommended for you", "recommended jobs", "new jobs",
                     "jobs you may", "similar jobs", "newsletter", "webinar", "is hiring", "jobs matching")
OFFER_PHRASES = ("pleased to offer", "offer of employment", "job offer", "offer letter", "extend an offer",
                 "extend you an offer", "employment offer")
# Strong signs of a "no". "Unfortunately" alone is weaker: checked after interviews.
REJECTION_PHRASES = ("not moving forward", "not be moving forward", "decided to move forward with other",
                     "move forward with other candidates", "decided to proceed with other", "regret to inform",
                     "not been selected", "were not selected", "position has been filled", "pursue other candidates",
                     "other candidates whose", "no longer under consideration", "not to proceed with your application")
WEAK_REJECTION_PHRASES = ("unfortunately",)
INTERVIEW_PHRASES = ("invite you to an interview", "invite you to interview", "invitation to interview",
                     "interview invitation", "schedule an interview", "schedule your interview", "schedule a call",
                     "book a time", "would like to interview", "like to invite you", "your interview is",
                     "interview has been scheduled", "interview is scheduled", "phone screen",
                     "availability for an interview", "availability for a call", "initial interview",
                     "technical interview", "final interview")
APPLIED_PHRASES = ("thank you for applying", "thanks for applying", "application received", "received your application",
                   "application has been received", "application was sent", "application has been submitted",
                   "thank you for your application", "we have received your application", "successfully applied")

# Senders that send for many companies: their name and address say nothing about which one.
SHARED_DOMAINS = {
    "gmail", "googlemail", "yahoo", "outlook", "hotmail", "icloud", "greenhouse", "greenhouse-mail", "lever",
    "hire", "workday", "myworkday", "myworkdayjobs", "smartrecruiters", "icims", "ashbyhq", "workable",
    "workablemail", "linkedin", "jobstreet", "indeed", "indeedemail", "kalibrr", "bamboohr", "recruitee",
    "teamtailor", "jobvite", "taleo", "successfactors", "mail", "email", "notifications", "breezy", "jazzhr",
}
TEAM_WORDS = re.compile(r"\b(careers?|recruit(ing|ment|er)?|talent( acquisition)?|hiring( team)?|human resources|"
                        r"hr|jobs|team|people( team)?|no-?reply|via \w+)\b", re.IGNORECASE)
COMPANY_IN_SUBJECT = [
    re.compile(r"application (?:was )?sent to (?P<c>.+)$", re.IGNORECASE),
    re.compile(r"(?:applying|applied|application|interest) (?:to|at|with|in joining) (?P<c>.+?)(?: for | - |[!.|:]|$)",
               re.IGNORECASE),
    re.compile(r"interview (?:with|at|invitation from) (?P<c>.+?)(?: for | - |[!.|:]|$)", re.IGNORECASE),
    re.compile(r"(?:offer|update|news) from (?P<c>.+?)(?: for | - |[!.|:]|$)", re.IGNORECASE),
    re.compile(r"\bat (?P<c>[A-Z][\w&.' -]+?)(?: - |[!.|:]|$)"),
]
ROLE_IN_TEXT = [
    re.compile(r"\bfor (?:the |our )?(?P<r>[\w ,&/+-]+?) (?:position|role|opening|job)\b", re.IGNORECASE),
    re.compile(r"(?:position|role) of (?P<r>[\w ,&/+-]+?)(?: at | (?:was|has|is|with)\b|[.,!]|$)", re.IGNORECASE),
    re.compile(r"application for (?:the )?(?P<r>[\w ,&/+-]+?)(?: at | - | (?:was|has|is|with)\b|[.,!]|$)", re.IGNORECASE),
]
COMPANY_SUFFIXES = re.compile(r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|co|company|philippines|ph|group|"
                              r"holdings|plc|gmbh|pte)\b\.?", re.IGNORECASE)

MONTHS = {name: number for number, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for name in names}
MONTH = r"(?P<month>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
TIME = r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
DATE_PATTERNS = [
    # Thursday, November 12, 2026 at 2:30 PM / Nov 12 at 2pm
    re.compile(MONTH + r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?(?:,?\s*(?:at|@|from)?\s*)" + TIME,
               re.IGNORECASE),
    # 12 November 2026, 14:30 / 12 Nov at 2:30 PM
    re.compile(r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH + r"(?:\s+(?P<year>\d{4}))?(?:,?\s*(?:at|@|from)?\s*)"
               + TIME, re.IGNORECASE),
    # 2026-11-12 14:30
    re.compile(r"(?P<year>\d{4})-(?P<monthnum>\d{2})-(?P<day>\d{2})[ T](?P<hour>\d{2}):(?P<minute>\d{2})"),
]


@dataclass
class Email:
    message_id: str
    sender_name: str
    sender_address: str
    subject: str
    text: str
    received_at: datetime  # naive UTC
    calendar: bytes | None = None  # an attached .ics invite, if any

    @property
    def sender_domain(self):
        return self.sender_address.rsplit("@", 1)[-1].lower() if "@" in self.sender_address else ""


@dataclass
class Finding:
    kind: str
    company: str
    role: str
    when: datetime | None  # an interview's time, naive UTC


def has_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def calendar_event(email):
    """The first event in an attached invite, or None."""
    if not email.calendar:
        return None
    try:
        return next(iter(Calendar.from_ical(email.calendar).walk("VEVENT")), None)
    except (ValueError, KeyError, IndexError):
        return None


def classify(email):
    """APPLIED, INTERVIEW, REJECTION, OFFER, or None (not about an application)."""
    subject = email.subject.lower()
    text = f"{subject}\n{email.text.lower()}"
    if has_any(subject, IGNORE_IN_SUBJECT):
        return None
    if has_any(text, OFFER_PHRASES):
        return OFFER
    if has_any(text, REJECTION_PHRASES):
        return REJECTION
    event = calendar_event(email)
    invite = event is not None and "interview" in str(event.get("summary", "")).lower()
    if invite or "interview" in subject and not has_any(subject, ("if selected", "next steps")) \
            or has_any(text, INTERVIEW_PHRASES):
        return INTERVIEW
    if has_any(text, WEAK_REJECTION_PHRASES):
        return REJECTION
    if has_any(text, APPLIED_PHRASES):
        return APPLIED
    return None


def tidy(name):
    name = re.sub(r"\s+", " ", name).strip(" .,!:;-|\"'")
    return name[:120]


def company_from(email):
    """The company's name, from the subject, the sender's name or their address."""
    for pattern in COMPANY_IN_SUBJECT:
        match = pattern.search(email.subject)
        if match and tidy(match.group("c")):
            return tidy(match.group("c"))
    if TEAM_WORDS.search(email.sender_name):  # "Acme Careers", "Talent at Acme"
        name = tidy(re.sub(r"\b(at|from|the)\b", " ", TEAM_WORDS.sub(" ", email.sender_name), flags=re.IGNORECASE))
        if name:
            return name
    parts = email.sender_domain.split(".")
    if len(parts) >= 2:
        main = parts[-3] if len(parts) >= 3 and parts[-2] in ("com", "co", "org", "net") else parts[-2]
        if main not in SHARED_DOMAINS:
            return main.replace("-", " ").title()
    return ""


def role_from(email):
    for pattern in ROLE_IN_TEXT:
        for source in (email.subject, email.text[:2000]):
            match = pattern.search(source)
            if match:
                role = tidy(match.group("r"))
                small_word = role.lower() in ("the", "a", "an", "this", "your", "our", "that")
                if 2 < len(role) <= 80 and not small_word and not role.lower().startswith(("a ", "an ", "this ", "your ")):
                    return role[:150]
    return ""


def company_key(name):
    """What makes two company names the same: "Acme Philippines, Inc." matches "ACME"."""
    name = COMPANY_SUFFIXES.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def interview_time(email, tz_name):
    """When the interview is, as naive UTC: from an attached invite first, then the words."""
    event = calendar_event(email)
    if event is not None and event.get("dtstart") is not None:
        start = event.decoded("dtstart")
        if isinstance(start, datetime):
            if start.tzinfo is not None:
                return start.astimezone(UTC).replace(tzinfo=None)
            return to_utc(start, tz_name)  # no time zone in the invite: the person's own clock
    for pattern in DATE_PATTERNS:
        match = pattern.search(email.text) or pattern.search(email.subject)
        if not match:
            continue
        found = match.groupdict()
        month = int(found["monthnum"]) if found.get("monthnum") else MONTHS[found["month"].lower().rstrip(".")]
        hour, minute = int(found["hour"]), int(found.get("minute") or 0)
        ampm = (found.get("ampm") or "").lower().replace(".", "")
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            continue
        received = email.received_at.date()
        year = int(found["year"]) if found.get("year") else received.year
        try:
            local = datetime(year, month, int(found["day"]), hour, minute)
        except ValueError:
            continue
        if not found.get("year") and local.date() < received - timedelta(days=1):
            local = local.replace(year=year + 1)  # "Jan 5" in a December email means next year
        return to_utc(local, tz_name)
    return None


def read_email(email, tz_name):
    """An Email -> a Finding, or None if it isn't about a job application."""
    kind = classify(email)
    if kind is None:
        return None
    when = interview_time(email, tz_name) if kind == INTERVIEW else None
    return Finding(kind=kind, company=company_from(email), role=role_from(email), when=when)


def match_application(finding, email, jobs):
    """Which application an email is about. jobs: (id, company name, company website, is closed, updated_at).
    Prefers open applications, then the most recently changed one. Returns an id or None."""
    want = company_key(finding.company) if finding.company else ""
    domain = email.sender_domain
    matches = []
    for job_id, company, website, closed, updated in jobs:
        key = company_key(company)
        same_name = bool(want and key) and (key == want or len(min(key, want, key=len)) >= 4
                                            and (key.startswith(want) or want.startswith(key)))
        site = re.sub(r"^www\.", "", (re.sub(r"^https?://", "", website or "").split("/")[0]).lower())
        same_site = bool(site and domain) and (domain == site or domain.endswith("." + site))
        if same_name or same_site:
            matches.append((not closed, updated, job_id))
    return max(matches)[2] if matches else None


def snippet(text, limit=300):
    return re.sub(r"\s+", " ", text).strip()[:limit]
