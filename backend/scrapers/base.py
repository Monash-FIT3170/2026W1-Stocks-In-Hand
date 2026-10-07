from datetime import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


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

    @abstractmethod
    async def fetch_announcements(self) -> list[Announcement]:
        """
        Navigate the IR page and return announcement metadata.
        No downloading occurs here.
        """
        ...
