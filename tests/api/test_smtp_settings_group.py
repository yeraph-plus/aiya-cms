"""SMTP settings mapping tests (no network).

Contract source: context/spec/adapters.md §3.1, context/spec/features.md §4.5.

``smtp_settings_from_group`` builds adapter connection settings from the
``site_settings`` ``notification`` settings group value; an empty host
must be rejected so the composition root can never bind an adapter that
cannot connect.
"""

from __future__ import annotations

import pytest

from inc.adapters.notification.email_smtp import (
    SmtpSettings,
    smtp_settings_from_group,
)
from inc.features.site_settings.definition import NotificationValueSchema


def test_mapper_builds_settings_from_notification_group_value() -> None:
    # The stored group value is the persisted dict (secrets unwrapped at the
    # settings capability boundary), not the schema's masked model_dump.
    group_value = NotificationValueSchema(
        smtp_host="mail.example.com",
        smtp_port=587,
        smtp_username="sender",
        smtp_password="s3cret",
        smtp_from_address="news@example.com",
        smtp_use_tls=True,
        smtp_starttls=False,
    ).model_dump()
    group_value["smtp_password"] = group_value["smtp_password"].get_secret_value()

    settings = smtp_settings_from_group(group_value)

    assert isinstance(settings, SmtpSettings)
    assert settings.host == "mail.example.com"
    assert settings.port == 587
    assert settings.username == "sender"
    assert settings.password == "s3cret"
    assert settings.from_address == "news@example.com"
    assert settings.use_tls is True
    assert settings.starttls is False


def test_mapper_builds_settings_from_stored_value_dict() -> None:
    """The real persisted group value (from the settings capability) carries the
    plaintext password that the adapter needs to authenticate."""
    settings = smtp_settings_from_group(
        {
            "smtp_host": "mail.example.com",
            "smtp_port": 587,
            "smtp_username": "sender",
            "smtp_password": "s3cret",
            "smtp_from_address": "news@example.com",
            "smtp_use_tls": True,
            "smtp_starttls": False,
        }
    )
    assert settings.password == "s3cret"


def test_mapper_applies_defaults_and_empty_credentials() -> None:
    settings = smtp_settings_from_group(
        NotificationValueSchema(smtp_host="mail.example.com").model_dump(mode="json")
    )
    assert settings.username is None
    assert settings.password is None
    assert settings.from_address == "no-reply@aiya.local"
    assert settings.port == 25


def test_mapper_rejects_missing_host() -> None:
    with pytest.raises(ValueError, match="smtp_host"):
        smtp_settings_from_group({})
    with pytest.raises(ValueError, match="smtp_host"):
        smtp_settings_from_group(NotificationValueSchema().model_dump(mode="json"))
