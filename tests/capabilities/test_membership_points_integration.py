"""Membership's boundary from points is explicit and opaque."""

from __future__ import annotations

import inspect

from inc.capabilities.membership import CommandContext, ports


def test_membership_command_context_has_no_points_dependency() -> None:
    assert "points" not in inspect.signature(CommandContext).parameters
    assert "points_ledger" not in inspect.signature(CommandContext).parameters


def test_membership_exports_no_points_port_or_recording_adapter() -> None:
    assert ports.__all__ == []
    assert not hasattr(ports, "PointsLedgerPort")
    assert not hasattr(ports, "RecordingPointsLedger")
