from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, Any

class InformationPlatformCreate(BaseModel):
    name: str
    platform_type: str
    base_url: Optional[str] = None
    scrape_enabled: bool = True
    scrape_config: Optional[dict[str, Any]] = None

class InformationPlatformUpdate(BaseModel):
    """Settings an administrator may change on an existing platform.

    The name is left out because platform rows are looked up by name.
    """

    platform_type: Optional[str] = None
    base_url: Optional[str] = None
    scrape_enabled: Optional[bool] = None
    scrape_config: Optional[dict[str, Any]] = None

    model_config = {"extra": "forbid"}

    @field_validator("platform_type", "scrape_enabled")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value

class InformationPlatformResponse(BaseModel):
    id: UUID
    name: str
    platform_type: str
    base_url: Optional[str]
    scrape_enabled: bool
    scrape_config: Optional[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}
