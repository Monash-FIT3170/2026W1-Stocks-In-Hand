from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional

class ArtifactChunkCreate(BaseModel):
    artifact_id: UUID
    chunk_index: int
    chunk_text: str
    token_count: Optional[int] = None

class ArtifactChunkResponse(BaseModel):
    id: UUID
    artifact_id: UUID
    chunk_index: int
    chunk_text: str
    token_count: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}