from sqlalchemy.orm import Session
from uuid import UUID
from app.models.investor import Investor
from app.schemas.investor import InvestorCreate

def get_investor(db: Session, investor_id: UUID):
    return db.query(Investor).filter(Investor.id == investor_id).first()

def get_investor_by_email(db: Session, email: str):
    return db.query(Investor).filter(Investor.email == email).first()

def get_investors(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Investor).offset(skip).limit(limit).all()

def create_investor(db: Session, investor: InvestorCreate):
    db_investor = Investor(
        email=investor.email,
        username=investor.username,
        hashed_password=investor.password + "_hashed"  # replace with real hashing later
    )
    db.add(db_investor)
    db.commit()
    db.refresh(db_investor)
    return db_investor

def update_investor(db: Session, investor_id: UUID, data: dict):
    db_investor = get_investor(db, investor_id)
    for key, value in data.items():
        setattr(db_investor, key, value)
    db.commit()
    db.refresh(db_investor)
    return db_investor

def delete_investor(db: Session, investor_id: UUID):
    db_investor = get_investor(db, investor_id)
    db.delete(db_investor)
    db.commit()