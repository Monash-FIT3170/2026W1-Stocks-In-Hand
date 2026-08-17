from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base
from app.status import AnalysisStatus, DownloadStatus

class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "scrape_run_id",
            "canonical_url",
            name="uq_artifacts_run_canonical_url",
        ),
        UniqueConstraint(
            "source_document_identity",
            name="uq_artifacts_source_document_identity",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scrape_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_runs.id"),
        nullable=True,
        index=True,
    )
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=True)
    platform_id = Column(UUID(as_uuid=True), ForeignKey("information_platforms.id"), nullable=True)
    source_type = Column(String, nullable=True)
    source_adapter = Column(String, nullable=True)
    source_id = Column(String, nullable=True)
    source_document_identity = Column(String(length=64), nullable=True)
    canonical_url = Column(Text, nullable=True)
    document_url = Column(Text, nullable=True)
    artifact_type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    author = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    artifact_metadata = Column(JSONB, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String, unique=True, nullable=True)
    checksum_sha256 = Column(String(length=64), nullable=True)
    content_type = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    s3_bucket = Column(String, nullable=True)
    s3_key = Column(Text, nullable=True)
    download_status = Column(String, nullable=False, default=DownloadStatus.PENDING)
    analysis_status = Column(String, nullable=False, default=AnalysisStatus.PENDING)
    downloaded_at = Column(DateTime(timezone=True), nullable=True)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    ticker = relationship("Ticker", backref="artifacts")
    platform = relationship("InformationPlatform", backref="artifacts")
    scrape_run = relationship("ScrapeRun", back_populates="artifacts")
