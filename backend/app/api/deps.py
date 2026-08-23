from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.cognito import (
    CognitoConfigurationError,
    CognitoPrincipal,
    CognitoServiceError,
    CognitoTokenError,
    CognitoUser,
    authenticate_cognito_authorization,
    get_verified_cognito_user,
)
from app.core.security import hash_session_token
from app.database.connection import get_db
from app.models.auth_session import AuthSession
from app.models.investor import Investor


def _is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _cognito_principal_or_error(authorization: str | None) -> CognitoPrincipal:
    try:
        return authenticate_cognito_authorization(authorization)
    except CognitoConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito authentication is not configured",
        ) from exc
    except CognitoTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc


def get_cognito_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CognitoPrincipal:
    if settings.AUTH_PROVIDER not in {"dual", "cognito"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _cognito_principal_or_error(authorization)


def _verified_cognito_user_or_error(principal: CognitoPrincipal) -> CognitoUser:
    try:
        return get_verified_cognito_user(principal)
    except CognitoTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc
    except CognitoServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito authentication is temporarily unavailable",
        ) from exc


def get_current_investor(
    session_token: str | None = Cookie(default=None, alias=settings.SESSION_COOKIE_NAME),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> Investor:
    use_cognito = settings.AUTH_PROVIDER == "cognito" or (
        settings.AUTH_PROVIDER == "dual" and authorization is not None
    )
    if use_cognito:
        principal = _cognito_principal_or_error(authorization)
        cognito_user = _verified_cognito_user_or_error(principal)
        investor = (
            db.query(Investor)
            .filter(Investor.cognito_sub == cognito_user.sub)
            .first()
        )
        if not investor:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cognito profile setup required",
            )
        investor._cognito_mfa_enabled = cognito_user.mfa_enabled
        investor._authenticated_with_cognito = True
        return investor

    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token_hash = hash_session_token(session_token)
    auth_session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
    if not auth_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    if _is_expired(auth_session.expires_at):
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )

    investor = db.query(Investor).filter(Investor.id == auth_session.investor_id).first()
    if not investor:
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return investor


def require_admin_investor(
    current_investor: Investor = Depends(get_current_investor),
) -> Investor:
    """Restrict cost-bearing and account-management operations to admins."""
    if (current_investor.role or "").lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    cognito_admin = settings.AUTH_PROVIDER == "cognito" or getattr(
        current_investor,
        "_authenticated_with_cognito",
        False,
    )
    if cognito_admin and not getattr(current_investor, "_cognito_mfa_enabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator multi-factor authentication required",
        )
    return current_investor
