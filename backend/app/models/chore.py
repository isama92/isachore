import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Column, Date, DateTime, ForeignKey, SmallInteger, String, Table, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore_occurrence import ChoreOccurrence
    from app.models.household import Household
    from app.models.tag import Tag
    from app.models.user import User


class RepeatPeriod(enum.StrEnum):
    manual = "manual"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class AssignmentType(enum.StrEnum):
    manual = "manual"
    alphabetical = "alphabetical"
    random = "random"
    least_done = "least_done"


# n-m: a chore is assigned to zero or more users
chore_assignees = Table(
    "chore_assignees",
    Base.metadata,
    Column("chore_id", ForeignKey("chores.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

# n-m: a chore carries zero or more tags
chore_tags = Table(
    "chore_tags",
    Base.metadata,
    Column("chore_id", ForeignKey("chores.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Chore(Base):
    __tablename__ = "chores"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed: every chore/history/stats query scopes by household, and Postgres does
    # not auto-index a foreign key.
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000))
    # When the chore starts, which is only ever used to seed the first occurrence's slot;
    # every later slot is walked from the previous one. NULL means unscheduled (`manual`),
    # which has no start: its first occurrence opens at creation time and each completion
    # reopens it at the completion moment. The schema layer keeps the two in step, forcing
    # NULL for `manual` and requiring a date for every other period.
    start_date: Mapped[date | None] = mapped_column(Date)
    repeats: Mapped[RepeatPeriod] = mapped_column(SAEnum(RepeatPeriod, name="repeat_period"))
    assignment_type: Mapped[AssignmentType] = mapped_column(
        SAEnum(AssignmentType, name="assignment_type")
    )
    # How many completions one assignee holds before the chore hands off to the next
    # person (the strategy picks who). 1 = hand off every completion; "take turns" in
    # the UI sets a larger value. Only meaningful for the auto-rotating strategies.
    turn_length: Mapped[int] = mapped_column(default=1, server_default="1")
    # How many periods pass between occurrences: 1 = every period, 2 = every other, and so
    # on. Not meaningful for `manual`, which never recurs (stored as 1). A plain int with
    # the >= 1 bound enforced at the schema layer, like turn_length.
    repeat_interval: Mapped[int] = mapped_column(default=1, server_default="1")
    # Which weekdays a `weekly` chore falls on, as Monday-first ordinals from Python's
    # `date.weekday()` (0 = Monday .. 6 = Sunday), sorted and deduplicated. NOT ISO-8601,
    # which numbers weekdays 1..7. NULL means unpinned: the chore keeps whatever weekday
    # its occurrences already sit on, which is how every chore predating this column
    # behaves - hence no backfill. Non-NULL only for `weekly`.
    #
    # Note the SQLAlchemy footgun: in-place mutation of an ARRAY value is not change
    # tracked. Every write path here assigns a whole new list, so it does not bite.
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), default=None)
    # Soft delete: NULL means active, a timestamp means the chore is deleted and
    # hidden from the list (mirrors households; recoverable only via the DB).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    household: Mapped["Household"] = relationship(back_populates="chores")
    assignees: Mapped[list["User"]] = relationship(
        secondary=chore_assignees, back_populates="chores"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=chore_tags, back_populates="chores")
    occurrences: Mapped[list["ChoreOccurrence"]] = relationship(back_populates="chore")
