from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from commerce_agent.common.config import Settings, get_settings


def test_defaults_without_environment() -> None:
    s = Settings()
    assert s.app_env == "dev"
    assert s.postgres_port == 5432
    assert s.redis_port == 6379
    assert s.cors_allow_origins == []
    assert s.postgres_password.get_secret_value() == ""


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = Settings()
    assert (s.app_env, s.postgres_host, s.postgres_port, s.log_level) == ("ci", "db", 6543, "DEBUG")


def test_dotenv_file_is_loaded(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("REDIS_HOST=cache\nPOSTGRES_DB=shop\n")
    s = Settings()
    assert s.redis_host == "cache"
    assert s.postgres_db == "shop"


def test_environment_beats_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("REDIS_HOST=from-file\n")
    monkeypatch.setenv("REDIS_HOST", "from-env")
    assert Settings().redis_host == "from-env"


def test_cors_origins_are_split_from_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://a.test, http://b.test,")
    assert Settings().cors_allow_origins == ["http://a.test", "http://b.test"]


@pytest.mark.parametrize(
    ("name", "value"),
    [("APP_ENV", "staging"), ("POSTGRES_PORT", "70000"), ("LOG_FORMAT", "xml")],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_password_is_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cret-value")
    s = Settings()
    assert "s3cret-value" not in repr(s)
    assert "s3cret-value" in s.postgres_dsn


def test_settings_are_immutable() -> None:
    with pytest.raises(ValidationError):
        Settings().app_env = "prod"  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
