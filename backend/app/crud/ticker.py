from sqlalchemy.orm import Session
from uuid import UUID
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate

def get_ticker(db: Session, ticker_id: UUID):
    return db.query(Ticker).filter(Ticker.id == ticker_id).first()

def get_ticker_by_symbol(db: Session, symbol: str):
    return db.query(Ticker).filter(Ticker.symbol == symbol).first()

def get_tickers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Ticker).offset(skip).limit(limit).all()

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