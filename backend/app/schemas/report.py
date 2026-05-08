from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ReportBase(BaseModel):
    ticker_id: UUID
    report_title: Optional[str] = None
    report_text: str
    report_type: str
    model_used: Optional[str] = None


class ReportCreate(ReportBase):
    pass


class ReportResponse(ReportBase):
    id: UUID
    generated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
