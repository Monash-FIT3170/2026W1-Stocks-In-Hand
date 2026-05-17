from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investor
from app.core.config import settings
from app.core.security import create_session_token, hash_session_token
from app.crud import investor as investor_crud
from app.database.connection import get_db
from app.models.auth_session import AuthSession
from app.models.investor import Investor
from app.schemas.auth import AuthResponse, SignInRequest, SignUpRequest


router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )


def _create_session(db: Session, investor: Investor) -> str:
    token = create_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SESSION_EXPIRE_DAYS)
    db_session = AuthSession(
        investor_id=investor.id,
        token_hash=hash_session_token(token),
        expires_at=expires_at,
    )
    db.add(db_session)
    db.commit()
    return token


@router.post("/sign-up", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def sign_up(body: SignUpRequest, response: Response, db: Session = Depends(get_db)):
    existing = investor_crud.get_auth_investor_by_email(db, email=body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    investor = investor_crud.create_auth_investor(
        db=db,
        email=str(body.email),
        username=body.name,
        password=body.password,
    )
    token = _create_session(db, investor)
    _set_session_cookie(response, token)
    return {"message": "Signed up successfully", "investor": investor}


@router.post("/sign-in", response_model=AuthResponse)
def sign_in(body: SignInRequest, response: Response, db: Session = Depends(get_db)):
    investor = investor_crud.authenticate_investor(
        db=db,
        email=body.email,
        password=body.password,
    )
    if not investor:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _create_session(db, investor)
    _set_session_cookie(response, token)
    return {"message": "Signed in successfully", "investor": investor}


@router.get("/me", response_model=AuthResponse)
def me(current_investor: Investor = Depends(get_current_investor)):
    return {"message": "Authenticated", "investor": current_investor}


@router.post("/sign-out")
def sign_out(request: Request, response: Response, db: Session = Depends(get_db)):
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_token:
        token_hash = hash_session_token(session_token)
        auth_session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
        if auth_session:
            db.delete(auth_session)
            db.commit()

    _clear_session_cookie(response)
    return {"message": "Signed out successfully"}
