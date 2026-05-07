from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime


@dataclass
class Announcement:
    ticker: str
    title: str
    date: datetime
    pdf_url: str
    source_url: str
    local_path: Path | None = None
    metadata: dict = field(default_factory=dict)


class BaseScraper(ABC):

    @property
    @abstractmethod
    def ticker(self) -> str: ...

    @property
    @abstractmethod
    def source_url(self) -> str: ...

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir / self.ticker
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def fetch_announcements(self) -> list[Announcement]:
        """
        Navigate the IR page and return announcement metadata.
        No downloading occurs here.
        """
        ...

    @abstractmethod
    async def download_pdf(self, announcement: Announcement) -> Path:
        """
        Download a single PDF to self.output_dir.
        Returns the local path it was saved to.
        """
        ...

    async def scrape(self) -> list[Announcement]:
        """
        Public entrypoint — always call this, never call fetch/download directly.
        Orchestrates fetch then download for every announcement found.
        """
        announcements = await self.fetch_announcements()
        for ann in announcements:
            ann.local_path = await self.download_pdf(ann)
        return announcements