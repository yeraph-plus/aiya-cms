"""Identity challenge notifications owned by the notification capability.

Identity creates and consumes one-time challenges.  This module owns the
notification vocabulary, templates, and delivery command used by the API
composition root to trigger those messages.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from inc.capabilities.notification.commands import CommandContext, RequestNotification
from inc.capabilities.notification.models import NotificationTemplate
from inc.capabilities.notification.schemas import RequestNotificationInput
from inc.capabilities.notification.specs import (
    NOTIFICATION_DELIVERY_MAX_ATTEMPTS,
    DeliveryPolicy,
    NotificationSpec,
)
from inc.kernel.db import UoWFactory

# Password-reset requests are rate limited to five per hour at the HTTP
# boundary.  Keep the challenge-message delivery budget at the same explicit
# value without importing the API layer into this capability.
AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS = NOTIFICATION_DELIVERY_MAX_ATTEMPTS
_AUTH_CHALLENGE_DELIVERY_POLICY = DeliveryPolicy(max_attempts=AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS)


class AuthChallengeVariables(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    token: str = Field(min_length=1, max_length=512)
    expires_at: datetime


class AuthChallengeInput(BaseModel):
    """Public trigger DTO; token is consumed only by notification delivery."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    purpose: Literal["email_verification", "password_reset"]
    username: str
    token: str = Field(min_length=1, max_length=512)
    expires_at: datetime


AUTH_NOTIFICATION_SPECS: tuple[NotificationSpec, ...] = (
    NotificationSpec(
        key="identity.email_verification.v1",
        version="1",
        channels=("email",),
        template_keys=("identity_email_verification",),
        variables_schema=AuthChallengeVariables,
        locale="zh-CN",
        sensitivity="sensitive",
        delivery_policy=_AUTH_CHALLENGE_DELIVERY_POLICY,
    ),
    NotificationSpec(
        key="identity.password_reset.v1",
        version="1",
        channels=("email",),
        template_keys=("identity_password_reset",),
        variables_schema=AuthChallengeVariables,
        locale="zh-CN",
        sensitivity="sensitive",
        delivery_policy=_AUTH_CHALLENGE_DELIVERY_POLICY,
    ),
)


@dataclass(frozen=True, slots=True)
class NotificationTemplateSeed:
    template_key: str
    subject: str
    body: str
    locale: str = "zh-CN"
    version: str = "1"
    channel: str = "email"
    variables_schema_version: str = "1"


AUTH_NOTIFICATION_TEMPLATES: tuple[NotificationTemplateSeed, ...] = (
    NotificationTemplateSeed(
        template_key="identity_email_verification",
        subject="验证邮箱",
        body="你好 {username}，你的邮箱验证码是：{token}。有效期至 {expires_at}。",
    ),
    NotificationTemplateSeed(
        template_key="identity_password_reset",
        subject="重置密码",
        body="你好 {username}，你的密码重置令牌是：{token}。有效期至 {expires_at}。",
    ),
)


class AuthChallengeNotifier:
    """Translate an identity challenge into one idempotent notification."""

    def __init__(self, context: CommandContext) -> None:
        self._context = context

    async def send(self, challenge: AuthChallengeInput, *, trace_id: str | None = None) -> None:
        context = replace(self._context, trace_id=trace_id)
        spec_key = f"identity.{challenge.purpose}.v1"
        await RequestNotification(context)(
            RequestNotificationInput(
                spec_key=spec_key,
                recipient_type="identity",
                recipient_id=challenge.subject_id,
                variables={
                    "username": challenge.username,
                    "token": challenge.token,
                    "expires_at": challenge.expires_at,
                },
                idempotency_key=(
                    f"identity-challenge:{challenge.purpose}:{_token_digest(challenge.token)}"
                ),
            )
        )


async def ensure_auth_templates(factory: UoWFactory) -> int:
    """Idempotently seed the built-in authentication templates."""

    created = 0
    async with factory() as uow:
        for seed in AUTH_NOTIFICATION_TEMPLATES:
            existing = (
                (
                    await uow.session.execute(
                        select(NotificationTemplate).where(
                            NotificationTemplate.template_key == seed.template_key,
                            NotificationTemplate.version == seed.version,
                            NotificationTemplate.channel == seed.channel,
                            NotificationTemplate.locale == seed.locale,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                continue
            uow.session.add(
                NotificationTemplate(
                    template_key=seed.template_key,
                    version=seed.version,
                    channel=seed.channel,
                    locale=seed.locale,
                    subject=seed.subject,
                    body=seed.body,
                    variables_schema_version=seed.variables_schema_version,
                    status="active",
                )
            )
            created += 1
        await uow.commit()
    return created


def _token_digest(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS",
    "AUTH_NOTIFICATION_SPECS",
    "AUTH_NOTIFICATION_TEMPLATES",
    "AuthChallengeInput",
    "AuthChallengeNotifier",
    "AuthChallengeVariables",
    "NotificationTemplateSeed",
    "ensure_auth_templates",
]
