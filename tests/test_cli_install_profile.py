"""Single-release installation boundary contracts."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from inc import cli


def test_release_install_requires_user_site_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIYA_SITE_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2


def test_release_install_passes_the_single_composition_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("AIYA_SITE_OIDC_CLIENT_SECRET", "s" * 32)
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install"])
    monkeypatch.setattr(cli, "_install_sync", lambda **kwargs: captured.update(kwargs) or 0)

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert captured["site_client_secret"] == "s" * 32
    assert captured["site_base_url"] == "http://127.0.0.1:4321"


def test_release_install_reads_optional_password_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("AIYA_SITE_OIDC_CLIENT_SECRET", "s" * 32)
    monkeypatch.setenv("AIYA_ADMIN_PASSWORD", "provided-password")
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install"])
    monkeypatch.setattr(cli, "_install_sync", lambda **kwargs: captured.update(kwargs) or 0)

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert captured["admin_password"] == "provided-password"


def test_install_rejects_removed_profile_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIYA_SITE_OIDC_CLIENT_SECRET", "s" * 32)
    monkeypatch.setattr(sys, "argv", ["inc.cli", "install", "--profile", "cms"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
