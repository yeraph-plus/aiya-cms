"""Smtp2Go email adapter (planned).

Target: ``inc.capabilities.notification.ports.NotificationProvider``.

Planned integration: Smtp2Go (smtp2go.com) transactional email API/SMTP.
Follows the same classification contract as ``email_smtp``: timeout ->
unknown (no blind resend), refused/authentication -> permanent, connect
failure -> transient. Do not implement until the provider contract is
frozen; this file must stay import-safe and side-effect free.
"""
