from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Household, household_members


async def add_to_default_household(session: AsyncSession, user_id: int) -> None:
    """Add a freshly created user to the default (lowest-id) household.

    Best-effort: no-op when no household exists yet (e.g. in tests that don't
    seed one). Real household management is a later feature; for now every user
    lands in the single household created by the initial migration.
    """
    household_id = (
        await session.execute(select(Household.id).order_by(Household.id).limit(1))
    ).scalar_one_or_none()
    if household_id is not None:
        await session.execute(
            insert(household_members).values(household_id=household_id, user_id=user_id)
        )
