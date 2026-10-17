from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate
from app.sources import normalise_symbol, source_for_ticker

def get_ticker(db: Session, ticker_id: UUID):
    return db.query(Ticker).filter(Ticker.id == ticker_id).first()

def get_ticker_by_symbol(db: Session, symbol: str):
    return db.query(Ticker).filter(Ticker.symbol == normalise_symbol(symbol)).first()

def get_tickers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Ticker).order_by(Ticker.symbol.asc()).offset(skip).limit(limit).all()

def create_ticker(db: Session, ticker: TickerCreate):
    db_ticker = Ticker(**ticker.model_dump())
    db.add(db_ticker)
    db.commit()
    db.refresh(db_ticker)
    return db_ticker

def update_ticker(db: Session, ticker_id: UUID, data: dict):
    db_ticker = get_ticker(db, ticker_id)
    for key, value in data.items():
        setattr(db_ticker, key, value)
    db.commit()
    db.refresh(db_ticker)
    return db_ticker


def ensure_ticker(db: Session, symbol: str) -> Ticker:
    """Return the row for ``symbol``, creating it from the ticker catalogue if needed.

    Catalogue tickers get the catalogue's name, sector and industry, and an
    existing row with a placeholder (an empty value, or the symbol as its
    name) is filled in while curated values are kept. A symbol outside the
    catalogue gets the symbol as its name. The change joins the caller's
    transaction: it is flushed, not committed. A concurrent insert of the
    same symbol is absorbed by the unique constraint instead of failing.
    """
    symbol = normalise_symbol(symbol)
    if not symbol:
        raise ValueError("Ticker symbol must not be empty")
    source = source_for_ticker(symbol)
    facts = {
        "company_name": source.company_name if source else symbol,
        "exchange": "ASX",
        "sector": source.sector if source else None,
        "industry": source.industry if source else None,
    }

    ticker = get_ticker_by_symbol(db, symbol)
    if ticker is None:
        db.execute(
            insert(Ticker)
            .values(id=uuid4(), symbol=symbol, **facts)
            .on_conflict_do_nothing(index_elements=[Ticker.symbol])
        )
        return get_ticker_by_symbol(db, symbol)

    if source is not None:
        for field, value in facts.items():
            current = getattr(ticker, field)
            if not current or (field == "company_name" and current == symbol):
                setattr(ticker, field, value)
        db.flush()
    return ticker
