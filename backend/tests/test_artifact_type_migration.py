"""Announcements analysed before analysis stored their category's type get it.

Analysis stored every pipeline announcement as asx_announcement_other, so an
old dividend announcement and a new one had different types.
"""

import importlib.util
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from parsing.classification.taxonomy import OTHER_ARTIFACT_TYPE, TAXONOMY

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "86d9artifacttypes_store_announcement_artifact_types.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("artifact_types_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_migration_snapshots_every_category_with_its_own_type() -> None:
    assert set(_migration().ARTIFACT_TYPES) == {
        (definition.compatibility_category, definition.artifact_type)
        for definition in TAXONOMY
        if definition.artifact_type != OTHER_ARTIFACT_TYPE
    }


def test_announcements_get_their_categorys_type_and_nothing_else_changes(
    db_session: Session,
) -> None:
    def artifact(source_type: str, artifact_type: str, category: str) -> Artifact:
        row = Artifact(
            source_type=source_type,
            artifact_type=artifact_type,
            content_hash=f"types-{uuid.uuid4()}",
            artifact_metadata={"category": category},
        )
        db_session.add(row)
        return row

    rows = {
        "dividend": artifact("asx_announcement", "asx_announcement_other", "DividendAnnouncement"),
        "leadership": artifact("asx_announcement", "dividend_announcement", "LeadershipChange"),
        "half_year": artifact("asx_announcement", "asx_announcement_other", "HalfYearResults"),
        "news": artifact("news", "news_article", "DividendAnnouncement"),
    }
    db_session.flush()

    for _run in range(2):
        _migration().store_announcement_artifact_types(db_session.connection())

    db_session.expire_all()
    assert {name: row.artifact_type for name, row in rows.items()} == {
        "dividend": "dividend_announcement",
        "leadership": "leadership_change",
        "half_year": "asx_announcement_other",
        "news": "news_article",
    }
