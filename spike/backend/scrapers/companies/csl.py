import re
import httpx
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page

from ..base import BaseScraper, Announcement

class CSLScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "CSL"

    @property
    def source_url(self) -> str:
        return "https://..."  # IR page URL when you get to it

    async def fetch_announcements(self) -> list[Announcement]:
        raise NotImplementedError

    async def download_pdf(self, announcement: Announcement) -> Path:
        raise NotImplementedError