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

settings = Settings()
