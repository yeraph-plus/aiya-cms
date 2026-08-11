"""Admin points adjust HTTP router tests.

Contract source: context/spec/http-openapi.md §2,
context/spec/capabilities/points.md §5/§9.

The cms manifest exposes the admin adjust endpoint behind the
``points.adjust`` grant; adjustments are idempotent per ``idempotency_key``.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
async def program(uow_factory: Any) -> None:
    from inc.capabilities.points.models import PointsProgram

    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="credit", display_name="Credit", unit="points", status="active"
            )
        )
        await uow.commit()


async def _register(uow_factory: Any, clock: Any, services: Any, username: str) -> Any:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    return await RegisterLocalUser(
        IdentityCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            hasher=services.hasher,
            outbox=services.outbox,
            audit_actor_id="system",
            audit_trace_id="test",
        )
    )(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
    )


async def _open_account(services: Any, uow_factory: Any, clock: Any, subject_id: str) -> None:
    from inc.capabilities.points.commands import (
        CommandContext as PointsCommandContext,
    )
    from inc.capabilities.points.commands import (
        OpenPointsAccount,
    )

    ctx = PointsCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=services.outbox,
        behaviors=services.behaviors,
        actor_id="system",
    )
    await OpenPointsAccount(ctx)(
        program_key="credit", subject_type="identity", subject_id=subject_id
    )


def _adjust_body(*, subject_id: str, amount: int, idempotency_key: str) -> dict[str, Any]:
    return {
        "subject_type": "identity",
        "subject_id": subject_id,
        "program_key": "credit",
        "amount": amount,
        "reason": "admin compensation",
        "idempotency_key": idempotency_key,
    }


async def test_adjust_credit_and_debit_balance(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "adjustee")
    await _open_account(services, uow_factory, clock, created.subject.id)
    headers = {"Authorization": f"Bearer {admin_token}"}

    credit = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=created.subject.id, amount=50, idempotency_key="adj-1"),
        headers=headers,
    )
    assert credit.status_code == 200, credit.text
    assert credit.json()["amount"] == 50
    assert credit.json()["entry_type"] == "adjustment"

    # balance is a self-service endpoint scoped to the caller, so read the
    # target subject's balance through the capability queries directly.
    from inc.capabilities.points.queries import PointsQueries

    queries = PointsQueries(uow_factory=uow_factory, behaviors=services.behaviors)
    after_credit = await queries.get_balance(
        program_key="credit", subject_type="identity", subject_id=created.subject.id
    )
    assert after_credit.balance == 50

    debit = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=created.subject.id, amount=-20, idempotency_key="adj-2"),
        headers=headers,
    )
    assert debit.status_code == 200, debit.text
    assert debit.json()["amount"] == -20

    after_debit = await queries.get_balance(
        program_key="credit", subject_type="identity", subject_id=created.subject.id
    )
    assert after_debit.balance == 30

    from tests.api.conftest import _mint_token_for

    user_token = await _mint_token_for(services, created.subject.id)
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {user_token}"})
    assert me.status_code == 200, me.text
    assert me.json()["points"]["balance"] == 30

    self_ledger = await client.get(
        "/api/v1/me/points/ledger",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert self_ledger.status_code == 200, self_ledger.text
    assert self_ledger.json()["total"] == 2
    assert [item["amount"] for item in self_ledger.json()["items"]] == [-20, 50]

    admin_ledger = await client.get(
        "/api/v1/admin/points/ledger",
        params={
            "subject_type": "identity",
            "subject_id": created.subject.id,
            "program_key": "credit",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_ledger.status_code == 200, admin_ledger.text
    view = admin_ledger.json()
    assert view["balance"]["balance"] == 30
    assert view["ledger"]["total"] == 2
    assert view["ledger"]["items"][0]["amount"] == -20
    assert view["ledger"]["items"][0]["metadata"]["reason"] == "admin compensation"
    assert view["buckets"]


async def test_adjust_is_idempotent_per_key(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "idem-adjust")
    await _open_account(services, uow_factory, clock, created.subject.id)
    headers = {"Authorization": f"Bearer {admin_token}"}

    body = _adjust_body(subject_id=created.subject.id, amount=100, idempotency_key="adj-idem")
    first = await client.post("/api/v1/admin/points/adjust", json=body, headers=headers)
    assert first.status_code == 200, first.text
    replay = await client.post("/api/v1/admin/points/adjust", json=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    from inc.capabilities.points.queries import PointsQueries

    queries = PointsQueries(uow_factory=uow_factory, behaviors=services.behaviors)
    balance = await queries.get_balance(
        program_key="credit", subject_type="identity", subject_id=created.subject.id
    )
    assert balance.balance == 100


async def test_self_points_reads_are_empty_without_opening_an_account(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    from sqlalchemy import func, select

    from inc.capabilities.points.models import PointsAccount

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "ledger-reader")
    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, created.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with uow_factory() as uow:
        before = (
            await uow.session.execute(select(func.count()).select_from(PointsAccount))
        ).scalar_one()

    me = await client.get("/api/v1/me", headers=headers)
    ledger = await client.get("/api/v1/me/points/ledger", headers=headers)

    assert me.status_code == 200
    assert me.json()["points"] == {"opened": False, "program_key": "credit", "balance": 0}
    assert ledger.status_code == 200
    assert ledger.json() == {"items": [], "total": 0, "page": 1, "size": 20}

    async with uow_factory() as uow:
        after = (
            await uow.session.execute(select(func.count()).select_from(PointsAccount))
        ).scalar_one()
    assert after == before


async def test_adjust_auto_opens_account_and_rejects_zero_amount(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "no-account")
    headers = {"Authorization": f"Bearer {admin_token}"}

    auto_opened = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=created.subject.id, amount=10, idempotency_key="adj-n1"),
        headers=headers,
    )
    assert auto_opened.status_code == 200, auto_opened.text
    assert auto_opened.json()["program_key"] == "credit"

    omitted_program = _adjust_body(
        subject_id=created.subject.id, amount=5, idempotency_key="adj-n3"
    )
    omitted_program.pop("program_key")
    defaulted = await client.post(
        "/api/v1/admin/points/adjust", json=omitted_program, headers=headers
    )
    assert defaulted.status_code == 200, defaulted.text
    assert defaulted.json()["program_key"] == "credit"

    zero = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=created.subject.id, amount=0, idempotency_key="adj-n2"),
        headers=headers,
    )
    assert zero.status_code == 422
    assert zero.json()["code"] == "points.zero_amount"


async def test_adjust_requires_capability_and_auth(
    client: Any, uow_factory: Any, clock: Any, program: None
) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "no-adjust")
    token = await _mint_token_for(services, created.subject.id)
    body = _adjust_body(subject_id=created.subject.id, amount=10, idempotency_key="adj-auth")

    assert (await client.post("/api/v1/admin/points/adjust", json=body)).status_code == 401
    denied = await client.post(
        "/api/v1/admin/points/adjust",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "api.forbidden"

    assert (
        await client.get(
            "/api/v1/admin/points/ledger",
            params={
                "subject_type": "identity",
                "subject_id": created.subject.id,
                "program_key": "credit",
            },
        )
    ).status_code == 401
    read_denied = await client.get(
        "/api/v1/admin/points/ledger",
        params={
            "subject_type": "identity",
            "subject_id": created.subject.id,
            "program_key": "credit",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read_denied.status_code == 403
    assert read_denied.json()["code"] == "api.forbidden"
