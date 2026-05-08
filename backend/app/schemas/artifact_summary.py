from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

class ArtifactSummaryCreate(BaseModel):
    artifact_id: UUID
    summary_text: str
    model_used: Optional[str] = None
    prompt_version: Optional[str] = None
    confidence_score: Optional[Decimal] = None

class ArtifactSummaryResponse(BaseModel):
    id: UUID
    artifact_id: UUID
    summary_text: str
    model_used: Optional[str]
    prompt_version: Optional[str]
    confidence_score: Optional[Decimal]
    created_at: datetime

    model_config = {"from_attributes": True}