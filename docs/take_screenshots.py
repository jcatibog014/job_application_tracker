"""Take the README screenshots (docs/screenshots/*.png).

Retake them in every pull request that visibly changes a page, and add a new
one when a page or feature is added: the README shows everything the app can
do. tests/test_readme.py fails if the pictures and the README disagree.

Every picture uses "Try Demo", so only made-up companies and people show.
It uses Microsoft Edge, which Windows already has, through Playwright.
Playwright is only a tool for this script, so it is not in requirements.txt:

    .venv\\Scripts\\python -m pip install playwright
    $env:DATABASE_URL = "sqlite:///C:/Temp/hirewire-screenshots.sqlite"
    .venv\\Scripts\\flask --app hirewire upgrade-db
    .venv\\Scripts\\flask --app hirewire run --port 5006      (keep this one running)
    .venv\\Scripts\\python docs\\take_screenshots.py          (in another terminal)

Every picture is one screen (no full-page shots), so they are all the same size.
Add a line to PAGES when a page is added.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5006"
OUT = Path(__file__).parent / "screenshots"
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}

# (file name, address, theme, screen size). {job} is the demo's Pacific Data Co application.
PAGES = [
    ("dashboard.png", "/dashboard/", "light", DESKTOP),
    ("dashboard-dark.png", "/dashboard/", "dark", DESKTOP),
    ("applications.png", "/applications/", "light", DESKTOP),
    ("application.png", "{job}", "light", DESKTOP),
    ("board.png", "/board/", "light", DESKTOP),
    ("schedule.png", "/schedule/", "light", DESKTOP),
    ("email-suggestions.png", "/email-suggestions/", "light", DESKTOP),
    ("quick-add.png", "/applications/quick-add", "light", DESKTOP),
    ("companies.png", "/companies/", "light", DESKTOP),
    ("contacts.png", "/contacts/", "light", DESKTOP),
    ("documents.png", "/documents/", "light", DESKTOP),
    ("stats.png", "/stats/", "light", DESKTOP),
    ("stats-dark.png", "/stats/", "dark", DESKTOP),
    ("phone.png", "/dashboard/", "light", PHONE),
]


def demo_page(browser, theme, size):
    page = browser.new_page(viewport=size, color_scheme=theme)
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name="Try Demo").click()
    page.wait_for_url("**/dashboard/")
    return page


def save(page, name):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    page.screenshot(path=OUT / name)
    print("saved", name)


def shoot(page, name, path):
    page.goto(f"{BASE}{path}")
    save(page, name)


def shoot_visitor_pages(browser):
    page = browser.new_page(viewport=DESKTOP, color_scheme="light")
    shoot(page, "login.png", "/login")
    shoot(page, "signup.png", "/signup")
    page.close()


def shoot_page_parts(page):
    """Things that need a click or a scroll first."""
    # The filters open (the panel starts closed), with a few chosen.
    page.goto(f"{BASE}/applications/?stage=applied&stage=screening&stage=interview&mode=hybrid&mode=onsite"
              "&sort=pay&order=desc")
    page.locator(".filter-toggle").click()
    save(page, "filters.png")
    page.locator(".filter-toggle").click()  # closed again, for the pictures after this one
    # The application page, further down: the follow-ups, people and the timeline.
    page.goto(f"{BASE}{job_address(page)}")
    page.locator("#timeline").scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -120)")
    save(page, "timeline.png")
    # Settings: reminders, the calendar feed and Gmail.
    page.goto(f"{BASE}/settings/")
    page.locator("#reminders").scroll_into_view_if_needed()
    page.evaluate("document.getElementById('reminders').scrollIntoView()")
    save(page, "settings.png")
    # A snoozed follow-up's menu, open.
    page.goto(f"{BASE}/dashboard/")
    page.locator(".snooze summary").first.click()
    save(page, "snooze.png")


def shoot_phone_menu(page):
    page.goto(f"{BASE}/dashboard/")
    page.get_by_role("button", name="Menu").click()
    save(page, "phone-menu.png")


def job_address(page):
    page.goto(f"{BASE}/applications/")
    return page.locator(".row-link", has_text="Junior Data Analyst").get_attribute("href")


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        shoot_visitor_pages(browser)
        pages = {}
        for name, path, theme, size in PAGES:
            key = (theme, size["width"])
            if key not in pages:
                pages[key] = demo_page(browser, theme, size)
            page = pages[key]
            if path == "{job}":
                path = job_address(page)
            shoot(page, name, path)
        shoot_page_parts(pages[("light", DESKTOP["width"])])
        shoot_phone_menu(pages[("light", PHONE["width"])])
        browser.close()


if __name__ == "__main__":
    main()
