from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

class ExtractedFactCreate(BaseModel):
    artifact_id: UUID
    chunk_id: Optional[UUID] = None
    fact_text: str
    fact_type: Optional[str] = None
    confidence_score: Optional[Decimal] = None
    is_speculative: bool = False
    model_used: Optional[str] = None

class ExtractedFactResponse(BaseModel):
    id: UUID
    artifact_id: UUID
    chunk_id: Optional[UUID]
    fact_text: str
    fact_type: Optional[str]
    confidence_score: Optional[Decimal]
    is_speculative: bool
    model_used: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}