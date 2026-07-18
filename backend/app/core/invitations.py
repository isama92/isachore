"""Household-invitation maintenance: the expiry sweep and the expiry-time
rounding used at creation."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models import HouseholdInvitation, HouseholdInvitationStatus

logger = logging.getLogger(__name__)


def round_up_to_hour(dt: datetime) -> datetime:
    """Round a datetime up to the next whole hour (minute/second/microsecond 0).
    A datetime already exactly on the hour is returned unchanged, so an invite's
    lifetime is at least its TTL and at most an hour more."""
    truncated = dt.replace(minute=0, second=0, microsecond=0)
    if truncated == dt:
        return truncated
    return truncated + timedelta(hours=1)


async def mark_expired_invitations(session: AsyncSession) -> int:
    """Flip every `pending` invite whose `expires_at` has passed to `expired`.

    Runtime checks trust `status` (not the date), so this sweep is what actually
    retires a stale invite. Returns how many rows were flipped; does NOT commit
    (the caller owns the transaction, like the purges in core/tokens.py)."""
    result = await session.execute(
        update(HouseholdInvitation)
        .where(
            HouseholdInvitation.status == HouseholdInvitationStatus.pending,
            HouseholdInvitation.expires_at <= datetime.now(UTC),
        )
        .values(status=HouseholdInvitationStatus.expired)
    )
    return result.rowcount


async def run_expire_invitations() -> int:
    """Open a standalone session, run the sweep, commit. This is the entry point
    the hourly scheduler job and the `expire-invitations` CLI command share."""
    async with async_session_factory() as session:
        count = await mark_expired_invitations(session)
        await session.commit()
    if count:
        logger.info("expired %d stale household invitation(s)", count)
    return count
