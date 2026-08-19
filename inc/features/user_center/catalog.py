"""Trusted product and fulfillment declarations for user-center flows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)*$")


def _validate_key(value: str, field: str) -> None:
    if not value or not _KEY.fullmatch(value):
        raise ValueError(f"invalid {field} {value!r}")


@dataclass(frozen=True, slots=True)
class PointBundleSpec:
    product_key: str
    version: str
    display_name: str
    price_cents: int
    points_amount: int
    available: bool = True
    available_from: datetime | None = None
    available_until: datetime | None = None
    per_subject_limit: int | None = None
    refund_policy_version: str = "1"
    currency: Literal["CNY"] = "CNY"
    program_key: Literal["credit"] = "credit"
    behavior_key: Literal["user_center.point_purchase.credit.v1"] = (
        "user_center.point_purchase.credit.v1"
    )

    def __post_init__(self) -> None:
        _validate_key(self.product_key, "product key")
        if not self.version or not self.display_name or not self.refund_policy_version:
            raise ValueError("bundle version, display name and refund policy are required")
        if self.price_cents <= 0 or self.points_amount <= 0:
            raise ValueError("bundle price and points must be positive")
        if self.per_subject_limit is not None and self.per_subject_limit <= 0:
            raise ValueError("per-subject limit must be positive")
        if (
            self.available_from
            and self.available_until
            and self.available_from >= self.available_until
        ):
            raise ValueError("bundle availability window is invalid")


@dataclass(frozen=True, slots=True)
class MembershipOfferSpec:
    offer_key: str
    version: str
    display_name: str
    level_key: str
    price_cents: int
    purchase_allowed: bool = True
    renewal_allowed: bool = True
    available_from: datetime | None = None
    available_until: datetime | None = None
    refund_policy_version: str = "1"
    currency: Literal["CNY"] = "CNY"

    def __post_init__(self) -> None:
        _validate_key(self.offer_key, "offer key")
        _validate_key(self.level_key, "level key")
        if not self.version or not self.display_name or not self.refund_policy_version:
            raise ValueError("offer version, display name and refund policy are required")
        if self.price_cents <= 0:
            raise ValueError("offer price must be positive")
        if (
            self.available_from
            and self.available_until
            and self.available_from >= self.available_until
        ):
            raise ValueError("offer availability window is invalid")


@dataclass(frozen=True, slots=True)
class GiftCardFulfillmentSpec:
    fulfillment_key: str
    payload_version: str
    fulfillment_type: Literal["points_bundle", "membership_offer"]
    target_key: str
    allowed_platforms: frozenset[str]
    available_from: datetime | None = None
    available_until: datetime | None = None
    per_subject_limit: int | None = None

    def __post_init__(self) -> None:
        _validate_key(self.fulfillment_key, "fulfillment key")
        _validate_key(self.target_key, "fulfillment target key")
        if not self.payload_version or not self.allowed_platforms:
            raise ValueError("payload version and allowed platforms are required")
        if self.per_subject_limit is not None and self.per_subject_limit <= 0:
            raise ValueError("per-subject limit must be positive")
        if (
            self.available_from
            and self.available_until
            and self.available_from >= self.available_until
        ):
            raise ValueError("fulfillment availability window is invalid")


class FrozenRegistry[T]:
    """Explicit stable-key registry, immutable after startup validation."""

    kind = "user-center item"

    def __init__(self) -> None:
        self._items: dict[str, T] = {}
        self._frozen = False

    def _key(self, spec: T) -> str:
        raise NotImplementedError

    def register(self, spec: T) -> None:
        key = self._key(spec)
        if self._frozen:
            raise _error("user_center.registry_frozen", f"{self.kind} registry is frozen")
        if key in self._items:
            raise _error("user_center.duplicate_registration", f"duplicate {self.kind} {key}")
        self._items[key] = spec

    def freeze(self) -> None:
        self._validate()
        self._frozen = True

    def _validate(self) -> None:
        return None

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, key: str) -> T:
        item = self._items.get(key)
        if item is None:
            raise KernelError(
                code="user_center.product_unavailable",
                category=ErrorCategory.VALIDATION,
                message=f"unknown {self.kind}",
            )
        return item

    def specs(self) -> tuple[T, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


class PointBundleRegistry(FrozenRegistry[PointBundleSpec]):
    kind = "point bundle"

    def _key(self, spec: PointBundleSpec) -> str:
        return spec.product_key


class MembershipOfferRegistry(FrozenRegistry[MembershipOfferSpec]):
    kind = "membership offer"

    def _key(self, spec: MembershipOfferSpec) -> str:
        return spec.offer_key


class GiftCardFulfillmentRegistry(FrozenRegistry[GiftCardFulfillmentSpec]):
    kind = "gift-card fulfillment"

    def __init__(
        self,
        *,
        point_bundles: PointBundleRegistry,
        membership_offers: MembershipOfferRegistry,
    ) -> None:
        super().__init__()
        self._point_bundles = point_bundles
        self._membership_offers = membership_offers

    def _key(self, spec: GiftCardFulfillmentSpec) -> str:
        return spec.fulfillment_key

    def _validate(self) -> None:
        if not self._point_bundles.frozen or not self._membership_offers.frozen:
            raise _error(
                "user_center.registry_dependency_not_frozen",
                "product and offer registries must be frozen first",
            )
        for spec in self._items.values():
            registry = (
                self._point_bundles
                if spec.fulfillment_type == "points_bundle"
                else self._membership_offers
            )
            registry.require(spec.target_key)


def _error(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.INTERNAL, message=message)


__all__ = [
    "GiftCardFulfillmentRegistry",
    "GiftCardFulfillmentSpec",
    "MembershipOfferRegistry",
    "MembershipOfferSpec",
    "PointBundleRegistry",
    "PointBundleSpec",
]
