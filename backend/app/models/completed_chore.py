from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore import Chore


class CompletedChore(Base):
    """One recorded completion of a chore occurrence (append-only history).

    Written when a chore is checked off on the Home due view. `title` is copied
    from the chore so history survives a later rename, and `scheduled_for` stores
    the occurrence's due datetime at completion time so we can tell whether it was
    done early or late (compare with `created_at`) without recomputing anything.
    `chore_id` is ON DELETE RESTRICT to preserve history: chores are only ever
    soft-deleted today, so this never blocks in-app, but it guards against a
    future hard purge silently dropping completion records.

    AVG note: `completed_by_user_id` links an identified person to timestamped
    actions, so this table accumulates personal data with no retention limit or
    pruning, and (like the rest of the app) users are soft-deleted, so the
    ON DELETE SET NULL never fires in practice. A bounded retention period and an
    erasure/anonymisation path are a follow-up, to be agreed with the VCSW
    compliance officer (draft pending sign-off). No special-category data (BSN,
    etc.) is stored here.
    """

    __tablename__ = "completed_chores"
    # A single occurrence (chore_id, scheduled_for) can only be completed once.
    # Legitimate consecutive occurrences always differ in scheduled_for (each is
    # last_completed_at + interval), so this only rejects a double-submit of the
    # same occurrence.
    __table_args__ = (UniqueConstraint("chore_id", "scheduled_for"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chore_id: Mapped[int] = mapped_column(ForeignKey("chores.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(255))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Who checked it off. SET NULL (not CASCADE) so history survives a hypothetical
    # hard user delete; users are soft-deleted, so in practice this stays set.
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chore: Mapped["Chore"] = relationship()
