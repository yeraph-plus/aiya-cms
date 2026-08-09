"""Config contract tests (foundation.md §1)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from inc.kernel.config import Settings, load_settings


def _clear_pg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate an unconfigured environment for fail-fast tests.

    Compose and CI inject AIYA_PG_*/AIYA_REDIS_* variables; the "missing
    config must fail" contract only holds when none of them are present.
    """

    for key in (
        "AIYA_PG_HOST",
        "AIYA_PG_PORT",
        "AIYA_PG_USER",
        "AIYA_PG_PASSWORD",
        "AIYA_PG_DATABASE",
        "AIYA_REDIS_HOST",
        "AIYA_REDIS_PORT",
        "AIYA_REDIS_DB",
        "AIYA_REDIS_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_with_overrides() -> None:
    settings = load_settings(
        overrides={"database_url": "sqlite+aiosqlite:///tmp/test.db", "log_level": "DEBUG"}
    )
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///tmp/test.db"
    assert settings.log_level == "DEBUG"


def test_decomposed_pg_fields_assemble_url() -> None:
    settings = Settings(
        pg_host="db.internal", pg_port=6432, pg_user="cms", pg_password="s3cr3t", pg_database="shop"
    )
    url = settings.database_url.get_secret_value()
    assert url.startswith("postgresql+asyncpg://cms:")
    assert "s3cr3t" in url
    assert "@db.internal:6432/shop" in url
    assert settings.redis_url.get_secret_value().startswith("redis://")


def test_explicit_database_url_wins_over_decomposed_fields() -> None:
    settings = Settings(pg_host="db.internal", database_url="sqlite+aiosqlite:///tmp/override.db")
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///tmp/override.db"


def test_decomposed_redis_fields_assemble_url() -> None:
    settings = Settings(
        pg_host="db.internal",
        redis_host="cache.internal",
        redis_port=6380,
        redis_db=2,
        redis_password="k",
    )
    assert settings.redis_url.get_secret_value() == "redis://:k@cache.internal:6380/2"


def test_env_vars_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIYA_PG_HOST", "db.internal")
    monkeypatch.setenv("AIYA_PG_USER", "cms")
    monkeypatch.setenv("AIYA_PG_PASSWORD", "s3cr3t")
    monkeypatch.setenv("AIYA_LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://cms:")
    assert settings.log_level == "WARNING"


def test_overrides_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIYA_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1/db")
    settings = load_settings(overrides={"database_url": "sqlite+aiosqlite:///tmp/win.db"})
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///tmp/win.db"


def test_missing_required_config_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_pg_env(monkeypatch)
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr(""))


def test_missing_database_url_fails_even_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIYA_DATABASE_URL", raising=False)
    _clear_pg_env(monkeypatch)
    # The empty default must be rejected by the validator even when the env
    # var is absent (validate_default), not silently accepted.
    with pytest.raises(ValidationError, match="database_url is required"):
        Settings()


def test_invalid_database_scheme_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings(overrides={"database_url": "mysql://127.0.0.1/db"})


def test_invalid_log_level_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings(overrides={"database_url": "sqlite+aiosqlite:///x.db", "log_level": "LOUD"})


def test_settings_are_immutable() -> None:
    settings = load_settings(overrides={"database_url": "sqlite+aiosqlite:///x.db"})
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_repr_redacts_secrets() -> None:
    settings = load_settings(
        overrides={
            "pg_host": "db.internal",
            "pg_user": "user",
            "pg_password": "s3cr3t",
            "redis_password": "r4d4r",
        }
    )
    assert "s3cr3t" not in repr(settings)
    assert "r4d4r" not in repr(settings)
