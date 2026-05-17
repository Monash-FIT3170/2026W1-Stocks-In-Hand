from typing import Optional

from pydantic import BaseModel, Field


class RedditSummary(BaseModel):
    summary: str
    dominant_sentiment: Optional[str] = None
    key_themes: Optional[list[str]] = None


class CategorySentimentRequest(BaseModel):
    categories: dict[str, str | None] = Field(default_factory=dict)
    reddit_summary: Optional[RedditSummary] = None


class CategorySentimentResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    summary: str
    sentiment_label: str
    label: str
    score: float
    confidence_score: float
    distribution: dict[str, float]
    model_used: str
    chunks_used: int
    chunks_analyzed: int


class CategorySentimentResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    ticker: str
    model_used: str
    categories: dict[str, CategorySentimentResult]
