"""Mail kernel component."""

from .errors import MAIL_001, MAIL_002, MAIL_CODES
from .events import MAIL_EVENT_TYPES, MailSendFailedPayload
from .models import MailContext, MailOutbox, MailOutboxRead, MailStatus
from .registry import (
    MailTemplate,
    MailTemplateRegistry,
    clear_mail_template_registry,
    mail_template_registry,
    register_mail_template,
)
from .service import MailService, MailTransport, SMTPTransport
from .uow import MailUnitOfWork

__all__ = [
    "MAIL_001",
    "MAIL_002",
    "MAIL_CODES",
    "MAIL_EVENT_TYPES",
    "MailSendFailedPayload",
    "MailContext",
    "MailOutbox",
    "MailOutboxRead",
    "MailStatus",
    "MailTemplate",
    "MailTemplateRegistry",
    "mail_template_registry",
    "register_mail_template",
    "clear_mail_template_registry",
    "MailService",
    "MailTransport",
    "SMTPTransport",
    "MailUnitOfWork",
]
