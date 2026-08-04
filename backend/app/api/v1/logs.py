from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.household_log import LOG_RETENTION
from app.core.households import owned_household_ids
from app.models import Household, HouseholdLogAction, HouseholdLogEntry, User
from app.schemas import LogEntryRead, Page
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()

# One whitelisted sort key, and it still goes through a Literal + map: `useServerTable` always
# sends a sort key, and a column's id IS that key, so the pair has to exist for the default to
# be legal and for anything else to be a 422 rather than a KeyError. The other columns are
# joins or unsorted on the client for the same reason.
LogSortBy = Literal["created_at"]

LOG_SORT_COLUMNS = {"created_at": (HouseholdLogEntry.created_at,)}


@router.get("", response_model=Page[LogEntryRead])
async def list_log_entries(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: LogSortBy = "created_at",
    sort_dir: SortDir = "desc",
    household_id: Annotated[int | None, Query(ge=1)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    action: HouseholdLogAction | None = None,
) -> Page[LogEntryRead]:
    """The activity log of every active household the caller OWNS, newest first.

    Ownership rather than a role: an organiser manages the chores, and this is the record of
    that management, so it answers to whoever the household belongs to. A non-owner - organiser
    included - gets an empty page rather than a 403, because the list spans several households
    at once and narrowing is what that surface does. Same for `household_id` naming a household
    they do not own, and `user_id` narrows by the *actor*.
    """
    actor = aliased(User)
    target = aliased(User)
    filters = [
        HouseholdLogEntry.household_id.in_(owned_household_ids(user.id)),
        # The retention promise as a query predicate, not only as a prune: an entry past the
        # window is invisible even on a deploy where the daily job has never once run.
        HouseholdLogEntry.created_at >= datetime.now(UTC) - LOG_RETENTION,
    ]
    if household_id is not None:
        filters.append(HouseholdLogEntry.household_id == household_id)
    if user_id is not None:
        filters.append(HouseholdLogEntry.actor_user_id == user_id)
    if action is not None:
        filters.append(HouseholdLogEntry.action == action)

    total = (
        await session.scalar(select(func.count()).select_from(HouseholdLogEntry).where(*filters))
        or 0
    )

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in LOG_SORT_COLUMNS[sort_by]]
    order_by.append(HouseholdLogEntry.id.desc() if descending else HouseholdLogEntry.id.asc())

    result = await session.execute(
        select(HouseholdLogEntry, Household, actor, target)
        .join(Household, Household.id == HouseholdLogEntry.household_id)
        # Three references to users on this row, so each join names its own foreign key. Outer,
        # because a hard-deleted account leaves the column NULL and a row still has to read.
        .outerjoin(actor, actor.id == HouseholdLogEntry.actor_user_id)
        .outerjoin(target, target.id == HouseholdLogEntry.target_user_id)
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        LogEntryRead(
            id=entry.id,
            action=entry.action,
            created_at=entry.created_at,
            household=ChoreHouseholdRead.model_validate(household),
            actor=HouseholdMemberRead.model_validate(actor_row) if actor_row else None,
            target=HouseholdMemberRead.model_validate(target_row) if target_row else None,
            chore_id=entry.chore_id,
            chore_title=entry.chore_title,
            changed_fields=entry.changed_fields or [],
            # The identity stays in the table; the household is told only that an admin session
            # was behind it.
            by_admin=entry.impersonator_user_id is not None,
        )
        for entry, household, actor_row, target_row in result.all()
    ]
    return Page[LogEntryRead](items=items, total=total, page=page, page_size=page_size)
