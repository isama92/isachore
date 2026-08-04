import enum
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HouseholdLogAction(enum.StrEnum):
    """What a log entry records. A closed set enforced at the schema layer, since the
    column is a plain String - see the note on HouseholdLogEntry.action.

    Undoing a completion and undoing a skip are two actions rather than one with a flag:
    they read completely differently to whoever is looking at the log ("Sam undid Jo's
    completion of Bins" is somebody's work being erased, "Sam undid Jo's skip of Bins" is
    a mis-skip being fixed), and nothing downstream would re-derive which it was.
    """

    chore_created = "chore_created"
    chore_updated = "chore_updated"
    chore_deleted = "chore_deleted"
    completion_undone = "completion_undone"
    skip_undone = "skip_undone"


class HouseholdLogEntry(Base):
    """Append-only log of who changed what inside one household, read by its owner on the
    Logs page. Covers chore management (create / update / delete) and undone closures.

    Deliberately NOT `audit_events`, and not application logging either. `audit_events` is
    the operator-facing trail for authentication, 2FA and admin user management: it keys its
    action off a native `audit_action` enum, so every new value needs an `ALTER TYPE`
    migration (which is why app/cli.py reuses `user_updated` rather than adding one), and it
    carries `ip_address`, which must never reach a household surface. This table is the
    household-facing counterpart, with a plain-String action and no IP.

    Personal data, so bounded on purpose (AVG / ISO 27001): visible to the household owner
    alone, no IP address and no free-text column for a caller to write into (`chore_title` is
    user-authored, but a copy of what the reader already sees on the chore), both people
    carried as `HouseholdMemberRead` (no email) on the wire, an impersonating operator recorded
    here but exposed to the household only as a boolean, no copy in the application log, and a
    90-day retention window enforced twice - as a predicate in the read query and by the daily
    prune job (see core/household_log.py).
    """

    __tablename__ = "household_log_entries"
    __table_args__ = (
        # The read shape: one or more owned households, newest first, inside the retention
        # window. A composite covers a household_id-only filter too, so the column carries no
        # index of its own; `created_at` does, for the prune, which scans it across every
        # household and cannot use this one.
        Index("ix_household_log_household_created_at", "household_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    # A plain String with the closed set enforced at the schema layer, the same pattern as
    # household_members.role and users.status: a new action then needs no migration, which is
    # the whole reason this is not a row in audit_events.
    action: Mapped[str] = mapped_column(String(50))
    # Nullable + SET NULL on all four references (a deliberate departure from the usual
    # CASCADE, mirroring audit_events) so the trail survives a hypothetical hard delete. Every
    # action has a known actor in practice - the writer takes one - and the column is nullable
    # for the foreign key's sake alone: do not "fix" it to NOT NULL.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Whose closure was undone. NULL for the three chore actions.
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # The real admin behind an impersonated session, when the action was taken while
    # impersonating. The read derives `by_admin: bool` from whether this is set and never
    # exposes the identity, because a site admin may be a stranger to this household. Nothing
    # reads the id itself: it is here for a by-hand query when somebody asks who was driving,
    # and it is pruned with the row. The durable impersonation trail is `audit_events`, which
    # records every start and stop and is not pruned.
    impersonator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # SET NULL, and it cannot be anything else. CASCADE would let an append-only log delete
    # its own rows. RESTRICT would break a hard household delete, because that cascades into
    # `chores` and Postgres does not order sibling cascades - this table's own CASCADE might
    # not have cleared the row yet when the chore goes. Nothing hard-deletes a household today
    # (they are soft-deleted, and `seed --fresh` clears this table explicitly and first), so
    # that is a landmine avoided rather than a live requirement. `chore_title` carries the
    # snapshot that keeps a row readable either way, the same trick chore_occurrences.title
    # uses against a rename.
    chore_id: Mapped[int | None] = mapped_column(
        ForeignKey("chores.id", ondelete="SET NULL"), default=None
    )
    # The title as it stood when the entry was written, so a rename or a soft delete does not
    # rewrite history. String(255) against chores.title's String(255), so the snapshot always
    # fits and adding a row can never fail the caller's commit on length.
    chore_title: Mapped[str | None] = mapped_column(String(255), default=None)
    # Which of the chore's fields moved on a `chore_updated`, by name and never by value.
    # NULL for every other action, and never an empty array: no fields moved means no entry.
    changed_fields: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
