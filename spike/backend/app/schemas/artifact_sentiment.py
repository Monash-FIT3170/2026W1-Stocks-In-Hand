from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

class ArtifactSentimentCreate(BaseModel):
    artifact_id: UUID
    sentiment_label: str
    stance: Optional[str] = None
    confidence_score: Optional[Decimal] = None
    model_used: Optional[str] = None

class ArtifactSentimentResponse(BaseModel):
    id: UUID
    artifact_id: UUID
    sentiment_label: str
    stance: Optional[str]
    confidence_score: Optional[Decimal]
    model_used: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}