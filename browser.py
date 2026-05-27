from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Page
from config import CDP_ENDPOINT, TARGET_URL


@contextmanager
def connect_to_chrome():
    """Connect to an already-open Chrome with --remote-debugging-port=9222."""
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        page = _find_page(browser)
        yield page
        browser.close()


def _find_page(browser) -> Page:
    for context in browser.contexts:
        for page in context.pages:
            if TARGET_URL in page.url:
                return page
    raise RuntimeError(
        f"No Chrome tab found at {TARGET_URL}. "
        "Make sure Chrome is open with --remote-debugging-port=9222 and the game is loaded."
    )
