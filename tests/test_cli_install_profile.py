"""Installation profile boundary contracts."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from inc import cli


def test_admin_install_does_not_require_or_register_user_site_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.delenv("AIYA_SITE_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install", "--profile", "admin"])
    monkeypatch.setattr(cli, "_install_sync", lambda **kwargs: captured.update(kwargs) or 0)

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert captured["profile"] == "admin"
    assert captured["site_client_secret"] is None


def test_full_install_requires_user_site_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIYA_SITE_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install", "--profile", "full"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2


def test_admin_install_reads_optional_password_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.delenv("AIYA_SITE_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("AIYA_ADMIN_PASSWORD", "provided-password")
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install", "--profile", "admin"])
    monkeypatch.setattr(cli, "_install_sync", lambda **kwargs: captured.update(kwargs) or 0)

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert captured["admin_password"] == "provided-password"
