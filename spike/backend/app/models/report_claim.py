from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class ReportClaim(Base):
    __tablename__ = "report_claims"

    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reports.id"),
        primary_key=True,
    )
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("claims.id"),
        primary_key=True,
    )
    display_order = Column(Integer, nullable=True)
