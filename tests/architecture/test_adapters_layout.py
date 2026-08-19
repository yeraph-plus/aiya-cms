"""Guards: adapter library structure and placeholder import safety.

Contract source: context/spec/adapters.md §2/§4/§6.

Adapters live under ``inc/adapters/<capability>/`` and are usable by both
``inc/api`` and ``inc/features``; planned integrations are side-effect-free
placeholders that declare their target Port. Importing any adapter directory
must not start connections, threads, routers or registries. Implemented
providers may import their SDKs lazily, but must still be side-effect-free at
module import time.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ADAPTER_DIRS = (
    ("notification", ("email_smtp", "smtp2go")),
    ("payments", ("paypal", "epay")),
    ("gift-cards", ("afdian",)),
    ("assets", ("s3",)),
    ("content", ("openlist",)),
)

PLACEHOLDERS = ()

IMPLEMENTED = (
    "inc.adapters.notification.email_smtp",
    "inc.adapters.notification.smtp2go",
    "inc.adapters.payments.paypal",
    "inc.adapters.payments.epay",
    "inc.adapters.assets.s3",
    "inc.adapters.content.openlist",
)


def test_adapters_live_at_inc_root() -> None:
    root = Path(__file__).resolve().parents[2] / "inc" / "adapters"
    assert root.is_dir(), "inc/adapters skeleton missing"
    assert not (Path(__file__).resolve().parents[2] / "inc" / "api" / "adapters").exists(), (
        "inc/api/adapters must not return; adapters moved to inc/adapters"
    )


def test_adapter_directories_match_spec_layout() -> None:
    root = Path(__file__).resolve().parents[2] / "inc" / "adapters"
    for capability, modules in ADAPTER_DIRS:
        directory = root / capability
        assert directory.is_dir(), f"missing adapter directory {directory}"
        for module in modules:
            assert (directory / f"{module}.py").is_file(), f"missing {capability}/{module}.py"


def test_placeholder_imports_are_side_effect_free() -> None:
    for module in PLACEHOLDERS:
        imported = importlib.import_module(module)
        source = Path(imported.__file__).read_text(encoding="utf-8")
        assert "import " not in source.split('"""', 2)[2], (
            f"placeholder {module} must not import anything yet"
        )


def test_email_smtp_adapter_imports_only_expected_dependencies() -> None:
    import inc.adapters.notification.email_smtp as adapter

    source = Path(adapter.__file__).read_text(encoding="utf-8")
    assert "aiosmtplib" in source
    assert "from inc.capabilities.notification.ports import" in source


def test_smtp2go_adapter_uses_requests_and_notification_port() -> None:
    import inc.adapters.notification.smtp2go as adapter

    source = Path(adapter.__file__).read_text(encoding="utf-8")
    assert "requests" in source
    assert "from inc.capabilities.notification.ports import" in source
