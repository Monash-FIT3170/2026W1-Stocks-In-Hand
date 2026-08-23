"""Validate Cognito access tokens and load verified user attributes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
import jwt
from botocore.exceptions import BotoCoreError, ClientError
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from app.core.config import settings


class CognitoConfigurationError(RuntimeError):
    """Raised when Cognito mode is missing required runtime settings."""


class CognitoTokenError(ValueError):
    """Raised when a Cognito token is absent or invalid."""


class CognitoServiceError(RuntimeError):
    """Raised when verified Cognito user attributes cannot be loaded."""


@dataclass(frozen=True)
class CognitoPrincipal:
    """Trusted claims and source token from a validated access token."""

    sub: str
    username: str | None
    access_token: str
    claims: dict[str, Any]


@dataclass(frozen=True)
class CognitoUser:
    """Verified Cognito attributes used to create an application profile."""

    sub: str
    email: str
    name: str | None
    mfa_enabled: bool = False


def _cognito_issuer() -> str:
    if settings.COGNITO_ISSUER:
        return settings.COGNITO_ISSUER.rstrip("/")
    if settings.COGNITO_USER_POOL_ID:
        return (
            f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com/"
            f"{settings.COGNITO_USER_POOL_ID}"
        )
    raise CognitoConfigurationError("COGNITO_USER_POOL_ID is required")


def _require_cognito_client_id() -> str:
    if not settings.COGNITO_APP_CLIENT_ID:
        raise CognitoConfigurationError("COGNITO_APP_CLIENT_ID is required")
    return settings.COGNITO_APP_CLIENT_ID


@lru_cache(maxsize=4)
def _cached_jwk_client(issuer: str, lifespan: int) -> PyJWKClient:
    return PyJWKClient(
        f"{issuer}/.well-known/jwks.json",
        cache_jwk_set=True,
        lifespan=lifespan,
        timeout=5,
    )


def verify_cognito_access_token(
    access_token: str,
    *,
    jwk_client: Any | None = None,
) -> CognitoPrincipal:
    """Validate a Cognito access token and return its trusted identity."""
    if not access_token or not access_token.strip():
        raise CognitoTokenError("Missing Cognito access token")

    issuer = _cognito_issuer()
    client_id = _require_cognito_client_id()
    client = jwk_client or _cached_jwk_client(
        issuer,
        settings.COGNITO_JWKS_CACHE_SECONDS,
    )

    try:
        signing_key = client.get_signing_key_from_jwt(access_token).key
        claims = jwt.decode(
            access_token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_aud": False,
                "require": ["client_id", "exp", "iat", "iss", "sub", "token_use"],
            },
            leeway=5,
        )
    except (InvalidTokenError, PyJWKClientError, ValueError) as exc:
        raise CognitoTokenError("Invalid Cognito access token") from exc

    if claims.get("token_use") != "access":
        raise CognitoTokenError("Cognito token is not an access token")
    claim_client_id = str(claims.get("client_id", ""))
    if not secrets.compare_digest(claim_client_id, client_id):
        raise CognitoTokenError("Cognito token has the wrong app client")

    subject = str(claims.get("sub", "")).strip()
    if not subject:
        raise CognitoTokenError("Cognito token has no subject")
    username = claims.get("username")
    return CognitoPrincipal(
        sub=subject,
        username=str(username) if username else None,
        access_token=access_token,
        claims=claims,
    )


def authenticate_cognito_authorization(
    authorization: str | None,
    *,
    jwk_client: Any | None = None,
) -> CognitoPrincipal:
    """Parse a bearer header and validate its Cognito access token."""
    if not authorization:
        raise CognitoTokenError("Missing Authorization header")
    scheme, separator, access_token = authorization.strip().partition(" ")
    if not separator or scheme.lower() != "bearer" or not access_token.strip():
        raise CognitoTokenError("Authorization header must use Bearer authentication")
    return verify_cognito_access_token(access_token.strip(), jwk_client=jwk_client)


@lru_cache(maxsize=2)
def _cognito_client(region: str):
    return boto3.client("cognito-idp", region_name=region)


def get_verified_cognito_user(
    principal: CognitoPrincipal,
    *,
    client: Any | None = None,
) -> CognitoUser:
    """Load verified user attributes for a validated Cognito principal."""
    cognito_client = client or _cognito_client(settings.AWS_REGION)
    try:
        response = cognito_client.get_user(AccessToken=principal.access_token)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NotAuthorizedException", "UserNotFoundException"}:
            raise CognitoTokenError("Cognito session is no longer valid") from exc
        raise CognitoServiceError("Could not load Cognito user attributes") from exc
    except BotoCoreError as exc:
        raise CognitoServiceError("Could not load Cognito user attributes") from exc

    attributes = {
        str(item.get("Name")): str(item.get("Value", ""))
        for item in response.get("UserAttributes", [])
        if item.get("Name")
    }
    subject = attributes.get("sub", "").strip()
    if not subject or not secrets.compare_digest(subject, principal.sub):
        raise CognitoTokenError("Cognito user does not match the access token")
    if attributes.get("email_verified", "").lower() != "true":
        raise CognitoTokenError("Cognito email is not verified")
    email = attributes.get("email", "").strip().lower()
    if not email:
        raise CognitoTokenError("Cognito user has no verified email")
    name = attributes.get("name", "").strip() or None
    mfa_settings = {
        str(setting).strip().upper()
        for setting in response.get("UserMFASettingList", [])
        if setting
    }
    return CognitoUser(
        sub=subject,
        email=email,
        name=name,
        mfa_enabled="SOFTWARE_TOKEN_MFA" in mfa_settings,
    )
