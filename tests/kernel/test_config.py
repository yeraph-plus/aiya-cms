"""Config contract tests (foundation.md §1)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from inc.kernel.config import Settings, load_settings


def test_load_with_overrides() -> None:
    settings = load_settings(
        overrides={"database_url": "sqlite+aiosqlite:///tmp/test.db", "log_level": "DEBUG"}
    )
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///tmp/test.db"
    assert settings.log_level == "DEBUG"


def test_env_vars_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIYA_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("AIYA_LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.log_level == "WARNING"


def test_overrides_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIYA_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    settings = load_settings(overrides={"database_url": "sqlite+aiosqlite:///tmp/win.db"})
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///tmp/win.db"


def test_missing_required_config_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr(""))


def test_invalid_database_scheme_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings(overrides={"database_url": "mysql://localhost/db"})


def test_invalid_log_level_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings(overrides={"database_url": "sqlite+aiosqlite:///x.db", "log_level": "LOUD"})


def test_settings_are_immutable() -> None:
    settings = load_settings(overrides={"database_url": "sqlite+aiosqlite:///x.db"})
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_repr_redacts_secrets() -> None:
    settings = load_settings(
        overrides={"database_url": "postgresql+asyncpg://user:s3cr3t@localhost/db"}
    )
    assert "s3cr3t" not in repr(settings)
    assert "user" not in repr(settings)
