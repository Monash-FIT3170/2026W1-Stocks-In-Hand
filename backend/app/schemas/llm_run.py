from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class LLMRunBase(BaseModel):
    task_type: str
    model_used: str
    prompt_version: Optional[str] = None
    input_token_count: Optional[int] = None
    output_token_count: Optional[int] = None
    estimated_cost: Optional[Decimal] = None
    status: str
    error_message: Optional[str] = None


class LLMRunCreate(LLMRunBase):
    pass


class LLMRunResponse(LLMRunBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
