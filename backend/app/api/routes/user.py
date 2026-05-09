from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database.connection import SessionLocal
from app.schemas.user import UserCreate, UserResponse
from app.crud.user import create_user, get_users

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=UserResponse)
def create_user_route(user: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, user)

@router.get("/", response_model=list[UserResponse])
def get_users_route(db: Session = Depends(get_db)):
    return get_users(db)