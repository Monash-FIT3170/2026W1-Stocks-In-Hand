from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ClaimBase(BaseModel):
    ticker_id: UUID
    claim_text: str
    claim_type: Optional[str] = None
    reliability_label: Optional[str] = None
    confidence_score: Optional[Decimal] = None
    generated_by_model: Optional[str] = None


class ClaimCreate(ClaimBase):
    pass


class ClaimResponse(ClaimBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
