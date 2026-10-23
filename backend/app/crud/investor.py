import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import UUID
from app.models.investor import Investor
from app.schemas.investor import InvestorCreate
from app.core.security import hash_password, hash_session_token, verify_password

EMAIL_CHANGE_TOKEN_TTL = timedelta(hours=24)

def get_investor(db: Session, investor_id: UUID):
    return db.query(Investor).filter(Investor.id == investor_id).first()

def get_investor_by_email(db: Session, email: str):
    return db.query(Investor).filter(Investor.email == email).first()

def get_auth_investor_by_email(db: Session, email: str):
    normalized_email = email.strip().lower()
    return db.query(Investor).filter(func.lower(Investor.email) == normalized_email).first()

def get_investor_by_cognito_sub(db: Session, cognito_sub: str):
    return db.query(Investor).filter(Investor.cognito_sub == cognito_sub).first()

def get_investors(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Investor).offset(skip).limit(limit).all()

def create_investor(db: Session, investor: InvestorCreate):
    password = investor.password
    normalized_email = str(investor.email).strip().lower()
    db_investor = Investor(
        email=normalized_email,
        username=investor.username,
        hashed_password=hash_password(password) if password else None,
        role="user",
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
    normalized_email = email.strip().lower()
    db_investor = Investor(
        email=normalized_email,
        username=username,
        hashed_password=hash_password(password),
        role="user",
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

class CognitoProfileConflict(ValueError):
    """Raised when a Cognito identity cannot be linked without ambiguity."""


def bootstrap_cognito_investor(
    db: Session,
    *,
    cognito_sub: str,
    email: str,
    username: str | None,
    allow_existing_email_link: bool = False,
):
    normalized_sub = cognito_sub.strip()
    normalized_email = email.strip().lower()
    normalized_username = username.strip() if username else None
    if not normalized_sub:
        raise ValueError("Cognito subject is required")
    if not normalized_email:
        raise ValueError("Verified Cognito email is required")

    by_subject = get_investor_by_cognito_sub(db, normalized_sub)
    if by_subject:
        email_owner = get_auth_investor_by_email(db, normalized_email)
        if email_owner and email_owner.id != by_subject.id:
            raise CognitoProfileConflict("Verified email belongs to another investor")
        changed = False
        if by_subject.email != normalized_email:
            by_subject.email = normalized_email
            changed = True
        if normalized_username and by_subject.username != normalized_username:
            by_subject.username = normalized_username
            changed = True
        if changed:
            db.commit()
            db.refresh(by_subject)
        return by_subject, False

    by_email = get_auth_investor_by_email(db, normalized_email)
    if by_email:
        if by_email.cognito_sub and by_email.cognito_sub != normalized_sub:
            raise CognitoProfileConflict("Verified email is linked to another identity")
        if not allow_existing_email_link:
            raise CognitoProfileConflict(
                "Existing profile requires an approved Cognito identity link"
            )
        by_email.cognito_sub = normalized_sub
        if normalized_username:
            by_email.username = normalized_username
        try:
            db.commit()
            db.refresh(by_email)
        except IntegrityError:
            db.rollback()
            concurrent = get_investor_by_cognito_sub(db, normalized_sub)
            if concurrent:
                return concurrent, False
            raise
        return by_email, False

    investor = Investor(
        email=normalized_email,
        cognito_sub=normalized_sub,
        username=normalized_username,
        hashed_password=None,
        role="user",
    )
    db.add(investor)
    try:
        db.commit()
        db.refresh(investor)
    except IntegrityError as exc:
        db.rollback()
        concurrent = get_investor_by_cognito_sub(db, normalized_sub)
        if concurrent:
            return concurrent, False
        raise CognitoProfileConflict("Cognito profile could not be linked") from exc
    return investor, True

def update_investor(db: Session, investor_id: UUID, data: dict):
    db_investor = get_investor(db, investor_id)
    allowed = {"email", "username", "role"}
    for key, value in data.items():
        if key not in allowed:
            raise ValueError(f"Investor field '{key}' cannot be updated")
        if key == "email":
            value = str(value).strip().lower()
        setattr(db_investor, key, value)
    db.commit()
    db.refresh(db_investor)
    return db_investor

def update_investor_profile(db: Session, investor: Investor, data: dict):
    """Apply immediate (non-email) profile fields. Email changes go through
    ``request_email_change`` instead, since they must be verified first."""
    allowed = {"username"}
    for key, value in data.items():
        if key not in allowed:
            raise ValueError(f"Investor field '{key}' cannot be updated")
        setattr(investor, key, value)
    db.commit()
    db.refresh(investor)
    return investor

def change_password(db: Session, investor: Investor, current_password: str, new_password: str):
    if not verify_password(current_password, investor.hashed_password):
        raise ValueError("Current password is incorrect")
    investor.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(investor)
    return investor

def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def request_email_change(db: Session, investor: Investor, new_email: str) -> str:
    """Start a pending email change, returning the raw confirmation token.

    The investor's ``email`` is not touched until the new address is
    confirmed through ``confirm_email_change``.
    """
    normalized = new_email.strip().lower()
    if normalized == investor.email:
        raise ValueError("That is already your email address")
    existing = get_auth_investor_by_email(db, email=normalized)
    if existing and existing.id != investor.id:
        raise ValueError("Email already registered")

    raw_token = secrets.token_urlsafe(32)
    investor.pending_email = normalized
    investor.pending_email_token_hash = hash_session_token(raw_token)
    investor.pending_email_requested_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(investor)
    return raw_token

def confirm_email_change(db: Session, investor_id: UUID, raw_token: str) -> Investor:
    invalid = ValueError("This confirmation link is invalid or has expired")
    investor = get_investor(db, investor_id)
    if (
        not investor
        or not investor.pending_email
        or not investor.pending_email_token_hash
        or not investor.pending_email_requested_at
    ):
        raise invalid
    requested_at = _aware_utc(investor.pending_email_requested_at)
    if datetime.now(timezone.utc) - requested_at > EMAIL_CHANGE_TOKEN_TTL:
        raise invalid
    if not secrets.compare_digest(
        hash_session_token(raw_token), investor.pending_email_token_hash
    ):
        raise invalid

    new_email = investor.pending_email
    conflicting = get_auth_investor_by_email(db, email=new_email)
    investor.pending_email = None
    investor.pending_email_token_hash = None
    investor.pending_email_requested_at = None
    if conflicting and conflicting.id != investor.id:
        db.commit()
        raise ValueError("That email address was claimed by another account")

    investor.email = new_email
    db.commit()
    db.refresh(investor)
    return investor

def delete_investor(db: Session, investor_id: UUID):
    db_investor = get_investor(db, investor_id)
    db.delete(db_investor)
    db.commit()
