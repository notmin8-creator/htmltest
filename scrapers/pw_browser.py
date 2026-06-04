"""Shared Playwright browser manager — one browser for all scrapers."""

import logging
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

_pw   = None
_browser = None


def get_browser():
    global _pw, _browser
    if _browser is None:
        _pw      = sync_playwright().start()
        _browser = _pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Playwright Chromium browser started.")
    return _browser


def close_browser():
    global _pw, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _pw:
        _pw.stop()
        _pw = None
    logger.info("Playwright browser closed.")


def fetch(url, api_patterns=None, wait_selector=None, wait_ms=4000):
    """
    Load *url* in a real Chromium tab.
    - api_patterns : list of URL substrings whose JSON responses to capture
    - wait_selector: CSS selector to wait for before returning
    - wait_ms      : extra ms to wait after page load for JS to settle

    Returns (html_str, intercepted_list)
    intercepted_list = [{'url': ..., 'data': {...}}, ...]
    """
    browser     = get_browser()
    intercepted = []

    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="ar-SA",
        extra_http_headers={
            "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        viewport={"width": 1366, "height": 768},
    )
    page = ctx.new_page()

    if api_patterns:
        def _on_response(resp):
            try:
                if any(p in resp.url for p in api_patterns):
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        intercepted.append({"url": resp.url, "data": resp.json()})
            except Exception:
                pass
        page.on("response", _on_response)

    html = ""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=10_000)
            except PWTimeout:
                pass
        page.wait_for_timeout(wait_ms)
        html = page.content()
    except Exception as exc:
        logger.warning(f"[Playwright] Error loading {url}: {exc}")
    finally:
        ctx.close()

    return html, intercepted
