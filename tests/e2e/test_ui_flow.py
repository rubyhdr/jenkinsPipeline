"""Browser tests run by Jenkins against the deployed staging environment.

Requires BASE_URL (the app) and SELENIUM_URL (a Selenium Grid / standalone-chrome). Skipped otherwise.
"""
import os
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
SELENIUM_URL = os.environ.get("SELENIUM_URL")
SCREENSHOT_DIR = Path(os.environ.get("E2E_SCREENSHOT_DIR", "reports/e2e-screenshots"))

if not (BASE_URL and SELENIUM_URL):
    pytest.skip("BASE_URL and SELENIUM_URL not set; skipping browser tests", allow_module_level=True)

from selenium import webdriver  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402


@pytest.fixture(scope="module")
def browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    driver = None
    for _ in range(30):  # the Selenium container may still be starting
        try:
            driver = webdriver.Remote(command_executor=SELENIUM_URL, options=options)
            break
        except Exception:
            time.sleep(2)
    if driver is None:
        pytest.fail(f"Could not connect to Selenium at {SELENIUM_URL}")
    driver.implicitly_wait(5)
    yield driver
    driver.quit()


@pytest.fixture(autouse=True)
def screenshot_on_failure(request, browser):
    yield
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        browser.save_screenshot(str(SCREENSHOT_DIR / f"{request.node.name}.png"))


def wait_for(browser, locator, timeout=10):
    return WebDriverWait(browser, timeout).until(EC.visibility_of_element_located(locator))


def css(selector):
    return (By.CSS_SELECTOR, selector)


def test_home_page_shows_catalogue(browser):
    browser.get(BASE_URL + "/")
    assert "Shelf" in browser.title
    cards = browser.find_elements(*css("[data-testid=book-card]"))
    assert len(cards) > 0
    assert wait_for(browser, css("[data-testid=version-badge]")).text.strip().startswith("v")


def test_live_search_filters_results(browser):
    browser.get(BASE_URL + "/")
    search = wait_for(browser, css("[data-testid=search]"))
    search.send_keys("hobbit")
    WebDriverWait(browser, 10).until(
        lambda d: len(d.find_elements(*css("[data-testid=book-card]"))) == 1
    )
    assert "Hobbit" in browser.find_element(*css("[data-testid=book-card]")).text


def test_member_can_register_borrow_and_return(browser):
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    browser.get(BASE_URL + "/register")
    browser.find_element(By.NAME, "name").send_keys("E2E Tester")
    browser.find_element(By.NAME, "email").send_keys(email)
    browser.find_element(By.NAME, "password").send_keys("Selenium123")
    browser.find_element(By.NAME, "confirm").send_keys("Selenium123")
    browser.find_element(*css("[data-testid=register-submit]")).click()
    assert "Your account is ready" in wait_for(browser, css("[data-testid=flash]")).text

    # Search for a book with several copies and borrow it.
    browser.get(BASE_URL + "/?q=atomic")
    wait_for(browser, css("[data-testid=book-card]")).click()
    title = wait_for(browser, css("[data-testid=book-title]")).text
    browser.find_element(*css("[data-testid=borrow]")).click()
    assert "You borrowed" in wait_for(browser, css("[data-testid=flash]")).text

    loans = browser.find_elements(*css("[data-testid=active-loan]"))
    assert any(title in loan.text for loan in loans)

    browser.find_element(*css("[data-testid=return-loan]")).click()
    assert "Returned" in wait_for(browser, css("[data-testid=flash]")).text
    assert not browser.find_elements(*css("[data-testid=active-loan]"))

    browser.find_element(*css("[data-testid=logout]")).click()
    assert "signed out" in wait_for(browser, css("[data-testid=flash]")).text
