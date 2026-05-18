from sqlalchemy import func
from sqlalchemy.orm import Session
from uuid import UUID
from app.models.investor import Investor
from app.schemas.investor import InvestorCreate
from app.core.security import hash_password, verify_password

def get_investor(db: Session, investor_id: UUID):
    return db.query(Investor).filter(Investor.id == investor_id).first()

def get_investor_by_email(db: Session, email: str):
    return db.query(Investor).filter(Investor.email == email).first()

def get_auth_investor_by_email(db: Session, email: str):
    normalized_email = email.strip().lower()
    return db.query(Investor).filter(func.lower(Investor.email) == normalized_email).first()

def get_investors(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Investor).offset(skip).limit(limit).all()

def create_investor(db: Session, investor: InvestorCreate):
    password = investor.password
    db_investor = Investor(
        email=investor.email,
        username=investor.username,
        hashed_password=f"{password}_hashed" if password else None
    )
    db.add(db_investor)
    db.commit()
    db.refresh(db_investor)
    return db_investor

def create_auth_investor(
    db: Session,
    email: str,
    username: str,
    password: str,
):
    db_investor = Investor(
        email=email.strip().lower(),
        username=username,
        hashed_password=hash_password(password),
    )
    db.add(db_investor)
    db.commit()
    db.refresh(db_investor)
    return db_investor

def authenticate_investor(db: Session, email: str, password: str):
    investor = get_auth_investor_by_email(db, email=email)
    if not investor or not verify_password(password, investor.hashed_password):
        return None
    if investor.hashed_password and investor.hashed_password.endswith("_hashed"):
        investor.hashed_password = hash_password(password)
        db.commit()
        db.refresh(investor)
    return investor

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
