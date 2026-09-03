"""Application settings management.

This module defines a single, typed, validated source of truth for every
configuration value the application needs. All other modules must obtain
configuration through :func:`get_settings` — no module should call
``os.environ`` or read ``.env`` directly. Centralizing configuration this
way means:

* Every setting is type-checked and validated once, at startup, instead of
  failing deep inside unrelated code paths at request time.
* Settings are trivially mockable in tests (override environment variables
  or monkeypatch :func:`get_settings`).
* `.env` file loading, defaults, and env-var precedence are defined in
  exactly one place.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment the application is running in.

    Used to toggle environment-specific behavior (e.g. verbose logging,
    auto-reload, permissive CORS) without scattering ``if env == "dev"``
    checks throughout the codebase.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Supported logging verbosity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Root application settings.

    Values are loaded, in order of precedence, from:

    1. Actual environment variables (highest precedence — e.g. set by
       Docker/Kubernetes at deploy time).
    2. A local ``.env`` file (used in development).
    3. The field defaults declared below (lowest precedence, and only
       used for genuinely optional settings — secrets have no defaults
       and will raise a validation error at startup if missing).

    Attributes are grouped by concern with a comment header per group so
    the class stays navigable as it grows.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------
    APP_NAME: str = "Jira Sprint Intelligence Bot"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    LOG_LEVEL: LogLevel = LogLevel.INFO
    API_V1_PREFIX: str = "/api/v1"

    # --- CORS ------------------------------------------------------------
    # Stored as a raw comma-separated string, not list[str]. pydantic-settings
    # attempts to JSON-decode any complex-typed (list/dict) env var before
    # validators run, which breaks on a plain "a,b,c" value. Keeping this as
    # `str` and exposing `cors_origins` (below) as the parsed list sidesteps
    # that entirely, without depending on decoding behavior that varies by
    # pydantic-settings version.
    CORS_ORIGINS: str = ""

    # --- Security / JWT ---------------------------------------------------
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- MySQL Database ----------------------------------------------------
    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # --- Redis -------------------------------------------------------------
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_MAX_CONNECTIONS: int = 20

    # --- ChromaDB ------------------------------------------------------------
    CHROMA_HOST: str
    CHROMA_PORT: int = 8000
    CHROMA_COLLECTION_COMMENTS: str = "ticket_comments"
    CHROMA_COLLECTION_RETROS: str = "retro_notes"

    # --- Gemini API ----------------------------------------------------------
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_MAX_OUTPUT_TOKENS: int = 2048
    GEMINI_TIMEOUT_SECONDS: int = 30
    GEMINI_MAX_RETRIES: int = 3

    # --- Rate limiting / quotas ---------------------------------------------
    AI_DAILY_QUERY_QUOTA_PER_USER: int = 100
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # --- Validators ----------------------------------------------------------
    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key_strength(cls, value: str) -> str:
        """Fail fast on an obviously weak or placeholder secret key.

        A weak JWT signing key is a critical security failure that should
        never reach production silently. Raising here means the app
        refuses to start rather than start insecurely.
        """
        if len(value) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters long. "
                "Generate one with: openssl rand -hex 32"
            )
        return value

    # --- Derived helpers -------------------------------------------------
    @property
    def cors_origins(self) -> list[str]:
        """Parse ``CORS_ORIGINS`` into a list, trimming whitespace per entry."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        """Assemble the async SQLAlchemy connection URL for MySQL.

        Kept as a computed property rather than a stored env var so the
        individual DB_* components remain the single source of truth —
        there is exactly one place that knows how to build a valid DSN.
        """
        return (
            f"mysql+asyncmy://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def redis_url(self) -> str:
        """Assemble the Redis connection URL."""
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def is_production(self) -> bool:
        """Convenience flag for environment-gated behavior."""
        return self.ENVIRONMENT is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, process-wide :class:`Settings` instance.

    ``lru_cache`` ensures the ``.env`` file and environment are parsed
    exactly once per process, and that every caller — route handlers,
    services, startup hooks — shares the same validated settings object.
    This function is the only supported entry point for reading
    configuration and is designed to be used as a FastAPI dependency:

    .. code-block:: python

        from fastapi import Depends
        from app.core.config import Settings, get_settings

        @router.get("/example")
        async def example(settings: Settings = Depends(get_settings)) -> dict:
            return {"environment": settings.ENVIRONMENT}
    """
    return Settings()
