"""Notification declarations: NotificationSpec and registry.

Contract source: context/spec/capabilities/notification.md §2.

NotificationSpec is an immutable code declaration registered by
capabilities/features. Templates and channels must be declared here; the
registry fails fast on duplicate keys, unknown channels, invalid
sensitivity or non-Pydantic variable schemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")
_TEMPLATE_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
CHANNELS = ("email", "sms")
SENSITIVITIES = ("normal", "sensitive")
# Keep the worker retry budget in code so notification delivery does not rely
# on an environment-specific default.  Identity challenge notifications use
# this same budget explicitly in ``notification.auth``.
NOTIFICATION_DELIVERY_MAX_ATTEMPTS = 5
REGISTERED_TRIGGER_NAMES = frozenset({"identity.email_verification", "identity.password_reset"})


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    max_attempts: int = NOTIFICATION_DELIVERY_MAX_ATTEMPTS
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    unknown_requires_manual: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive")


@dataclass(frozen=True, slots=True)
class NotificationSpec:
    """Immutable trigger declaration owned by the notification capability."""

    key: str
    version: str
    channels: tuple[str, ...]
    template_keys: tuple[str, ...]
    variables_schema: type[BaseModel]
    recipient_kind: str = "identity"
    sensitivity: str = "normal"
    locale: str = "en"
    fallback_channels: tuple[str, ...] = ()
    delivery_policy: DeliveryPolicy = DeliveryPolicy()

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise ValueError(f"invalid notification key {self.key!r}")
        if not self.version:
            raise ValueError(f"notification {self.key} requires a version")
        unknown = set(self.channels) - set(CHANNELS)
        if unknown:
            raise ValueError(f"notification {self.key} declares unknown channels {sorted(unknown)}")
        if not self.channels:
            raise ValueError(f"notification {self.key} requires at least one channel")
        unknown_fallback = set(self.fallback_channels) - set(CHANNELS)
        if unknown_fallback:
            raise ValueError(
                f"notification {self.key} declares unknown fallback channels "
                f"{sorted(unknown_fallback)}"
            )
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(
                f"notification {self.key} has invalid sensitivity {self.sensitivity!r}"
            )
        if not self.template_keys:
            raise ValueError(f"notification {self.key} requires template keys")
        for template_key in self.template_keys:
            if not _TEMPLATE_KEY.match(template_key):
                raise ValueError(
                    f"notification {self.key} declares invalid template key {template_key!r}"
                )
        if not isinstance(self.variables_schema, type) or not issubclass(
            self.variables_schema, BaseModel
        ):
            raise ValueError(f"notification {self.key} requires a Pydantic variables schema")

    @property
    def trigger_name(self) -> str:
        """Public vocabulary used by callers; ``key`` is storage compatibility."""

        return self.key


class NotificationSpecRegistry:
    """notification key -> NotificationSpec; frozen after boot."""

    def __init__(self, *, allowed_triggers: frozenset[str] | None = None) -> None:
        self._specs: dict[str, NotificationSpec] = {}
        self._frozen = False
        self._allowed_triggers = (
            REGISTERED_TRIGGER_NAMES if allowed_triggers is None else allowed_triggers
        )

    def register(self, spec: NotificationSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"notification registry is frozen; cannot register {spec.key}",
            )
        if spec.trigger_name not in self._allowed_triggers:
            raise KernelError(
                code="notification.unknown_trigger",
                category=ErrorCategory.VALIDATION,
                message=f"notification trigger {spec.trigger_name!r} is not registered",
            )
        if spec.key in self._specs:
            raise KernelError(
                code="notification.duplicate_spec",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate notification spec {spec.key}",
            )
        self._specs[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, key: str) -> NotificationSpec:
        spec = self._specs.get(key)
        if spec is None:
            raise KernelError(
                code="notification.unknown_spec",
                category=ErrorCategory.INTERNAL,
                message=f"notification spec {key!r} is not registered",
            )
        return spec

    def require_trigger(self, trigger_name: str) -> NotificationSpec:
        try:
            return self.require(trigger_name)
        except KernelError as exc:
            if exc.code == "notification.unknown_spec":
                raise KernelError(
                    code="notification.unknown_trigger",
                    category=ErrorCategory.VALIDATION,
                    message=f"notification trigger {trigger_name!r} is not registered",
                ) from exc
            raise

    def specs(self) -> tuple[NotificationSpec, ...]:
        return tuple(self._specs.values())
