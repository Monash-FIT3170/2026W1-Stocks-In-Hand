from sqlalchemy.orm import Session
from uuid import UUID
from app.models.market_data import MarketData
from app.schemas.market_data import MarketDataCreate

def get_market_data(db: Session, market_data_id: UUID):
    return db.query(MarketData).filter(MarketData.id == market_data_id).first()

def get_market_data_by_ticker(db: Session, ticker_id: UUID):
    return db.query(MarketData).filter(MarketData.ticker_id == ticker_id).all()

def get_latest_market_data(db: Session, ticker_id: UUID):
    return (
        db.query(MarketData)
        .filter(MarketData.ticker_id == ticker_id)
        .order_by(MarketData.created_at.desc())
        .first()
    )

def create_market_data(db: Session, market_data: MarketDataCreate):
    db_md = MarketData(**market_data.model_dump())
    db.add(db_md)
    db.commit()
    db.refresh(db_md)
    return db_md