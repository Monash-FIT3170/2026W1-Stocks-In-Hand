import uuid

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class LLMRun(Base):
    __tablename__ = "llm_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type = Column(String, nullable=False)
    model_used = Column(String, nullable=False)
    prompt_version = Column(String, nullable=True)
    input_token_count = Column(Integer, nullable=True)
    output_token_count = Column(Integer, nullable=True)
    estimated_cost = Column(Numeric, nullable=True)
    status = Column(String, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
