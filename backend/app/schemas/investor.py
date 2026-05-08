from pydantic import BaseModel, EmailStr
from datetime import datetime
from uuid import UUID
from typing import Optional

class InvestorCreate(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    password: Optional[str] = None

class InvestorResponse(BaseModel):
    id: UUID
    email: EmailStr
    username: Optional[str]
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}