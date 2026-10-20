"""Shared read policy for Reddit research selected for feeds or digests."""

from sqlalchemy import and_, or_

from app.models.artifact import Artifact
from app.status import AnalysisStatus


def approved_reddit_filter():
    """Require an analysed, approved post with a recorded company association."""
    return and_(
        Artifact.artifact_metadata["feed_eligible"].as_boolean().is_(True),
        Artifact.analysis_status == AnalysisStatus.COMPLETED,
        or_(Artifact.ticker_id.isnot(None), Artifact.ticker_mentions.any()),
    )
