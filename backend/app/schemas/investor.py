from pydantic import BaseModel, EmailStr
from datetime import datetime
from uuid import UUID
from typing import Literal, Optional

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


class InvestorUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    role: Optional[Literal["user", "admin"]] = None

    model_config = {"extra": "forbid"}
