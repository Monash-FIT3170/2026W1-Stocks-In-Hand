from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.schemas.public_discussion import ArtifactTickerMentionCreate


def upsert_artifact_ticker_mention(
    db: Session,
    mention: ArtifactTickerMentionCreate,
    *,
    commit: bool = True,
) -> ArtifactTickerMention:
    """Create or update one artifact-to-ticker match."""

    row = (
        db.query(ArtifactTickerMention)
        .filter(
            ArtifactTickerMention.artifact_id == mention.artifact_id,
            ArtifactTickerMention.ticker_id == mention.ticker_id,
        )
        .first()
    )
    if row is None:
        row = ArtifactTickerMention(
            artifact_id=mention.artifact_id,
            ticker_id=mention.ticker_id,
        )
        db.add(row)

    row.match_method = mention.match_method
    row.match_confidence = mention.match_confidence
    row.matched_text = mention.matched_text

    try:
        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row
    except IntegrityError:
        db.rollback()
        row = (
            db.query(ArtifactTickerMention)
            .filter(
                ArtifactTickerMention.artifact_id == mention.artifact_id,
                ArtifactTickerMention.ticker_id == mention.ticker_id,
            )
            .one()
        )
        row.match_method = mention.match_method
        row.match_confidence = mention.match_confidence
        row.matched_text = mention.matched_text
        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row
