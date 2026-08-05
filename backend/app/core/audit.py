"""Audit trail for auth, impersonation and admin user-management (M3).

`record_event` appends an AuditEvent to the caller's session (the caller commits
it as part of the surrounding transaction) and emits a structured log line. It
never raises for the logging side.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditEvent

logger = logging.getLogger("app.audit")


def _loggable(detail: str | None) -> str | None:
    """`detail` with control characters replaced, for the log line only.

    The log line is one record per newline, so a `detail` containing CR or LF can forge a
    second record - including a plausible `audit action=login_success ...` line. Most callers
    pass something the app itself produced or pydantic validated, but not all: the SSO
    callback's `?error=` is a raw query parameter from an unauthenticated request, and an
    email claim comes from whatever the identity provider was told. That makes this a
    property of the formatter rather than of any one caller.

    The stored column keeps the original: the DB row is not line-oriented, so nothing is
    forgeable there, and truncating what an operator can query would be the worse trade.
    """
    if detail is None:
        return None
    return "".join(ch if ch.isprintable() else f"\\x{ord(ch):02x}" for ch in detail)


async def record_event(
    session: AsyncSession,
    *,
    action: AuditAction,
    actor_id: int | None = None,
    target_id: int | None = None,
    impersonator_id: int | None = None,
    ip: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_id,
            target_user_id=target_id,
            impersonator_user_id=impersonator_id,
            ip_address=ip,
            detail=detail,
        )
    )
    logger.info(
        "audit action=%s actor=%s target=%s impersonator=%s ip=%s detail=%s",
        action.value,
        actor_id,
        target_id,
        impersonator_id,
        ip,
        _loggable(detail),
    )
