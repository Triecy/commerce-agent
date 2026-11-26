"""Typed application settings loaded from environment variables (and `.env`).

Secrets come only from the environment (NFR-5). Variable names are flat and shared
with `deploy/compose.yml`, so one `.env` file configures both the app and the stack.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["dev", "test", "ci", "prod"]
LogFormat = Literal["json", "console"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Process-wide configuration. Construct via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: Environment = "dev"
    service_name: str = "commerce-agent"
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "commerce"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "commerce"

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)

    # Comma-separated in the environment, e.g. "http://localhost:3000,http://127.0.0.1:3000".
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Upper bound for each dependency probe in /readyz (enforced timeout, CLAUDE.md §7.3).
    readiness_timeout_s: float = Field(default=1.0, gt=0, le=10)

    # Database timeouts (enforced by asyncpg). Bulk loads in `make data` use the longer one.
    db_connect_timeout_s: float = Field(default=5.0, gt=0, le=60)
    db_statement_timeout_s: float = Field(default=30.0, gt=0, le=600)
    db_bulk_timeout_s: float = Field(default=600.0, gt=0, le=3600)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def postgres_dsn(self) -> str:
        """SQLAlchemy-style async DSN. Contains the password: never log it."""
        return "postgresql+asyncpg://" + self._postgres_location()

    @property
    def postgres_dsn_asyncpg(self) -> str:
        """Plain DSN for asyncpg.connect(). Contains the password: never log it."""
        return "postgresql://" + self._postgres_location()

    def _postgres_location(self) -> str:
        password = quote(self.postgres_password.get_secret_value(), safe="")
        user = quote(self.postgres_user, safe="")
        return f"{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance (call ``get_settings.cache_clear()`` in tests)."""
    return Settings()
