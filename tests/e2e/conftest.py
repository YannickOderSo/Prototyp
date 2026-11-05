"""Playwright-Tests auf Handy-Viewport 390 × 844 gegen den Django-Live-Server."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

VIEWPORT = {"width": 390, "height": 844}
VORINSTALLIERT = Path("/opt/pw-browsers/chromium")


def _chromium_pfad() -> str | None:
    if os.environ.get("PLAYWRIGHT_CHROMIUM"):
        return os.environ["PLAYWRIGHT_CHROMIUM"]
    if VORINSTALLIERT.is_file():
        return str(VORINSTALLIERT)
    return None


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        pfad = _chromium_pfad()
        argumente = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        b = pw.chromium.launch(executable_path=pfad, args=argumente) if pfad else pw.chromium.launch(args=argumente)
        yield b
        b.close()


@pytest.fixture
def seite(browser, live_server):
    kontext = browser.new_context(viewport=VIEWPORT, locale="de-DE", timezone_id="Europe/Berlin")
    kontext.grant_permissions(["microphone"], origin=live_server.url)
    page = kontext.new_page()
    page.set_default_timeout(10_000)
    yield page
    kontext.close()


def kein_horizontales_scrollen(page) -> None:
    breite = page.evaluate("document.documentElement.scrollWidth")
    sichtbar = page.evaluate("document.documentElement.clientWidth")
    assert breite <= sichtbar, f"horizontale Scrollleiste: {breite} > {sichtbar}"
