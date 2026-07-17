import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings
from app.models import User

logger = logging.getLogger(__name__)

# Shared error detail when an email action is attempted without SMTP configured.
NO_SMTP_DETAIL = "There is no confirmation SMTP server configured"


def smtp_configured() -> bool:
    """Whether enough SMTP settings are present to send mail. Username/password
    are optional (a dev relay like mailpit needs neither), but a host and a From
    address are the minimum."""
    return bool(settings.smtp_host and settings.smtp_from)


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via the configured SMTP server. Raises
    aiosmtplib.SMTPException (or ValueError if SMTP isn't configured) on
    failure; callers decide whether that is fatal or best-effort."""
    if not smtp_configured():
        raise ValueError("SMTP is not configured")

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password or None,
        use_tls=settings.smtp_use_tls,
        # Pass the bool straight through (False must mean "never STARTTLS", not
        # aiosmtplib's None = "auto"). Force it off under implicit TLS, since
        # aiosmtplib rejects use_tls and start_tls both being true.
        start_tls=settings.smtp_starttls and not settings.smtp_use_tls,
    )


def _confirmation_link(raw_token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/confirm?token={raw_token}"


async def send_confirmation_email(user: User, raw_token: str) -> None:
    """Email a new (or resent) user the link to set their password and activate
    their account. English-only: the backend has no i18n and doesn't yet know
    the recipient's chosen language at creation time."""
    link = _confirmation_link(raw_token)
    body = (
        f"Hi {user.first_name},\n\n"
        "An isachore account has been created for you. To activate it, set your "
        "password using the link below:\n\n"
        f"{link}\n\n"
        "This link expires in 7 days. If you weren't expecting this, you can "
        "ignore this email.\n"
    )
    await send_email(user.email, "Confirm your isachore account", body)
