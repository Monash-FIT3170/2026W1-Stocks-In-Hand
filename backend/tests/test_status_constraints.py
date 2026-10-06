"""The status columns accept exactly the values in app.status."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.sources import SOURCES
from app.status import AnalysisStatus, DownloadStatus, ScrapeRunStatus


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


def _artifact(db: Session):
    run, _created = scrape_run_crud.get_or_create_queued_run(
        db,
        ticker="CSL",
        source_url=SOURCES["CSL"].source_url,
        idempotency_key=f"test:{uuid.uuid4()}",
    )
    url = f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf"
    artifact, _created = scrape_run_crud.get_or_create_artifact(
        db,
        scrape_run_id=run.id,
        canonical_url=url,
        document_url=url,
        source_adapter="csl",
    )
    return run, artifact


def _accepts(db: Session, table: str, column: str, row_id, value: str) -> bool:
    savepoint = db.begin_nested()
    try:
        db.execute(
            text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": value, "id": row_id},
        )
    except IntegrityError:
        savepoint.rollback()
        return False
    savepoint.rollback()
    return True


@pytest.mark.parametrize(
    ("table", "column", "statuses"),
    [
        ("scrape_runs", "status", ScrapeRunStatus),
        ("artifacts", "download_status", DownloadStatus),
        ("artifacts", "analysis_status", AnalysisStatus),
    ],
)
def test_status_column_accepts_exactly_its_enum(
    db_session: Session,
    table: str,
    column: str,
    statuses,
) -> None:
    run, artifact = _artifact(db_session)
    row_id = run.id if table == "scrape_runs" else artifact.id

    assert all(
        _accepts(db_session, table, column, row_id, status) for status in statuses
    )
    assert not _accepts(db_session, table, column, row_id, "succeeded")
