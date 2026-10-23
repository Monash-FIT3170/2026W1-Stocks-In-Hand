import logging
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_cognito_principal, get_current_investor
from app.core.config import settings
from app.core.cognito import (
    CognitoPrincipal,
    CognitoServiceError,
    CognitoTokenError,
    get_verified_cognito_user,
)
from app.core.security import create_session_token, hash_session_token
from app.crud import investor as investor_crud
from app.database.connection import get_db
from app.models.auth_session import AuthSession
from app.models.investor import Investor
from app.schemas.auth import (
    AuthResponse,
    ConfirmEmailChangeRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    SignInRequest,
    SignUpRequest,
)
from app.services.email_sender import Accepted, OutgoingEmail, configured_sender

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])


def _require_legacy_auth(*, allow_dual: bool = False) -> None:
    legacy_enabled = settings.AUTH_PROVIDER == "legacy" or (
        allow_dual and settings.AUTH_PROVIDER == "dual"
    )
    if not legacy_enabled:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Legacy authentication is disabled",
        )


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
    _require_legacy_auth()
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
    _require_legacy_auth(allow_dual=True)
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


def _reject_if_cognito_managed(current_investor: Investor) -> None:
    if getattr(current_investor, "_authenticated_with_cognito", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is managed through Cognito — update it there instead",
        )


def _email_change_confirmation_url(investor_id: UUID, raw_token: str) -> str:
    base_url = settings.FRONTEND_BASE_URL.strip().rstrip("/")
    token = f"{investor_id.hex}.{raw_token}"
    return f"{base_url}/confirm-email-change?{urlencode({'token': token})}"


def _send_email_change_confirmation(to: str, confirm_url: str) -> None:
    subject = "Confirm your new Stocks In Hand email address"
    safe_url = escape(confirm_url, quote=True)
    html = (
        "<!doctype html><html lang=\"en\"><body>"
        "<h1>Confirm your new email address</h1>"
        "<p>Click the link below to confirm this is your new Stocks In Hand sign-in email.</p>"
        f'<p><a href="{safe_url}">Confirm email address</a></p>'
        "<p>If you did not request this change, you can ignore this email.</p>"
        "</body></html>"
    )
    text = (
        "Confirm your new Stocks In Hand email address\n\n"
        "Open this link to confirm:\n"
        f"{confirm_url}\n\n"
        "If you did not request this change, you can ignore this email.\n"
    )
    outcome = configured_sender().send(
        OutgoingEmail(to=to, subject=subject, html=html, text=text)
    )
    if not isinstance(outcome, Accepted):
        LOGGER.warning("Email change confirmation to %s was not accepted: %s", to, outcome)


@router.patch("/me", response_model=AuthResponse)
def update_profile(
    body: ProfileUpdateRequest,
    current_investor: Investor = Depends(get_current_investor),
    db: Session = Depends(get_db),
):
    _reject_if_cognito_managed(current_investor)
    data = body.model_dump(exclude_unset=True)
    new_email = data.pop("email", None)

    if data:
        try:
            investor_crud.update_investor_profile(db, current_investor, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = "Profile updated successfully"
    if new_email is not None and new_email != current_investor.email:
        try:
            raw_token = investor_crud.request_email_change(
                db, current_investor, new_email
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        confirm_url = _email_change_confirmation_url(current_investor.id, raw_token)
        _send_email_change_confirmation(current_investor.pending_email, confirm_url)
        message = (
            "Profile updated successfully. Check your new email address to "
            "confirm the change."
        )

    return {"message": message, "investor": current_investor}


@router.post("/confirm-email-change")
def confirm_email_change(body: ConfirmEmailChangeRequest, db: Session = Depends(get_db)):
    invalid_link = HTTPException(
        status_code=400, detail="This confirmation link is invalid or has expired"
    )
    parts = body.token.split(".", 1)
    if len(parts) != 2:
        raise invalid_link
    try:
        investor_id = UUID(hex=parts[0])
    except ValueError as exc:
        raise invalid_link from exc

    try:
        investor_crud.confirm_email_change(db, investor_id, parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Email address updated successfully"}


@router.post("/me/change-password")
def change_password(
    body: PasswordChangeRequest,
    current_investor: Investor = Depends(get_current_investor),
    db: Session = Depends(get_db),
):
    _reject_if_cognito_managed(current_investor)
    try:
        investor_crud.change_password(
            db, current_investor, body.current_password, body.new_password
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Password changed successfully"}


@router.post("/bootstrap", response_model=AuthResponse)
def bootstrap_cognito_profile(
    principal: CognitoPrincipal = Depends(get_cognito_principal),
    db: Session = Depends(get_db),
):
    try:
        cognito_user = get_verified_cognito_user(principal)
    except CognitoTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc
    except CognitoServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito profile service is unavailable",
        ) from exc

    try:
        investor, created = investor_crud.bootstrap_cognito_investor(
            db,
            cognito_sub=cognito_user.sub,
            email=cognito_user.email,
            username=cognito_user.name,
            allow_existing_email_link=settings.COGNITO_LINK_EXISTING_BY_EMAIL,
        )
    except investor_crud.CognitoProfileConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return {
        "message": "Cognito profile created" if created else "Cognito profile linked",
        "investor": investor,
    }


@router.post("/sign-out")
def sign_out(request: Request, response: Response, db: Session = Depends(get_db)):
    _require_legacy_auth(allow_dual=True)
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_token:
        token_hash = hash_session_token(session_token)
        auth_session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
        if auth_session:
            db.delete(auth_session)
            db.commit()

    _clear_session_cookie(response)
    return {"message": "Signed out successfully"}
