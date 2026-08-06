"""Red tests locking the logging component contract (M1.1).

Contract source: context/spec/kernel.md
"""

import json
import logging

import pytest
import structlog

from inc.kernel.config import Settings
from inc.kernel.logging import bind_context, get_logger, setup_logging


@pytest.fixture(autouse=True)
def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _last_json_line(capsys: pytest.CaptureFixture[str]) -> dict:
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_test_env_emits_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(Settings(_env_file=None, env="test"))

    get_logger("tests.logging").info("hello-world", extra=1)

    record = _last_json_line(capsys)
    assert record["event"] == "hello-world"
    assert "level" in record
    assert "timestamp" in record
    assert record["extra"] == 1


def test_bind_context_adds_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(Settings(_env_file=None, env="test"))

    bind_context(request_id="rid-abc")
    get_logger("tests.logging").info("with-rid")

    record = _last_json_line(capsys)
    assert record["request_id"] == "rid-abc"


def test_setup_logging_is_idempotent() -> None:
    setup_logging(Settings(_env_file=None, env="test"))
    handlers_before = len(logging.getLogger().handlers)

    setup_logging(Settings(_env_file=None, env="test"))

    assert len(logging.getLogger().handlers) == handlers_before
