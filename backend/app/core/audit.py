"""Audit trail for auth, impersonation and admin user-management (M3).

`record_event` appends an AuditEvent to the caller's session (the caller commits
it as part of the surrounding transaction) and emits a structured log line. It
never raises for the logging side.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditEvent

logger = logging.getLogger("app.audit")


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
        detail,
    )
