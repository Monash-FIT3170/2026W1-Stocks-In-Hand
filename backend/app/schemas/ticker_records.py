from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.ticker_brief import SourceLink


class NewsFeedRecord(BaseModel):
    """One record in a ticker's news feed: the artifact's card, dated for display."""

    id: UUID
    ticker: str
    time: str
    tag: str
    title: str
    source_type: str
    source_name: Optional[str]
    source_label: str
    url: Optional[str]
    # None until the record's summary has that line.
    about: Optional[str]
    changed: Optional[str]
    matters: Optional[str]
    # The content topics recorded for the record, most confident first.
    topics: list[str] = []
    sources: list[SourceLink]


class DeepDiveEvent(BaseModel):
    """One record in a ticker's research history."""

    tag: str
    title: str
    date: str
    # The summary's text, or None until the record has a summary.
    detail: Optional[str]
    sources: list[SourceLink]
