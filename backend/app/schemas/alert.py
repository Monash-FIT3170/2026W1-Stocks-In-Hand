from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AlertBase(BaseModel):
    investor_id: UUID
    ticker_id: UUID
    alert_type: str
    title: str
    message: str
    severity: Optional[str] = None
    is_read: bool = False


class AlertCreate(AlertBase):
    pass


class AlertResponse(AlertBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
