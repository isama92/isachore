"""Slot placement for materialised occurrences: the DB-touching layer over `core.chores`.

`core.chores` is pure and knows only where the grid falls. These helpers know which slots a
chore has actually used, which is what makes a computed slot safe to assign. They live here
rather than in `api/v1/chores.py` because two routers need them - the chores router and the
household one, which re-anchors slots when a household moves timezone - and the chores router
already imports from the household router, so the reverse would be a cycle.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.chores import RecurrenceRule, first_occurrence, next_slot_after
from app.core.households import household_zone
from app.models import Chore, ChoreOccurrence, OccurrenceStatus, RepeatPeriod


def rule_for(chore: Chore) -> RecurrenceRule:
    """The chore's recurrence rule, as the pure `core.chores` helpers want it."""
    return RecurrenceRule.of(chore.repeats, chore.repeat_interval, chore.weekdays)


def zone_for(chore: Chore) -> ZoneInfo:
    """The zone the chore's household reckons its days in, which every slot is anchored to
    (local midnight - see `core.chores`).

    Reads `chore.household`, so every path reaching this must have eagerly loaded it. All of
    them do: `_get_user_chore_or_404` and `_managed_chore_or_error` both `selectinload` it,
    the management list uses `contains_eager`, and `create_chore` resolves the household
    itself. In async SQLAlchemy a missed eager load raises `MissingGreenlet` rather than
    quietly issuing another query, so this fails loudly instead of degrading."""
    return household_zone(chore.household.timezone)


def initial_slot(
    start_date: date | None, rule: RecurrenceRule, now: datetime, tz: ZoneInfo
) -> datetime:
    """Where a chore's first open occurrence sits. A scheduled chore opens at local midnight
    on its start date; an unscheduled one has no start date and opens now, reading as
    "available since" rather than a deadline."""
    return first_occurrence(start_date, rule, tz) if start_date is not None else now


async def free_slot_from(
    session: AsyncSession,
    chore_id: int,
    candidate: datetime,
    rule: RecurrenceRule,
    tz: ZoneInfo,
) -> datetime:
    """`candidate`, advanced along the grid past every slot this chore has already completed.

    Re-dating a chore onto a grid it has history on can land exactly on one of its `done`
    rows, and `uq_occurrence_chore_scheduled` is per (chore, scheduled_for): the commit would
    fail and the caller would surface a 409 that retrying could never get past, because the
    same edit recomputes the same occupied slot every time. It used to be impossible - an
    open row's slot was always later than every done row's - but unscheduled chores broke
    that: one anchors its successors at completion timestamps, so a chore that was unscheduled
    for a while has done rows on both sides of its open one.

    Walking forward applies the same rule `advance_anchor` already does: a slot the chore has
    been completed for is not a slot it can be due for again. The rule always has an interval
    to step, since a candidate only exists when there is a start date (never `manual`), and it
    terminates because every step strictly advances while the done set is finite.

    The `taken` set holds UTC-aware rows straight from Postgres while `candidate` is anchored
    in the household's zone, and that mismatch is fine: aware datetimes hash and compare by
    the instant they name, not by how it is written, so membership is representation-blind.

    Note this is one of the two queries that deliberately does NOT filter out skipped rows
    (see `ChoreOccurrence.skipped`). The question here is which slots are *occupied*, not
    which produced work, and a skipped slot is every bit as occupied: excluding them would
    put the unclearable 409 above straight back.
    """
    taken = set(
        (
            await session.execute(
                select(ChoreOccurrence.scheduled_for).where(
                    ChoreOccurrence.chore_id == chore_id,
                    ChoreOccurrence.status == OccurrenceStatus.done,
                    ChoreOccurrence.scheduled_for >= candidate,
                )
            )
        )
        .scalars()
        .all()
    )
    slot = candidate
    while slot in taken:
        slot = next_slot_after(slot, rule, tz)
    return slot


async def reanchor_open_occurrences(
    session: AsyncSession, household_id: int, old_tz: ZoneInfo, new_tz: ZoneInfo
) -> int:
    """Move a household's open slots so they keep the local dates they already had, after the
    household changed timezone. Returns how many moved.

    The transform is the same one the timezone migration applies in SQL: read the slot's wall
    clock in the old zone, then say that reading was always local to the new one. A chore
    showing "due 5 August" before the change still shows "due 5 August" after it, which is the
    only reading of a zone change that does not silently re-date somebody's week.

    Three deliberate exclusions:

    - **Done rows.** History is a record of when things actually happened; re-anchoring it
      would rewrite the past to match a decision made afterwards. `completed_at` is untouched
      everywhere for the same reason.
    - **Unscheduled (`manual`) chores.** Their slot is the moment the chore was last completed
      ("available since"), not a calendar anchor, so it is already a correct instant.
    - **Soft-deleted chores.** Nothing shows them and nothing can complete them, so moving
      their slots is work with no observer - and it would collide with the restore path's own
      reconciliation if one is ever added.

    Every candidate goes through `free_slot_from` because the new instant can land exactly on
    a slot the chore has already completed, which `uq_occurrence_chore_scheduled` would turn
    into a 409 the caller cannot clear by retrying. Only `session.add` semantics here - the
    caller commits, matching `record_log_entry` and `record_event`.

    Deliberately N+1: one `free_slot_from` SELECT per open occurrence, all of them inside the
    lock. A conscious trade, not an oversight - a household has tens of chores, not thousands,
    and this runs when somebody edits a setting rather than on any read path. Collapsible to one
    query if it ever matters (fetch every `done` slot for the household's non-manual chores at or
    after `min(candidates)`, group by `chore_id`, then walk in memory), at the cost of
    duplicating the walk `free_slot_from` already owns.
    """
    rows = (
        (
            await session.execute(
                select(ChoreOccurrence)
                # to-one, so no row multiplication; `contains_eager` reuses this join to
                # populate `occ.chore` rather than costing a second query per row - and
                # without it `occ.chore.repeats` below would raise `MissingGreenlet`.
                .join(Chore, Chore.id == ChoreOccurrence.chore_id)
                .options(contains_eager(ChoreOccurrence.chore))
                .where(
                    Chore.household_id == household_id,
                    Chore.deleted_at.is_(None),
                    Chore.repeats != RepeatPeriod.manual,
                    ChoreOccurrence.status == OccurrenceStatus.open,
                )
                # These rows are read here and written further down the same transaction, so
                # without a lock a concurrent `POST /complete` can flip one to `done` in
                # between and the pending UPDATE then re-dates a history row - the single
                # thing this function documents it must never do. `of=` keeps the lock off
                # the joined `chores` row, which nothing here writes and which every other
                # request touching this household would otherwise queue behind.
                .with_for_update(of=ChoreOccurrence)
            )
        )
        .scalars()
        .all()
    )
    for occ in rows:
        candidate = occ.scheduled_for.astimezone(old_tz).replace(tzinfo=new_tz)
        occ.scheduled_for = await free_slot_from(
            session, occ.chore_id, candidate, rule_for(occ.chore), new_tz
        )
    return len(rows)
