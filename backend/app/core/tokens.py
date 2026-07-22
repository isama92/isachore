from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, ConfirmationToken, TwoFactorChallenge


async def purge_expired_tokens(session: AsyncSession) -> None:
    """Delete auth tokens whose TTL has elapsed.

    Expired tokens are already ignored at read time (see get_user_by_token), but
    without a sweep the table grows without bound (one row per login and per
    impersonation, 30-day TTL). Called opportunistically at login so cleanup
    rides on normal traffic without needing a cron job (L1).
    """
    await session.execute(delete(AuthToken).where(AuthToken.expires_at < datetime.now(UTC)))


async def purge_expired_confirmation_tokens(session: AsyncSession) -> None:
    """Delete confirmation tokens whose TTL has elapsed. Same opportunistic
    sweep as purge_expired_tokens; called when a confirmation link is used."""
    await session.execute(
        delete(ConfirmationToken).where(ConfirmationToken.expires_at < datetime.now(UTC))
    )


async def purge_expired_two_factor_challenges(session: AsyncSession) -> None:
    """Delete 2FA login challenges whose short TTL has elapsed. Same
    opportunistic sweep; called when a new challenge is issued at login."""
    await session.execute(
        delete(TwoFactorChallenge).where(TwoFactorChallenge.expires_at < datetime.now(UTC))
    )
