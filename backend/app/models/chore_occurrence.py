import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore import Chore
    from app.models.user import User


class OccurrenceStatus(enum.StrEnum):
    """Lifecycle of a single chore occurrence: `open` = assigned and due (the
    scheduler), `done` = completed (history). Stored as a plain String with the closed
    set enforced at the schema layer, same approach as users.status."""

    open = "open"
    done = "done"


class ChoreOccurrence(Base):
    """One occurrence of a chore on its recurrence grid - the scheduler and the
    completion history merged into a single timeline.

    A chore has at most one `open` occurrence at a time (the current due one, backed by
    a partial unique index); completing it flips the row to `done` and inserts the next
    open occurrence. The open row's `assignee_id` is the chore's current assignee, the
    only person shown on the Home due view. `title` is snapshotted on completion so
    history survives a rename (open rows read the live chore title). `assignee_id` and
    `completed_by_user_id` are ON DELETE SET NULL so history outlives a hard user delete;
    `chore_id` is ON DELETE RESTRICT to preserve history (chores are only soft-deleted).
    """

    __tablename__ = "chore_occurrences"
    __table_args__ = (
        # One row per occurrence (open or done); rejects a double-complete of a slot.
        UniqueConstraint("chore_id", "scheduled_for", name="uq_occurrence_chore_scheduled"),
        # At most one open occurrence per chore (the current due one).
        Index(
            "uq_open_occurrence_per_chore",
            "chore_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        # Stats aggregations lead with status, then window on a timestamp. Composite
        # (status, completed_at) serves the done-in-range scans (completions over time,
        # punctuality, per-person, "done in range"); (status, scheduled_for) serves the
        # open+overdue scans (status donut, "overdue now"). A composite also covers a
        # status-only filter, so these two back most stats queries.
        Index("ix_occurrence_status_completed_at", "status", "completed_at"),
        Index("ix_occurrence_status_scheduled_for", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chore_id: Mapped[int] = mapped_column(ForeignKey("chores.id", ondelete="RESTRICT"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Who is on the hook for this occurrence. NULL = unassigned/shared (shows to everyone).
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(16), default=OccurrenceStatus.open)
    # Snapshot taken on completion so history survives a rename; open rows read the
    # live chore title instead.
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    # Who got credit for the completion (may differ from assignee_id via the credit
    # dialog). Set when the row is done.
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chore: Mapped["Chore"] = relationship(back_populates="occurrences")
    # Two FKs point at users, so each relationship names its own foreign key.
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id])
    completed_by: Mapped["User | None"] = relationship(foreign_keys=[completed_by_user_id])
