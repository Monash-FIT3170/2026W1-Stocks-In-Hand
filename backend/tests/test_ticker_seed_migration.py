"""A freshly migrated database already has every supported ticker.

/news-feed, /sentiment/{ticker} and the public-discussion status route used
to 404 on a fresh database until some other ticker route had created the
rows on demand.
"""

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.api.routes import category_sentiment, ticker as ticker_route
from app.core.config import settings
from app.models.ticker import Ticker
from app.services import public_discussion
from app.sources import SOURCES

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "86d9seedtickers_seed_supported_tickers.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("seed_tickers_migration", MIGRATION_PATH)
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


def test_migration_seeds_the_catalogue_facts() -> None:
    seeded = {
        symbol: (company_name, sector, industry)
        for symbol, company_name, sector, industry in _migration().SUPPORTED_TICKERS
    }

    assert seeded == {
        symbol: (source.company_name, source.sector, source.industry)
        for symbol, source in SOURCES.items()
    }


def test_migrated_database_has_named_rows_for_every_source(db_session: Session) -> None:
    rows = {
        row.symbol: row.company_name
        for row in db_session.scalars(select(Ticker).where(Ticker.symbol.in_(SOURCES)))
    }

    assert set(rows) == set(SOURCES)
    assert all(name and name != symbol for symbol, name in rows.items())


@pytest.mark.parametrize("symbol", sorted(SOURCES))
def test_read_routes_find_every_ticker_on_a_migrated_database(
    db_session: Session,
    symbol: str,
) -> None:
    assert ticker_route.get_ticker_news_feed(symbol, db=db_session) == []
    assert ticker_route.get_ticker_deep_dive_timeline(symbol, db=db_session) == []
    assert ticker_route.get_ticker_by_symbol(symbol, db=db_session).symbol == symbol
    category = category_sentiment.read_ticker_category_sentiment(symbol, db=db_session)
    assert category["ticker"] == symbol
    status = public_discussion.public_discussion_status(db_session, symbol)
    assert status["ticker"] == symbol


def test_reseeding_fills_placeholders_and_keeps_curated_values(db_session: Session) -> None:
    connection = db_session.connection()
    connection.execute(
        text("UPDATE tickers SET company_name = symbol, sector = NULL WHERE symbol = 'BHP'")
    )
    connection.execute(
        text("UPDATE tickers SET company_name = 'CSL (curated)' WHERE symbol = 'CSL'")
    )

    _migration().seed_supported_tickers(connection)
    _migration().seed_supported_tickers(connection)

    rows = {
        symbol: (name, sector)
        for symbol, name, sector in connection.execute(
            text(
                "SELECT symbol, company_name, sector FROM tickers "
                "WHERE symbol IN ('BHP', 'CSL')"
            )
        )
    }
    assert rows["BHP"] == ("BHP Group Limited", "Materials")
    assert rows["CSL"][0] == "CSL (curated)"
    assert connection.execute(
        text("SELECT count(*) FROM tickers WHERE symbol = 'BHP'")
    ).scalar_one() == 1
