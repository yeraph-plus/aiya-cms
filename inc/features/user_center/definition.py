"""Single feature declaration and owned behavior/notification specs."""

from pydantic import BaseModel, ConfigDict

from inc.capabilities.notification import NotificationSpec
from inc.capabilities.points import PointBehaviorSpec
from inc.features.user_center.workflows import (
    CHECK_IN_BEHAVIOR_KEY,
    MEMBERSHIP_CYCLE_BEHAVIOR_KEY,
    POINT_PURCHASE_BEHAVIOR_KEY,
)
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(
    name="user_center",
    version="1",
    requires=(
        "identity",
        "assets",
        "settings",
        "points",
        "membership",
        "gift_cards",
        "payments",
        "notification",
    ),
)

behavior_specs = (
    PointBehaviorSpec(
        key=CHECK_IN_BEHAVIOR_KEY,
        version="1",
        program_key="credit",
        direction="credit",
        fixed_amount=10,
        daily_limit=1,
        business_timezone="Asia/Shanghai",
        allowed_source_types=("user_center",),
    ),
    PointBehaviorSpec(
        key=POINT_PURCHASE_BEHAVIOR_KEY,
        version="1",
        program_key="credit",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("payment", "gift_card"),
    ),
    PointBehaviorSpec(
        key=MEMBERSHIP_CYCLE_BEHAVIOR_KEY,
        version="1",
        program_key="credit",
        direction="credit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("membership",),
    ),
)


class FulfillmentNotificationVariables(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    source_ref: str


notification_specs = (
    NotificationSpec(
        key="usercenter.fulfillment_completed.v1",
        version="1",
        channels=("email",),
        template_keys=("user_center_fulfillment_completed",),
        variables_schema=FulfillmentNotificationVariables,
        recipient_kind="identity",
    ),
)

__all__ = ["behavior_specs", "notification_specs", "spec"]
