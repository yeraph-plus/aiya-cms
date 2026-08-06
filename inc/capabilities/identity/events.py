"""Identity events.

Contract source: context/spec/capabilities/identity.md §7.

Events carry only subject ids and minimal security metadata; never
passwords, challenge tokens or full profiles. Keys are the stable contract
consumed by OIDC session revocation handlers and notification workflows.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from inc.kernel.errors import validate_error_code


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str


class UserRegisteredPayload(_Payload):
    username: str
    email: str = Field(default="")


class EmailVerifiedPayload(_Payload):
    pass


class PasswordChangedPayload(_Payload):
    method: str  # change | reset


class UserBannedPayload(_Payload):
    reason: str | None = None


class UserUnbannedPayload(_Payload):
    pass


class UserDeletedPayload(_Payload):
    pass


IDENTITY_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "identity.user_registered.v1": UserRegisteredPayload,
    "identity.email_verified.v1": EmailVerifiedPayload,
    "identity.password_changed.v1": PasswordChangedPayload,
    "identity.user_banned.v1": UserBannedPayload,
    "identity.user_unbanned.v1": UserUnbannedPayload,
    "identity.user_deleted.v1": UserDeletedPayload,
}

for _key in IDENTITY_EVENT_SCHEMAS:
    validate_error_code(_key)
