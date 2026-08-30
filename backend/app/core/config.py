"""Environment-backed application settings."""

import os
from pathlib import Path

from app.sources import SOURCES


def _load_local_env() -> None:
    """Load backend/.env for local runs without overriding real env vars."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


def _env_int(name: str, default: int, *, minimum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_confidence(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _first_env(*names: str) -> str:
    """Return the first non-empty value from equivalent environment names."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class Settings:
    """Application configuration loaded from environment variables.

    The database layer reads ``DATABASE_URL`` from this settings object. In
    Docker this value is supplied by the compose file. During local development,
    if no environment variable is set, the backend falls back to the local
    Postgres URL below.
    """

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/spike"
    )
    AWS_REGION: str = os.getenv("AWS_REGION", "ap-southeast-2")
    AUTH_PROVIDER: str = os.getenv("AUTH_PROVIDER", "legacy").strip().lower()
    COGNITO_USER_POOL_ID: str = os.getenv("COGNITO_USER_POOL_ID", "").strip()
    COGNITO_APP_CLIENT_ID: str = os.getenv("COGNITO_APP_CLIENT_ID", "").strip()
    COGNITO_ISSUER: str = os.getenv("COGNITO_ISSUER", "").strip()
    COGNITO_JWKS_CACHE_SECONDS: int = int(
        os.getenv("COGNITO_JWKS_CACHE_SECONDS", "300")
    )
    COGNITO_LINK_EXISTING_BY_EMAIL: bool = (
        os.getenv("COGNITO_LINK_EXISTING_BY_EMAIL", "false").lower() == "true"
    )
    DATABASE_URL_PARAMETER: str = os.getenv("DATABASE_URL_PARAMETER", "")
    REDDIT_CLIENT_ID_PARAMETER: str = os.getenv(
        "REDDIT_CLIENT_ID_PARAMETER",
        "",
    )
    REDDIT_CLIENT_SECRET_PARAMETER: str = os.getenv(
        "REDDIT_CLIENT_SECRET_PARAMETER",
        "",
    )
    PUBLIC_DISCUSSION_FEED_URLS_PARAMETER: str = os.getenv(
        "PUBLIC_DISCUSSION_FEED_URLS_PARAMETER",
        "",
    )
    DISCOVERY_QUEUE_URL: str = os.getenv("DISCOVERY_QUEUE_URL", "")
    ANALYSIS_QUEUE_URL: str = os.getenv("ANALYSIS_QUEUE_URL", "")
    NOTIFICATIONS_ENABLED: bool = (
        os.getenv("NOTIFICATIONS_ENABLED", "false").lower() == "true"
    )
    NOTIFICATIONS_DRY_RUN: bool = (
        os.getenv("NOTIFICATIONS_DRY_RUN", "false").lower() == "true"
    )
    ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED: bool = (
        os.getenv("ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED", "false").lower()
        == "true"
    )
    NOTIFICATION_QUEUE_URL: str = os.getenv("NOTIFICATION_QUEUE_URL", "")
    ALERT_SENDER_EMAIL: str = os.getenv("ALERT_SENDER_EMAIL", "")
    ALERT_SENDER_NAME: str = os.getenv("ALERT_SENDER_NAME", "Stocks In Hand")
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    BREVO_API_KEY_PARAMETER: str = os.getenv("BREVO_API_KEY_PARAMETER", "")
    BREVO_API_BASE_URL: str = os.getenv(
        "BREVO_API_BASE_URL",
        "https://api.brevo.com/v3",
    )
    ALERT_DAILY_BUDGET: int = _env_int(
        "ALERT_DAILY_BUDGET",
        180,
        minimum=0,
    )
    ALERT_MAX_PER_INVESTOR_PER_RUN: int = _env_int(
        "ALERT_MAX_PER_INVESTOR_PER_RUN",
        5,
        minimum=1,
    )
    ALERT_DEFAULT_MIN_CONFIDENCE: float = _env_confidence(
        "ALERT_DEFAULT_MIN_CONFIDENCE",
        0.75,
    )
    ALERT_CLAIM_STALE_MINUTES: int = _env_int(
        "ALERT_CLAIM_STALE_MINUTES",
        15,
        minimum=1,
    )
    ALERT_VERIFICATION_TOKEN_TTL_HOURS: int = _env_int(
        "ALERT_VERIFICATION_TOKEN_TTL_HOURS",
        24,
        minimum=1,
    )
    FRONTEND_BASE_URL: str = os.getenv(
        "FRONTEND_BASE_URL",
        "http://localhost:3000",
    )
    SOURCE_URLS: dict[str, str] = {
        ticker: os.getenv(f"{ticker}_SOURCE_URL", str(source.source_url))
        for ticker, source in SOURCES.items()
    }
    SUPPORTED_TICKERS: list[str] = [
        ticker.strip().upper()
        for ticker in os.getenv(
            "SUPPORTED_TICKERS",
            ",".join(SOURCES),
        ).split(",")
        if ticker.strip()
    ]
    SCHEDULED_TICKERS: list[str] = [
        ticker.strip().upper()
        for ticker in os.getenv(
            "SCHEDULED_TICKERS",
            ",".join(SOURCES),
        ).split(",")
        if ticker.strip()
    ]
    DISCOVERY_LOOKBACK_DAYS: int = int(
        os.getenv("DISCOVERY_LOOKBACK_DAYS", "30")
    )
    MAX_DOCUMENTS_PER_RUN: int = int(
        os.getenv("MAX_DOCUMENTS_PER_RUN", "3")
    )
    MAX_DOCUMENT_BYTES: int = int(
        os.getenv("MAX_DOCUMENT_BYTES", "10485760")
    )
    MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "100"))
    MAX_OCR_PAGES: int = int(os.getenv("MAX_OCR_PAGES", "5"))
    MAX_ANALYSIS_CHARS: int = int(
        os.getenv("MAX_ANALYSIS_CHARS", "50000")
    )
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv(
        "REDDIT_USER_AGENT",
        "windows:stocks-in-hand:1.0.0 (read-only ASX market research)",
    )
    BLUESKY_IDENTIFIER: str = os.getenv("BLUESKY_IDENTIFIER", "")
    BLUESKY_APP_PASSWORD: str = os.getenv("BLUESKY_APP_PASSWORD", "")
    BLUESKY_SERVICE_URL: str = os.getenv(
        "BLUESKY_SERVICE_URL",
        "https://bsky.social",
    ).rstrip("/")
    BLUESKY_PUBLIC_API_URL: str = os.getenv(
        "BLUESKY_PUBLIC_API_URL",
        "https://public.api.bsky.app",
    ).rstrip("/")
    PUBLIC_DISCUSSION_FEED_URLS: list[str] = [
        url.strip()
        for url in os.getenv("PUBLIC_DISCUSSION_FEED_URLS", "").split(",")
        if url.strip()
    ]
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    FINBERT_MODEL: str = os.getenv("FINBERT_MODEL", "/app/finbert")
    MARKETAUX_API_TOKEN: str = _first_env(
        "MARKETAUX_API_TOKEN",
        "MARKETAUX_API_KEY",
    )
    MARKETAUX_BASE_URL: str = os.getenv(
        "MARKETAUX_BASE_URL",
        "https://api.marketaux.com/v1",
    )
    NEWS_FETCH_LIMIT: int = int(os.getenv("NEWS_FETCH_LIMIT", "10"))

    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "stonks_session")
    SESSION_EXPIRE_DAYS: int = int(os.getenv("SESSION_EXPIRE_DAYS", "7"))
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax")

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

settings = Settings()

if settings.AUTH_PROVIDER not in {"legacy", "dual", "cognito"}:
    raise ValueError("AUTH_PROVIDER must be 'legacy', 'dual', or 'cognito'")

if settings.AUTH_PROVIDER in {"dual", "cognito"}:
    missing_cognito_settings = [
        name
        for name in ("COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID")
        if not getattr(settings, name)
    ]
    if missing_cognito_settings:
        raise ValueError(
            "Cognito authentication requires: "
            + ", ".join(missing_cognito_settings)
        )
    if settings.COGNITO_JWKS_CACHE_SECONDS <= 0:
        raise ValueError("COGNITO_JWKS_CACHE_SECONDS must be greater than zero")
