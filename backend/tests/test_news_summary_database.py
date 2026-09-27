"""News summaries replace the artifact's one summary row instead of inserting.

artifact_summaries allows one row per artifact. The admin news route used to
INSERT, so summarising a story the analysis worker had already summarised hit
the unique constraint.
"""

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.services import news_summary


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_summarising_an_already_summarised_story_updates_its_row(
    db_session: Session,
) -> None:
    artifact = Artifact(
        source_type="news",
        artifact_type="news_article",
        title="BHP lifts copper output",
        raw_text="BHP reported stronger copper production.",
        content_hash=f"news-{uuid.uuid4()}",
        artifact_metadata={"source_name": "publisher.example"},
    )
    db_session.add(artifact)
    db_session.flush()
    db_session.add(
        ArtifactSummary(
            artifact_id=artifact.id,
            summary_text="Worker summary.",
            model_used="bedrock:worker",
        )
    )
    db_session.commit()

    with patch.object(
        news_summary.summary_service,
        "summarise_news_article",
        return_value={
            "summary": "BHP lifted copper output.",
            "about": "The story covers BHP production.",
            "changed": "Copper output rose.",
            "matters": "Output supports revenue.",
        },
    ):
        news_summary.summarise_news_artifact(db_session, artifact)

    rows = db_session.scalars(
        select(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].summary_text.startswith("BHP lifted copper output.")
    assert rows[0].prompt_version == news_summary.summary_service.NEWS_SUMMARY_PROMPT_VERSION
