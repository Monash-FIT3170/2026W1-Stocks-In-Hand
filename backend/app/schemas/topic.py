from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional

class TopicCreate(BaseModel):
    name: str
    description: Optional[str] = None

class TopicResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}