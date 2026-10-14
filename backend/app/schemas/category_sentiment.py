from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.public_discussion import PublicDiscussionSource


class CategorySentimentResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    summary: str
    available: bool = False
    sentiment_label: Optional[str] = None
    label: Optional[str] = None
    score: Optional[float] = None
    confidence_score: Optional[float] = None
    agreement_score: Optional[float] = None
    distribution: dict[str, float] = Field(default_factory=dict)
    model_used: Optional[str] = None
    chunks_used: int = 0
    chunks_analyzed: int = 0
    sources_count: int = 0
    sources: list[PublicDiscussionSource] = Field(default_factory=list)
    latest_analyzed_at: Optional[datetime] = None


class CategorySentimentResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    ticker: str
    status: Literal["available", "partial", "unavailable"]
    model_used: Optional[str] = None
    latest_analyzed_at: Optional[datetime] = None
    categories: dict[str, CategorySentimentResult]
