"""Red tests locking the config component contract (M1.1).

Contract source: context/kernel/config.md
"""

from inc.kernel.config import Settings, get_settings


def test_defaults_construct_in_dev_without_env() -> None:
    settings = Settings(_env_file=None, env="dev")

    assert settings.env == "dev"
    assert settings.database_url == "postgresql+asyncpg://aiya:aiya@localhost:5432/aiya"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.log_level == "INFO"
    assert settings.jwt_access_ttl_seconds == 900
    assert settings.jwt_refresh_ttl_seconds == 1_209_600


def test_new_cookie_and_cors_fields_have_stable_defaults() -> None:
    settings = Settings(_env_file=None, env="dev")

    assert settings.cookie_name == "aiya_refresh"
    assert settings.cookie_secure is False
    assert "http://localhost:7000" in settings.cors_origins


def test_environment_variable_override_wins() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://override:override@localhost:5432/other",
    )

    assert settings.database_url.startswith("postgresql+asyncpg://override:")


def test_invalid_field_value_raises_validation_error() -> None:
    try:
        Settings(_env_file=None, jwt_access_ttl_seconds=-1)
    except ValueError:
        return
    raise AssertionError("negative access TTL must be rejected")


def test_prod_rejects_dev_default_jwt_secret() -> None:
    try:
        Settings(_env_file=None, env="prod", jwt_secret="dev-only-change-me")
    except ValueError:
        return
    raise AssertionError("prod must not run with the dev default JWT secret")


def test_prod_rejects_insecure_refresh_cookie() -> None:
    try:
        Settings(_env_file=None, env="prod", jwt_secret="a" * 32, cookie_secure=False)
    except ValueError:
        return
    raise AssertionError("prod must require cookie_secure=True")


def test_prod_allows_secure_cookie_with_real_secret() -> None:
    settings = Settings(_env_file=None, env="prod", jwt_secret="a" * 32, cookie_secure=True)

    assert settings.cookie_secure is True


def test_prod_rejects_empty_or_short_jwt_secret() -> None:
    for secret in ("", "short"):
        try:
            Settings(_env_file=None, env="prod", jwt_secret=secret, cookie_secure=True)
        except ValueError:
            continue
        raise AssertionError("prod must reject empty and short JWT secrets")


def test_prod_rejects_secret_that_is_one_character_plus_whitespace() -> None:
    try:
        Settings(_env_file=None, env="prod", jwt_secret="a" + " " * 31, cookie_secure=True)
    except ValueError:
        return
    raise AssertionError("prod must count non-whitespace JWT secret characters")


def test_get_settings_is_cached_singleton() -> None:
    assert get_settings() is get_settings()
