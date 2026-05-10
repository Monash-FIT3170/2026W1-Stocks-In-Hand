from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

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

    report = relationship("Report", back_populates="report_claims")
    claim = relationship("Claim", back_populates="report_claims")
