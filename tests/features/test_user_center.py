"""User-center trusted catalogs, workflow topology and gateway contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from inc.features.user_center import (
    CHECK_IN_WORKFLOW_KEY,
    GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY,
    GIFT_CARD_POINTS_WORKFLOW_KEY,
    MEMBERSHIP_PURCHASE_WORKFLOW_KEY,
    POINT_PURCHASE_WORKFLOW_KEY,
    REFUND_WORKFLOW_KEY,
    GiftCardFulfillmentRegistry,
    GiftCardFulfillmentSpec,
    MembershipOfferRegistry,
    MembershipOfferSpec,
    PointBundleRegistry,
    PointBundleSpec,
    UserCenterService,
    UserCenterServiceContext,
    UserCenterWorkflowContext,
    behavior_specs,
    build_user_center_workflow_specs,
    notification_specs,
    spec,
)
from inc.kernel.errors import KernelError


def _catalogs() -> tuple[PointBundleRegistry, MembershipOfferRegistry, GiftCardFulfillmentRegistry]:
    bundles = PointBundleRegistry()
    bundles.register(
        PointBundleSpec(
            product_key="points.small",
            version="3",
            display_name="Small point bundle",
            price_cents=990,
            points_amount=100,
        )
    )
    offers = MembershipOfferRegistry()
    offers.register(
        MembershipOfferSpec(
            offer_key="membership.monthly",
            version="2",
            display_name="Monthly membership",
            level_key="pro",
            price_cents=1990,
        )
    )
    fulfillments = GiftCardFulfillmentRegistry(point_bundles=bundles, membership_offers=offers)
    fulfillments.register(
        GiftCardFulfillmentSpec(
            fulfillment_key="gift.points.small",
            payload_version="1",
            fulfillment_type="points_bundle",
            target_key="points.small",
            allowed_platforms=frozenset({"card_platform"}),
        )
    )
    fulfillments.register(
        GiftCardFulfillmentSpec(
            fulfillment_key="gift.membership.monthly",
            payload_version="1",
            fulfillment_type="membership_offer",
            target_key="membership.monthly",
            allowed_platforms=frozenset({"card_platform"}),
        )
    )
    bundles.freeze()
    offers.freeze()
    fulfillments.freeze()
    return bundles, offers, fulfillments


def test_single_feature_and_public_capability_import_boundary() -> None:
    assert spec.name == "user_center"
    assert set(spec.requires) == {
        "identity",
        "assets",
        "settings",
        "points",
        "membership",
        "gift_cards",
        "payments",
        "notification",
    }
    assert {item.key for item in behavior_specs} == {
        "user_center.check_in.credit.v1",
        "user_center.point_purchase.credit.v1",
        "user_center.membership_cycle.credit.v1",
    }
    assert [item.key for item in notification_specs] == ["usercenter.fulfillment_completed.v1"]

    root = Path(__file__).parents[2] / "inc" / "features" / "user_center"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (".models import", ".repository import", ".commands import", ".schemas import")
    assert not any(fragment in source for fragment in forbidden)
    assert "inc.features.check_in" not in source


def test_catalogs_freeze_and_validate_references() -> None:
    bundles, offers, fulfillments = _catalogs()
    assert bundles.frozen and offers.frozen and fulfillments.frozen
    assert bundles.require("points.small").price_cents == 990
    with pytest.raises(KernelError) as frozen:
        bundles.register(
            PointBundleSpec(
                product_key="points.late",
                version="1",
                display_name="Late",
                price_cents=1,
                points_amount=1,
            )
        )
    assert frozen.value.code == "user_center.registry_frozen"

    bad_fulfillments = GiftCardFulfillmentRegistry(point_bundles=bundles, membership_offers=offers)
    bad_fulfillments.register(
        GiftCardFulfillmentSpec(
            fulfillment_key="gift.unknown",
            payload_version="1",
            fulfillment_type="points_bundle",
            target_key="points.missing",
            allowed_platforms=frozenset({"card_platform"}),
        )
    )
    with pytest.raises(KernelError) as unknown:
        bad_fulfillments.freeze()
    assert unknown.value.code == "user_center.product_unavailable"


def test_all_workflows_have_stable_crash_recovery_boundaries() -> None:
    bundles, offers, fulfillments = _catalogs()
    context = UserCenterWorkflowContext(
        points_ctx=Any,
        membership_ctx=Any,
        payments=Any,
        points=Any,
        membership=Any,
        gift_cards_ctx=Any,
        gift_cards=Any,
        point_bundles=bundles,
        membership_offers=offers,
        gift_card_fulfillments=fulfillments,
    )
    workflows = {item.key: item for item in build_user_center_workflow_specs(ctx=context)}
    assert set(workflows) == {
        CHECK_IN_WORKFLOW_KEY,
        POINT_PURCHASE_WORKFLOW_KEY,
        MEMBERSHIP_PURCHASE_WORKFLOW_KEY,
        GIFT_CARD_POINTS_WORKFLOW_KEY,
        GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY,
        REFUND_WORKFLOW_KEY,
    }
    assert [item.key for item in workflows[POINT_PURCHASE_WORKFLOW_KEY].activities] == [
        "user_center.point_purchase.validate_captured.v1",
        "user_center.point_purchase.credit.v1",
        "user_center.point_purchase.notify.v1",
    ]
    assert [item.key for item in workflows[MEMBERSHIP_PURCHASE_WORKFLOW_KEY].activities] == [
        "user_center.membership_purchase.validate.v1",
        "user_center.membership_purchase.prepare_cycle.v1",
        "user_center.membership_purchase.credit_cycle.v1",
        "user_center.membership_purchase.attach_cycle.v1",
        "user_center.membership_purchase.notify.v1",
    ]
    assert [item.key for item in workflows[GIFT_CARD_POINTS_WORKFLOW_KEY].activities][-2:] == [
        "user_center.gift_card.points.commit.v1",
        "user_center.gift_card.points.notify.v1",
    ]
    membership_gift_steps = [
        item.key for item in workflows[GIFT_CARD_MEMBERSHIP_WORKFLOW_KEY].activities
    ]
    assert membership_gift_steps.index("user_center.gift_card.membership.attach_cycle.v1") < (
        membership_gift_steps.index("user_center.gift_card.membership.commit.v1")
    )
    assert [item.key for item in workflows[REFUND_WORKFLOW_KEY].activities] == [
        "user_center.refund.resolve_fact.v1",
        "user_center.refund.terminate_membership.v1",
        "user_center.refund.reverse_points.v1",
    ]
    assert all(item.version == "1" for item in workflows.values())
    assert len(
        {activity.key for workflow in workflows.values() for activity in workflow.activities}
    ) == sum(len(item.activities) for item in workflows.values())


@dataclass
class _Clock:
    def utc_now(self) -> datetime:
        return datetime(2026, 8, 19, tzinfo=UTC)


class _Runner:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []

    async def start(self, **values: Any) -> dict[str, Any]:
        self.starts.append(values)
        return values


class _PaymentCommand:
    calls: list[Any] = []

    def __init__(self, _ctx: Any) -> None:
        pass

    async def __call__(self, input_: Any) -> Any:
        self.calls.append(input_)
        return input_


def _service(runner: _Runner) -> UserCenterService:
    bundles, offers, fulfillments = _catalogs()
    context = UserCenterServiceContext(
        clock=_Clock(),
        runner=runner,
        identity_ctx=Any,
        identity=Any,
        points=Any,
        membership_ctx=Any,
        membership=Any,
        payments_ctx=Any,
        payments=Any,
        gift_cards_ctx=Any,
    )
    return UserCenterService(
        ctx=context,
        point_bundles=bundles,
        membership_offers=offers,
        gift_card_fulfillments=fulfillments,
    )


async def test_order_creation_uses_only_frozen_price_and_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inc.features.user_center import service as service_module

    _PaymentCommand.calls.clear()
    monkeypatch.setattr(service_module, "CreatePaymentOrder", _PaymentCommand)
    service = _service(_Runner())
    await service.create_point_order(
        subject_id="subject-1",
        product_key="points.small",
        provider_key="epay",
        idempotency_key="request-1",
    )
    created = _PaymentCommand.calls[-1]
    assert created.amount == 990
    assert created.currency == "CNY"
    assert created.offer_version == "3"
    assert created.subject_id == "subject-1"


async def test_gift_card_secret_never_enters_persistent_workflow_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inc.features.user_center import service as service_module

    class Reserve:
        def __init__(self, _ctx: Any) -> None:
            pass

        async def __call__(self, input_: Any) -> Any:
            assert input_.secret == "top-secret-card"
            return type(
                "Redemption",
                (),
                {"id": "redemption-1", "fulfillment_key": "gift.points.small"},
            )()

    runner = _Runner()
    monkeypatch.setattr(service_module, "ReserveGiftCardRedemption", Reserve)
    service = _service(runner)
    await service.redeem_gift_card(
        subject_id="subject-1",
        secret="top-secret-card",
        idempotency_key="request-2",
    )
    persisted = runner.starts[-1]["input_data"]
    assert persisted == {
        "redemption_id": "redemption-1",
        "redemption_key": "user-center:subject-1:request-2",
        "subject_id": "subject-1",
    }
    assert "top-secret-card" not in repr(runner.starts)
