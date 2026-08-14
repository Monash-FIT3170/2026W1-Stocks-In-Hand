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

    def __init__(self, output_dir: Path | None = None):
        # Lambda discovery does not pass an output directory, so it cannot
        # write files. Keep the directory behaviour for the existing local CLI.
        self.output_dir = output_dir / self.ticker if output_dir else None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def fetch_announcements(self) -> list[Announcement]:
        """
        Navigate the IR page and return announcement metadata.
        No downloading occurs here.
        """
        ...

    async def download_pdf(self, announcement: Announcement) -> Path:
        """
        Legacy local-CLI download using the same source session strategy as the
        AWS downloader. Discovery never calls this method.
        """
        if self.output_dir is None:
            raise ValueError("output_dir is required when downloading documents")

        # Imported lazily so discovery does not load downloader dependencies.
        from lambdas.source_download import resolve_session_download

        downloaded = await resolve_session_download(
            source_adapter=self.ticker.lower(),
            source_url=self.source_url,
            document_url=announcement.pdf_url,
            title=announcement.title,
            metadata=announcement.metadata,
            max_bytes=25 * 1024 * 1024,
        )
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in announcement.title
        ).strip("_")[:120] or "announcement"
        destination = (
            self.output_dir
            / f"{date_str}_{clean_title}.{downloaded.extension}"
        )
        destination.write_bytes(downloaded.content)
        return destination

    async def scrape(self) -> list[Announcement]:
        """
        Public entrypoint — always call this, never call fetch/download directly.
        Orchestrates fetch then download for every announcement found.
        """
        announcements = await self.fetch_announcements()
        if self.output_dir is None:
            raise ValueError("output_dir is required when downloading documents")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for ann in announcements:
            ann.local_path = await self.download_pdf(ann)
        return announcements
