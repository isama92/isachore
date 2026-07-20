from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import days_until_due, due_status, next_due
from app.core.households import member_household_ids
from app.models import Chore, CompletedChore, User
from app.schemas import DueChoreRead, HomeRead, ProgressRead

router = APIRouter()

# Chores due within this many days ahead show on the Home due view.
DUE_SOON_DAYS = 7


@router.get("", response_model=HomeRead)
async def get_home(user: CurrentUser, session: SessionDep) -> HomeRead:
    """The current user's due view: chores that are overdue, due today, or due
    within the next week, plus today's completion progress. Scoped to non-deleted
    chores in the user's active households that are assigned to the user or to
    nobody (chores assigned to other members are excluded)."""
    now = datetime.now(UTC)

    # Scaling note: next_due is derived from start_date + repeats + schedule_anchor
    # (with month/year clamping), so it can't be expressed in SQL and the due-window
    # filter runs in Python below. This loads every in-scope chore per request -
    # O(chores in the user's households), regardless of how few are actually due.
    # Fine for a household-sized app; revisit (e.g. a stored/materialised next_due)
    # if a household ever holds a large number of chores. The completion query below
    # stays bounded to today's rows for the in-scope chores.
    result = await session.execute(
        select(Chore).where(
            Chore.deleted_at.is_(None),
            Chore.household_id.in_(member_household_ids(user.id)),
            # "mine + unassigned": no assignees at all, or the current user is one.
            or_(~Chore.assignees.any(), Chore.assignees.any(User.id == user.id)),
        )
    )
    chores = result.scalars().all()

    scoped_ids = {chore.id for chore in chores}
    items: list[DueChoreRead] = []
    pending_ids: set[int] = set()  # overdue or due today, still not done
    for chore in chores:
        due = next_due(chore)
        if due is None:  # a completed one-off has no next occurrence
            continue
        days = days_until_due(due, now)
        if days <= 0:
            pending_ids.add(chore.id)
        if days <= DUE_SOON_DAYS:
            items.append(
                DueChoreRead(
                    id=chore.id,
                    title=chore.title,
                    repeats=chore.repeats,
                    next_due=due,
                    days_until_due=days,
                    status=due_status(days),
                )
            )
    items.sort(key=lambda item: (item.next_due, item.id))  # most overdue first

    # Today's progress. done_today = distinct in-scope chores completed today for
    # an occurrence that was due on or before today. Completions by ANY household
    # member count (a shared/unassigned chore someone else finished is still done
    # from this user's view); the scope is fixed by scoped_ids (mine + unassigned).
    # UTC day bounds (not a `::date` cast, which depends on the session TimeZone).
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)
    done_ids: set[int] = set()
    if scoped_ids:
        done_result = await session.execute(
            select(CompletedChore.chore_id)
            .where(
                CompletedChore.chore_id.in_(scoped_ids),
                CompletedChore.created_at >= today_start,
                CompletedChore.created_at < tomorrow_start,
                CompletedChore.scheduled_for < tomorrow_start,
            )
            .distinct()
        )
        done_ids = set(done_result.scalars().all())

    progress = ProgressRead(done_today=len(done_ids), total_today=len(pending_ids | done_ids))
    return HomeRead(progress=progress, items=items)
