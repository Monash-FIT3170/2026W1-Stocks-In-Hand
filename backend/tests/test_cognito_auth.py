"""Focused tests for Cognito token and Supabase profile integration."""

import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.responses import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import deps
from app.api.routes import auth
from app.core.config import settings
from app.core.cognito import (
    CognitoPrincipal,
    CognitoServiceError,
    CognitoTokenError,
    CognitoUser,
    get_verified_cognito_user,
    verify_cognito_access_token,
)
from app.crud import investor as investor_crud
from app.models.investor import Investor
from app.schemas.auth import SignUpRequest


class StaticJwkClient:
    def __init__(self, public_key) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, _token: str):
        return SimpleNamespace(key=self.public_key)


@pytest.fixture()
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Investor.__table__.create(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _access_token(private_key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "client_id": "client-123",
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "iss": "https://issuer.example.test/pool",
        "sub": "subject-123",
        "token_use": "access",
        "username": "test@example.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})


def _set_cognito_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "COGNITO_ISSUER", "https://issuer.example.test/pool")
    monkeypatch.setattr(settings, "COGNITO_APP_CLIENT_ID", "client-123")


def test_access_token_verifies_required_cognito_claims(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys,
) -> None:
    private_key, public_key = rsa_keys
    _set_cognito_settings(monkeypatch)

    principal = verify_cognito_access_token(
        _access_token(private_key),
        jwk_client=StaticJwkClient(public_key),
    )

    assert principal.sub == "subject-123"
    assert principal.username == "test@example.com"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"token_use": "id"}, "not an access token"),
        ({"client_id": "other-client"}, "wrong app client"),
        ({"sub": ""}, "no subject"),
    ],
)
def test_access_token_rejects_wrong_cognito_claims(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys,
    overrides: dict,
    message: str,
) -> None:
    private_key, public_key = rsa_keys
    _set_cognito_settings(monkeypatch)

    with pytest.raises(CognitoTokenError, match=message):
        verify_cognito_access_token(
            _access_token(private_key, **overrides),
            jwk_client=StaticJwkClient(public_key),
        )


def test_access_token_rejects_expired_token(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys,
) -> None:
    private_key, public_key = rsa_keys
    _set_cognito_settings(monkeypatch)

    with pytest.raises(CognitoTokenError, match="Invalid Cognito access token"):
        verify_cognito_access_token(
            _access_token(
                private_key,
                exp=datetime.now(timezone.utc) - timedelta(minutes=1),
            ),
            jwk_client=StaticJwkClient(public_key),
        )


def test_get_user_requires_verified_matching_email() -> None:
    principal = CognitoPrincipal(
        sub="subject-123",
        username="test@example.com",
        access_token="access-token",
        claims={},
    )
    client = MagicMock()
    client.get_user.return_value = {
        "UserAttributes": [
            {"Name": "sub", "Value": "subject-123"},
            {"Name": "email", "Value": "Test@Example.com"},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": "Test User"},
        ],
        "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"],
    }

    user = get_verified_cognito_user(principal, client=client)

    assert user == CognitoUser(
        sub="subject-123",
        email="test@example.com",
        name="Test User",
        mfa_enabled=True,
    )
    client.get_user.assert_called_once_with(AccessToken="access-token")


def test_get_user_rejects_unverified_email() -> None:
    principal = CognitoPrincipal("subject-123", None, "access-token", {})
    client = MagicMock()
    client.get_user.return_value = {
        "UserAttributes": [
            {"Name": "sub", "Value": "subject-123"},
            {"Name": "email", "Value": "test@example.com"},
            {"Name": "email_verified", "Value": "false"},
        ]
    }

    with pytest.raises(CognitoTokenError, match="not verified"):
        get_verified_cognito_user(principal, client=client)


