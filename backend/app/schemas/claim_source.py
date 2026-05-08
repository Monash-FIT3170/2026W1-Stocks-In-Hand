from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ClaimSourceBase(BaseModel):
    claim_id: UUID
    artifact_id: UUID
    chunk_id: Optional[UUID] = None
    evidence_text: Optional[str] = None
    published_at: Optional[datetime] = None
    url: Optional[str] = None


class ClaimSourceCreate(ClaimSourceBase):
    pass


class ClaimSourceResponse(ClaimSourceBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
