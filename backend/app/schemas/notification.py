"""Request and response contracts for investor notification preferences."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


SentimentLabel = Literal["positive", "neutral", "negative"]
VerificationStatus = Literal["unverified", "pending", "verified", "failed"]


class NotificationPreferencesUpdate(BaseModel):
    """Editable settings for sentiment-driven watchlist alerts."""

    enabled: bool
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    sentiment_labels: list[SentimentLabel] = Field(
        default_factory=lambda: ["negative"],
        min_length=1,
        max_length=3,
    )

    model_config = {"extra": "forbid"}

    @field_validator("sentiment_labels")
    @classmethod
    def reject_duplicate_labels(
        cls,
        value: list[SentimentLabel],
    ) -> list[SentimentLabel]:
        """Keep rule payloads deterministic and free of duplicates."""
        if len(set(value)) != len(value):
            raise ValueError("sentiment_labels must not contain duplicates")
        return value


class NotificationPreferencesResponse(BaseModel):
    """Current alert, verification, and delivery state for one investor."""

    feature_enabled: bool
    enabled: bool
    email: EmailStr
    min_confidence: float = Field(ge=0, le=1)
    sentiment_labels: list[SentimentLabel]
    verification_status: VerificationStatus
    verification_requested_at: datetime | None = None
    verified_at: datetime | None = None
    last_delivery_status: str | None = None
    last_delivery_error_code: str | None = None
    last_delivery_at: datetime | None = None
    unsubscribe_token: str | None = None


class UnsubscribeRequest(BaseModel):
    """One opaque raw or signed unsubscribe token."""

    token: str = Field(min_length=16, max_length=512)

    model_config = {"extra": "forbid"}

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        """Reject whitespace-only tokens and ignore surrounding whitespace."""
        token = value.strip()
        if not token:
            raise ValueError("token must not be empty")
        return token


class UnsubscribeResponse(BaseModel):
    """A generic response that does not reveal whether a token matched."""

    message: str
