"""The household activity log: the writer, the chore-diff that feeds it, and its
retention sweep. The table and what it is not are documented on
`app.models.household_log_entry.HouseholdLogEntry`.

`record_log_entry` appends an entry to the caller's session and lets the caller commit it as
part of the surrounding transaction, the same contract `core/audit.py`'s `record_event` has -
but it emits no log line of its own, see its docstring. The only thing logged here is the
prune's row count, which names nobody.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models import AssignmentType, Chore, HouseholdLogAction, HouseholdLogEntry, RepeatPeriod

logger = logging.getLogger("app.household_log")

# How long an entry is readable for. A product promise rather than a deployment knob, so a
# module constant and NOT a Settings field - the same call as MAX_PENDING_INVITATIONS and
# MAX_RICH_TEXT_LENGTH. The read endpoint applies it as a query predicate and the daily job
# below deletes past it, which is why the promise holds even where the job has never run.
LOG_RETENTION = timedelta(days=90)

# The chore fields an update reports, and the order it reports them in: declaration order is
# what the reader sees, so an entry is stable and nothing downstream has to sort.
#
# The open occurrence's assignee is deliberately absent. It is derived rather than stored on
# the chore, and `_reconcile_open_occurrence` recomputes it on most edits, so including it
# would mark nearly every edit as an assignee change. The consequence, which is intended: a
# PATCH that only moves `current_assignee_id`, or only sets `clear_current_assignee`, writes
# no entry at all.
CHORE_LOG_FIELDS = (
    "title",
    "description",
    "start_date",
    "repeats",
    "assignment_type",
    "turn_length",
    "repeat_interval",
    "weekdays",
    "assignees",
    "tags",
)


@dataclass(frozen=True)
class ChoreSnapshot:
    """A chore's loggable fields at one moment, for diffing an edit against itself.

    Frozen and built from copies, so it cannot alias the live chore: `weekdays` is an ARRAY
    whose in-place mutation SQLAlchemy does not track (see the note on `Chore.weekdays`), and
    the two id sets are taken off relationship lists that the edit is about to replace.
    """

    title: str
    description: str | None
    start_date: date | None
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    turn_length: int
    repeat_interval: int
    weekdays: tuple[int, ...] | None
    assignees: frozenset[int]
    tags: frozenset[int]


def snapshot_chore(chore: Chore) -> ChoreSnapshot:
    """Snapshot a chore's loggable fields. Reads `assignees` and `tags`, which
    `_get_user_chore_or_404` already eager-loads, so this costs no query."""
    return ChoreSnapshot(
        title=chore.title,
        description=chore.description,
        start_date=chore.start_date,
        repeats=chore.repeats,
        assignment_type=chore.assignment_type,
        turn_length=chore.turn_length,
        repeat_interval=chore.repeat_interval,
        # A tuple rather than the list itself, which is what stops `before` aliasing the value
        # the edit then overwrites. Both None and [] collapse to None, so a legacy row holding
        # [] does not report a phantom change when it is normalised away; compared as a
        # sequence rather than a set because both sides are already sorted and deduplicated by
        # `_normalised_schedule`, so a genuine reordering would be a genuine change.
        weekdays=tuple(chore.weekdays) if chore.weekdays else None,
        assignees=frozenset(u.id for u in chore.assignees),
        tags=frozenset(t.id for t in chore.tags),
    )


def changed_chore_fields(before: ChoreSnapshot, after: ChoreSnapshot) -> list[str]:
    """The names of the fields that moved between two snapshots of the same chore, in
    CHORE_LOG_FIELDS order. Empty means the edit changed nothing loggable.

    `description` compares the stored strings as they are: both sides have been through
    `SanitisedHtml`, so both are canonical and NULL is the single spelling of empty. Do not
    re-sanitise the older side before comparing - a later tightening of the allowlist does not
    clean old rows, so that would hide a real cleanup instead of reporting it.
    """
    return [field for field in CHORE_LOG_FIELDS if getattr(before, field) != getattr(after, field)]


async def record_log_entry(
    session: AsyncSession,
    *,
    action: HouseholdLogAction,
    household_id: int,
    actor_id: int,
    chore_id: int | None = None,
    chore_title: str | None = None,
    target_id: int | None = None,
    impersonator_id: int | None = None,
    changed_fields: Sequence[str] | None = None,
) -> None:
    """Append an entry to the caller's transaction. `session.add` only: the caller commits,
    so an entry lands exactly when the change it describes does, and a rolled-back request
    (the 409 on a colliding chore edit, say) leaves none behind.

    Cannot fail the caller's commit: `chore_title` comes from a String(255) column of the same
    width, and `changed_fields` values come from the closed CHORE_LOG_FIELDS tuple.

    Writes no application log line, deliberately unlike `core/audit.py`'s `record_event`. There
    the log line is a second channel for operator forensics; here the row IS the record, and a
    copy in the app log would put the same personal data somewhere the 90-day promise below does
    not reach - application logs are usually shipped off-box under their own retention. Keeping
    it in one place is what makes that promise true rather than nearly true.
    """
    session.add(
        HouseholdLogEntry(
            action=action,
            household_id=household_id,
            actor_user_id=actor_id,
            target_user_id=target_id,
            impersonator_user_id=impersonator_id,
            chore_id=chore_id,
            chore_title=chore_title,
            # A fresh list, never the caller's, since ARRAY mutation is not change-tracked.
            # An empty sequence collapses to NULL: no fields moved means no entry at all, so
            # the column is never a meaningless [].
            changed_fields=list(changed_fields) if changed_fields else None,
        )
    )


async def prune_old_log_entries(session: AsyncSession) -> int:
    """Delete entries past the retention window. Returns how many rows went; does NOT commit
    (the caller owns the transaction, like `mark_expired_invitations`).

    Housekeeping rather than enforcement: the read endpoint applies the same window in SQL, so
    what this actually buys is a table that does not grow without bound.
    """
    result = await session.execute(
        delete(HouseholdLogEntry).where(
            HouseholdLogEntry.created_at < datetime.now(UTC) - LOG_RETENTION
        )
    )
    return result.rowcount


async def run_prune_logs() -> int:
    """Open a standalone session, prune, commit. The entry point the daily scheduler job and
    the `prune-logs` CLI command share."""
    async with async_session_factory() as session:
        count = await prune_old_log_entries(session)
        await session.commit()
    if count:
        logger.info("pruned %d household log entry/entries past retention", count)
    return count
