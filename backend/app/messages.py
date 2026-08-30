"""Versioned SQS message contracts for the ASX document pipeline."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    JsonValue,
    field_validator,
    model_validator,
)

from app.sources import SourceAdapter, adapter_matches_ticker


_FORBIDDEN_METADATA_KEYS = {
    "authorization",
    "browser_cookie",
    "cookie",
    "credentials",
    "document_bytes",
    "extracted_text",
    "password",
    "raw_text",
    "secret",
    "token",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_metadata(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    def visit(item: JsonValue) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key.lower() in _FORBIDDEN_METADATA_KEYS:
                    raise ValueError(f"metadata must not contain '{key}'")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return value


class QueueAMessage(BaseModel):
    """A request to discover downloadable documents on one source page."""

    schema_version: Literal[1] = 1
    scrape_run_id: UUID
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9.-]+$")
    source_url: HttpUrl
    source_adapter: SourceAdapter = "csl"
    requested_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("metadata")
    @classmethod
    def reject_sensitive_metadata(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        return _validate_metadata(value)

    @model_validator(mode="after")
    def adapter_must_match_ticker(self) -> "QueueAMessage":
        if not adapter_matches_ticker(self.ticker, self.source_adapter):
            raise ValueError("source_adapter does not match ticker")
        return self


class QueueBMessage(BaseModel):
    """A discovered document that should be downloaded into the raw S3 bucket."""

    schema_version: Literal[1] = 1
    scrape_run_id: UUID
    artifact_id: UUID
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9.-]+$")
    source_url: HttpUrl
    document_url: HttpUrl
    canonical_url: HttpUrl
    source_adapter: SourceAdapter = "csl"
    source_id: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=1000)
    published_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("metadata")
    @classmethod
    def reject_sensitive_metadata(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        return _validate_metadata(value)

    @model_validator(mode="after")
    def adapter_must_match_ticker(self) -> "QueueBMessage":
        if not adapter_matches_ticker(self.ticker, self.source_adapter):
            raise ValueError("source_adapter does not match ticker")
        return self


class NotificationMessage(BaseModel):
    """An analyzed artifact that may match investor alert preferences."""

    schema_version: Literal[1] = 1
    artifact_id: UUID
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9.-]+$")
    scrape_run_id: UUID
    sentiment_label: Literal["positive", "negative"]
    confidence_score: Decimal = Field(ge=0, le=1)

    model_config = {"extra": "forbid"}

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, value: object) -> object:
        """Normalise the producer ticker before applying its pattern."""
        return value.strip().upper() if isinstance(value, str) else value
