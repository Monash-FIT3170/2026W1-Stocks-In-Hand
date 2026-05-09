from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from decimal import Decimal

class ArtifactTopicCreate(BaseModel):
    artifact_id: UUID
    topic_id: UUID
    confidence_score: Optional[Decimal] = None

class ArtifactTopicResponse(BaseModel):
    artifact_id: UUID
    topic_id: UUID
    confidence_score: Optional[Decimal]

    model_config = {"from_attributes": True}