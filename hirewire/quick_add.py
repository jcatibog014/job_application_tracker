"""Quick add: paste a job posting's address, and the form fills itself in.

Most job sites put the posting's details in the page as schema.org
"JobPosting" data (a JSON block made for search engines), so we read that
first, and fall back to the page's title and description tags.

Fetching an address someone typed is risky: it could point at a computer
inside Render's own network ("SSRF"). So only http/https, only public
addresses (checked again after every redirect), 10 seconds and 1 MB at most.
"""
import ipaddress
import json
import re
import socket
from datetime import timedelta
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

TIMEOUT = 10
MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
HOURLY_LIMIT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HireWire/1.0; job application tracker)",
           "Accept": "text/html,application/xhtml+xml"}
SOURCES_BY_SITE = {
    "linkedin.": "LinkedIn", "jobstreet.": "JobStreet", "indeed.": "Indeed", "kalibrr.": "Kalibrr",
    "onlinejobs.ph": "OnlineJobs.ph", "greenhouse.io": "Company site", "lever.co": "Company site",
    "workable.com": "Company site", "myworkdayjobs.com": "Company site", "smartrecruiters.com": "Company site",
}


class FetchProblem(Exception):
    """Why the page couldn't be read, in words for the person."""


# ---------- Fetching safely ----------

def resolve(host, port):
    return {info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def check_address(url, resolver=resolve):
    """Refuse anything that isn't a public web address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchProblem("Only web addresses (http or https) can be read.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = resolver(parts.hostname, port)
    except (OSError, ValueError, UnicodeError):
        raise FetchProblem("That site couldn't be found. Check the address.") from None
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise FetchProblem("That address points inside a private network, so it can't be read.")


def fetch(url, get=requests.get, resolver=resolve):
    """The page's HTML as text, or raise FetchProblem."""
    for _ in range(MAX_REDIRECTS + 1):
        check_address(url, resolver)
        try:
            response = get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False, stream=True)
        except requests.RequestException:
            raise FetchProblem("The site didn't answer in time. Try again, or fill in the form yourself.") from None
        try:
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                url = urljoin(url, response.headers["Location"])
                continue
            if response.status_code != 200:
                raise FetchProblem(f"The site said no (error {response.status_code}). Some sites, like LinkedIn, "
                                   "only show postings to people who are logged in.")
            if "html" not in response.headers.get("Content-Type", "text/html"):
                raise FetchProblem("That address isn't a web page.")
            body = b""
            for chunk in response.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchProblem("That page is too big to read.")
            return body.decode(response.encoding or "utf-8", errors="replace"), url
        finally:
            response.close()
    raise FetchProblem("That address sends you around too many times.")


# ---------- Reading the posting ----------

def text_of(html, limit=20_000):
    """HTML -> plain text with paragraphs kept, at most limit characters."""
    text = BeautifulSoup(html or "", "html.parser").get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:limit]


def find_posting(data):
    """The first JobPosting in a JSON-LD block (it can sit in a list or an @graph)."""
    if isinstance(data, list):
        for item in data:
            found = find_posting(item)
            if found:
                return found
    elif isinstance(data, dict):
        kind = data.get("@type")
        if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
            return data
        if "@graph" in data:
            return find_posting(data["@graph"])
    return None


def name_of(value):
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def place_of(location):
    """jobLocation -> "Makati City, Metro Manila" (city and region)."""
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address", {}) if isinstance(location, dict) else {}
    if isinstance(address, str):
        return address
    parts = [name_of(address.get(key)) for key in ("addressLocality", "addressRegion")]
    if not any(parts):
        parts = [name_of(address.get("addressCountry"))]
    return ", ".join(part for part in parts if part)


def monthly_pay(salary):
    """baseSalary -> (lowest, highest, currency) a month, or (None, None, None)."""
    if not isinstance(salary, dict):
        return None, None, None
    currency = salary.get("currency")
    value = salary.get("value", {})
    if not isinstance(value, dict):
        value = {"value": value}
    unit = str(value.get("unitText") or salary.get("unitText") or "MONTH").upper()
    per_month = {"MONTH": 1, "YEAR": 1 / 12, "WEEK": 52 / 12}.get(unit)
    if per_month is None:
        return None, None, currency  # by the hour or the day: too unsure to turn into a month

    def number(key):
        try:
            return round(float(value[key]) * per_month)
        except (KeyError, TypeError, ValueError):
            return None

    low, high = number("minValue"), number("maxValue")
    if low is None and high is None:
        low = high = number("value")
    return low, high, currency


def source_of(url):
    host = (urlsplit(url).hostname or "").lower()
    for part, source in SOURCES_BY_SITE.items():
        if part in host:
            return source
    return "Company site"


def read_posting(html, url):
    """A job page -> the application form's fields (only the ones found)."""
    soup = BeautifulSoup(html, "html.parser")
    found = {"posting_url": url, "source": source_of(url)}
    posting = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            posting = find_posting(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if posting:
            break
    if posting:
        found["role_title"] = text_of(posting.get("title"), 150)
        found["company_name"] = name_of(posting.get("hiringOrganization"))[:120]
        found["location"] = place_of(posting.get("jobLocation"))[:120]
        if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
            found["work_mode"] = "remote"
        low, high, currency = monthly_pay(posting.get("baseSalary"))
        if low:
            found["salary_min"] = low
        if high:
            found["salary_max"] = high
        if currency:
            found["currency"] = str(currency).upper()[:3]
        found["job_description"] = text_of(posting.get("description"))
    else:
        def meta(*names):
            for name in names:
                tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
                if tag and tag.get("content"):
                    return tag["content"].strip()
            return ""
        title = meta("og:title", "twitter:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
        found["role_title"] = title[:150]
        found["company_name"] = meta("og:site_name")[:120]
        found["job_description"] = text_of(meta("og:description", "description"))
    return {name: value for name, value in found.items() if value}


# ---------- The hourly limit ----------

def take_a_turn(user, moment):
    """True (and counted) if the user may fetch another page this hour."""
    if user.quick_add_window is None or user.quick_add_window <= moment - timedelta(hours=1):
        user.quick_add_window, user.quick_adds = moment, 0
    if user.quick_adds >= HOURLY_LIMIT:
        return False
    user.quick_adds += 1
    return True
