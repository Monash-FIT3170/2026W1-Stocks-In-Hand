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
    DATABASE_URL_PARAMETER: str = os.getenv("DATABASE_URL_PARAMETER", "")
    DISCOVERY_QUEUE_URL: str = os.getenv("DISCOVERY_QUEUE_URL", "")
    SOURCE_URLS: dict[str, str] = {
        ticker: os.getenv(f"{ticker}_SOURCE_URL", source.source_url)
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
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    FINBERT_MODEL: str = os.getenv("FINBERT_MODEL", "/app/finbert")
    MARKETAUX_API_TOKEN: str = os.getenv("MARKETAUX_API_TOKEN", "")
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
