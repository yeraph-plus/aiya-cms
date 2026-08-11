"""Notification channel adapters.

Implement ``inc.capabilities.notification.ports.NotificationProvider``.
Both SMTP and SMTP2GO are import-safe and perform external work only from
their explicit ``send`` methods.
"""

from inc.adapters.notification.email_smtp import SmtpEmailAdapter
from inc.adapters.notification.smtp2go import Smtp2GoEmailAdapter

__all__ = ["Smtp2GoEmailAdapter", "SmtpEmailAdapter"]
