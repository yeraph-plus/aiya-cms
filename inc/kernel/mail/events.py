"""Mail domain events."""

from uuid import UUID

from pydantic import BaseModel

MAIL_EVENT_TYPES: tuple[str, ...] = ("mail.send_failed",)


class MailSendFailedPayload(BaseModel):
    mail_id: UUID
    to: str
    template: str
    attempts: int
