from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ReportClaimBase(BaseModel):
    report_id: UUID
    claim_id: UUID
    display_order: Optional[int] = None


class ReportClaimCreate(ReportClaimBase):
    pass


class ReportClaimResponse(ReportClaimBase):
    model_config = {"from_attributes": True}
