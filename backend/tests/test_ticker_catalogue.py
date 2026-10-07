"""The ticker catalogue and the one path that makes sure a ticker row exists."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app import sources
from app.core.config import settings
from app.crud import ticker as ticker_crud
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate
from app.sources import SourceDefinition, normalise_symbol, source_for_ticker


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


@pytest.fixture()
def new_catalogue_entry(monkeypatch: pytest.MonkeyPatch) -> SourceDefinition:
    entry = SourceDefinition(
        ticker="ZZQ",
        adapter="csl",
        source_url="https://example.test/zzq/announcements",
        company_name="ZZQ Holdings Limited",
        sector="Utilities",
        industry="Electric Utilities",
    )
    monkeypatch.setitem(sources.SOURCES, entry.ticker, entry)
    return entry


@pytest.mark.parametrize(
    ("value", "expected"),
    [("BHP", "BHP"), (" bhp ", "BHP"), ("bhp.ax", "BHP"), ("BHP.AX", "BHP"), ("  ", "")],
)
def test_symbols_are_normalised_to_the_stored_form(value: str, expected: str) -> None:
    assert normalise_symbol(value) == expected


def test_exchange_qualified_symbols_find_their_catalogue_entry() -> None:
    assert source_for_ticker("csl.ax") is sources.SOURCES["CSL"]
    assert source_for_ticker("XYZ") is None


def test_ticker_create_stores_the_normalised_symbol() -> None:
    assert TickerCreate(symbol=" bhp.ax ", company_name="BHP Group").symbol == "BHP"
    with pytest.raises(ValueError):
        TickerCreate(symbol=".AX", company_name="Nothing")


def test_ensure_ticker_returns_the_seeded_row(db_session: Session) -> None:
    seeded = db_session.scalars(select(Ticker).where(Ticker.symbol == "CSL")).one()

    assert ticker_crud.ensure_ticker(db_session, "csl.ax") is seeded


def test_ensure_ticker_creates_a_catalogue_ticker_with_catalogue_facts(
    db_session: Session,
    new_catalogue_entry: SourceDefinition,
) -> None:
    ticker = ticker_crud.ensure_ticker(db_session, "zzq")

    assert (ticker.symbol, ticker.company_name, ticker.exchange, ticker.sector, ticker.industry) == (
        "ZZQ",
        "ZZQ Holdings Limited",
        "ASX",
        "Utilities",
        "Electric Utilities",
    )
    assert ticker_crud.ensure_ticker(db_session, "ZZQ").id == ticker.id
    assert db_session.scalar(
        select(func.count()).select_from(Ticker).where(Ticker.symbol == "ZZQ")
    ) == 1


def test_ensure_ticker_names_an_unknown_symbol_after_itself(db_session: Session) -> None:
    ticker = ticker_crud.ensure_ticker(db_session, "xyz")

    assert (ticker.symbol, ticker.company_name, ticker.sector) == ("XYZ", "XYZ", None)


def test_ensure_ticker_fills_placeholders_and_keeps_curated_values(
    db_session: Session,
) -> None:
    db_session.execute(
        text("UPDATE tickers SET company_name = symbol, sector = NULL WHERE symbol = 'BHP'")
    )
    db_session.execute(
        text("UPDATE tickers SET company_name = 'CSL (curated)' WHERE symbol = 'CSL'")
    )
    db_session.expire_all()

    bhp = ticker_crud.ensure_ticker(db_session, "BHP")
    csl = ticker_crud.ensure_ticker(db_session, "CSL")

    assert (bhp.company_name, bhp.sector) == ("BHP Group Limited", "Materials")
    assert csl.company_name == "CSL (curated)"


def test_ensure_ticker_rejects_an_empty_symbol() -> None:
    with pytest.raises(ValueError):
        ticker_crud.ensure_ticker(None, " .ax ")  # type: ignore[arg-type]
