import os

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
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    FINBERT_MODEL: str = os.getenv("FINBERT_MODEL", "/app/finbert")
    
settings = Settings()
