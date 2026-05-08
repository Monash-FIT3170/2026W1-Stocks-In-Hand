from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WatchlistBase(BaseModel):
    investor_id: UUID
    name: str


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistResponse(WatchlistBase):
    id: UUID
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
