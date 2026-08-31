"""Build-time smoke test for the Chromium bundled in the scraper image."""

import asyncio

from playwright.async_api import async_playwright

from scrapers.browser import chromium_launch_options


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**chromium_launch_options())
        try:
            page = await browser.new_page()
            await page.goto("data:text/html,<title>scraper-smoke-ok</title>")
            if await page.title() != "scraper-smoke-ok":
                raise RuntimeError("Chromium smoke page returned the wrong title")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