def test_profile_bootstrap_is_idempotent(db_session: Session) -> None:
    first, first_created = investor_crud.bootstrap_cognito_investor(
        db_session,
        cognito_sub="subject-123",
        email="Test@Example.com",
        username="Test User",
    )
    second, second_created = investor_crud.bootstrap_cognito_investor(
        db_session,
        cognito_sub="subject-123",
        email="test@example.com",
        username="Test User",
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.email == "test@example.com"
    assert second.hashed_password is None
    assert second.role == "user"
    assert db_session.query(Investor).count() == 1


def test_existing_email_link_requires_explicit_permission(db_session: Session) -> None:
    legacy = Investor(
        email="test@example.com",
        username="Legacy User",
        hashed_password="legacy-hash",
        role="user",
    )
    db_session.add(legacy)
    db_session.commit()

    with pytest.raises(
        investor_crud.CognitoProfileConflict,
        match="approved Cognito identity link",
    ):
        investor_crud.bootstrap_cognito_investor(
            db_session,
            cognito_sub="subject-123",
            email="test@example.com",
            username="Test User",
        )

    linked, created = investor_crud.bootstrap_cognito_investor(
        db_session,
        cognito_sub="subject-123",
        email="test@example.com",
        username="Test User",
        allow_existing_email_link=True,
    )
    assert created is False
    assert linked.id == legacy.id
    assert linked.cognito_sub == "subject-123"


def test_current_investor_uses_cognito_subject_in_cognito_mode(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    investor = Investor(
        email="test@example.com",
        cognito_sub="subject-123",
        username="Test User",
        role="user",
    )
    db_session.add(investor)
    db_session.commit()
    principal = CognitoPrincipal("subject-123", None, "access-token", {})
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "cognito")
    monkeypatch.setattr(
        deps,
        "authenticate_cognito_authorization",
        MagicMock(return_value=principal),
    )
    verify_user = MagicMock(
        return_value=CognitoUser(
            sub="subject-123",
            email="test@example.com",
            name="Test User",
        )
    )
    monkeypatch.setattr(deps, "get_verified_cognito_user", verify_user)

    current = deps.get_current_investor(
        session_token=None,
        authorization="Bearer access-token",
        db=db_session,
    )

    assert current.id == investor.id
    verify_user.assert_called_once_with(principal)


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (CognitoTokenError("revoked"), 401),
        (CognitoServiceError("unavailable"), 503),
    ],
)
def test_current_investor_checks_cognito_session_with_service(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    error: Exception,
    expected_status: int,
) -> None:
    principal = CognitoPrincipal("subject-123", None, "access-token", {})
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "cognito")
    monkeypatch.setattr(
        deps,
        "authenticate_cognito_authorization",
        MagicMock(return_value=principal),
    )
    monkeypatch.setattr(
        deps,
        "get_verified_cognito_user",
        MagicMock(side_effect=error),
    )

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_investor(
            session_token=None,
            authorization="Bearer access-token",
            db=db_session,
        )

    assert exc_info.value.status_code == expected_status


def test_cognito_admin_requires_mfa(monkeypatch: pytest.MonkeyPatch) -> None:
    investor = MagicMock()
    investor.role = "admin"
    investor._cognito_mfa_enabled = False
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "cognito")

    with pytest.raises(HTTPException) as exc_info:
        deps.require_admin_investor(investor)

    assert exc_info.value.status_code == 403
    assert "multi-factor" in exc_info.value.detail


def test_cognito_admin_with_mfa_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    investor = MagicMock()
    investor.role = "admin"
    investor._cognito_mfa_enabled = True
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "cognito")

    assert deps.require_admin_investor(investor) is investor


def test_legacy_signup_is_disabled_in_cognito_mode(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "cognito")

    with pytest.raises(HTTPException) as exc_info:
        auth.sign_up(
            body=SignUpRequest(
                name="Test User",
                email="test@example.com",
                password="password123",
            ),
            response=Response(),
            db=db_session,
        )

    assert exc_info.value.status_code == 410


def test_legacy_signup_is_disabled_in_dual_mode(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "dual")

    with pytest.raises(HTTPException) as exc_info:
        auth.sign_up(
            body=SignUpRequest(
                name="Test User",
                email="test@example.com",
                password="password123",
            ),
            response=Response(),
            db=db_session,
        )

    assert exc_info.value.status_code == 410


def test_dual_mode_uses_cognito_when_authorization_is_present(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    investor = Investor(
        email="test@example.com",
        cognito_sub="subject-123",
        username="Test User",
        role="user",
    )
    db_session.add(investor)
    db_session.commit()
    principal = CognitoPrincipal("subject-123", None, "access-token", {})
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "dual")
    authenticate = MagicMock(return_value=principal)
    monkeypatch.setattr(deps, "authenticate_cognito_authorization", authenticate)
    monkeypatch.setattr(
        deps,
        "get_verified_cognito_user",
        MagicMock(
            return_value=CognitoUser(
                sub="subject-123",
                email="test@example.com",
                name="Test User",
                mfa_enabled=True,
            )
        ),
    )

    current = deps.get_current_investor(
        session_token="ignored-legacy-cookie",
        authorization="Bearer access-token",
        db=db_session,
    )

    assert current.id == investor.id
    assert current._authenticated_with_cognito is True
    authenticate.assert_called_once_with("Bearer access-token")


def test_dual_mode_does_not_fall_back_after_invalid_authorization(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "dual")
    authenticate = MagicMock(side_effect=CognitoTokenError("invalid"))
    monkeypatch.setattr(deps, "authenticate_cognito_authorization", authenticate)

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_investor(
            session_token="valid-or-invalid-cookie-is-not-used",
            authorization="Bearer invalid-token",
            db=db_session,
        )

    assert exc_info.value.status_code == 401
