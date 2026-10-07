from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Announcement:
    """One document a source adapter listed, before it is downloaded.

    ``metadata`` holds the adapter's resolution hints; Queue B carries it to
    the same adapter's fetch_document.
    """

    ticker: str
    title: str
    date: datetime
    pdf_url: str
    source_url: str
    local_path: Path | None = None
    metadata: dict = field(default_factory=dict)
