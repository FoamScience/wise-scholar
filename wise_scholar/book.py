"""Course export: a headless Chromium prints the web app's own book view, so the PDF carries the site's theme and type."""

import asyncio
import importlib.util

from .backends import PORT

# The cover appears once the course, its notebook and its exercise files are loaded; then every diagram
# has drawn (a failed one is replaced by its error) and every plot has drawn or reported its error.
READY = """() =>
  document.querySelector('.book-cover') !== null &&
  [...document.querySelectorAll('.book .mermaid')].every((e) => e.childElementCount > 0) &&
  [...document.querySelectorAll('.book .plot-box')].every(
    (e) => e.childElementCount > 0 || e.parentElement.querySelector('.error'))
"""

# One browser at a time: each export starts a Chromium of its own.
_exporting = asyncio.Lock()


class NoBrowser(Exception):
    pass


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


async def _launch(chromium):
    from playwright.async_api import Error

    try:
        return await chromium.launch()
    except Error as e:
        if "Executable doesn't exist" not in str(e):
            raise
    try:
        # No Chromium from `make pdf`: an installed Chrome prints the same.
        return await chromium.launch(channel="chrome")
    except Error:
        raise NoBrowser from None


async def render(course_id: int, profile_id: int, theme: str) -> bytes:
    """The course as a PDF. Raises NoBrowser without a Chromium or Chrome, and Playwright's TimeoutError
    when the page does not finish drawing."""
    from playwright.async_api import async_playwright

    async with _exporting, async_playwright() as p:
        browser = await _launch(p.chromium)
        try:
            context = await browser.new_context()
            # The page reads its profile, and through it the language, and its theme from the browser's storage.
            await context.add_init_script(
                f"localStorage.setItem('wise-scholar.profile', '{int(profile_id)}'); localStorage.setItem('theme', '{theme}')"
            )
            page = await context.new_page()
            await page.goto(f"http://127.0.0.1:{PORT}/#/course/{int(course_id)}/book")
            await page.wait_for_function(READY)
            await page.evaluate("() => document.fonts.ready.then(() => true)")
            return await page.pdf(prefer_css_page_size=True, print_background=True)
        finally:
            await browser.close()
