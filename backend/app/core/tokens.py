from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken


async def purge_expired_tokens(session: AsyncSession) -> None:
    """Delete auth tokens whose TTL has elapsed.

    Expired tokens are already ignored at read time (see get_user_by_token), but
    without a sweep the table grows without bound (one row per login and per
    impersonation, 30-day TTL). Called opportunistically at login so cleanup
    rides on normal traffic without needing a cron job (L1).
    """
    await session.execute(delete(AuthToken).where(AuthToken.expires_at < datetime.now(UTC)))
