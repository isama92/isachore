from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.chores import MAX_INTERVAL
from app.models import AssignmentType, RepeatPeriod
from app.schemas.tag import TagRead
from app.schemas.user import UserRead

# A Monday-first weekday ordinal, as Python's `date.weekday()` numbers them (0 = Monday ..
# 6 = Sunday). NOT ISO-8601, which numbers weekdays 1..7, and not JavaScript's
# `Date.getDay()`, which starts at Sunday: the frontend indexes a Monday-first key array
# rather than calling getDay(), so the two agree.
Weekday = Annotated[int, Field(ge=0, le=6)]


def _normalised_recurrence(
    repeats: RepeatPeriod, repeat_interval: int, weekdays: list[int] | None
) -> tuple[int, list[int] | None]:
    """The canonical (repeat_interval, weekdays) pair: weekdays sorted and deduplicated but
    kept only for `weekly`, and the interval forced to 1 for `manual`, which never recurs.

    Normalising rather than rejecting, because a 422 here would fire every time someone
    flipped the period from weekly to daily before the form cleared the weekday list -
    `turn_length` sets the same ignore-when-irrelevant precedent. Dropping the value rather
    than merely ignoring it stops a stale weekday set silently reactivating on a switch
    back to weekly, and the read-back (`weekdays: null`) makes the drop visible. An empty
    list means what NULL means, unpinned, so it collapses to None too.
    """
    interval = 1 if repeats == RepeatPeriod.manual else repeat_interval
    if repeats != RepeatPeriod.weekly or not weekdays:
        return interval, None
    return interval, sorted(set(weekdays))


class ChoreHouseholdRead(BaseModel):
    """The household a chore belongs to, embedded in ChoreRead so the list column
    and the read-only edit header can show its name without a second request."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ChoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    # Completions one assignee holds before the chore hands off (1 = every completion).
    turn_length: int
    # Periods between occurrences (1 = every period), and the Monday-first weekdays a weekly
    # chore falls on. None means unpinned: the chore keeps whatever weekday its occurrences
    # already sit on. For a chore created unpinned that is its start date's weekday, but a
    # chore that was pinned and then unpinned keeps the weekday it was snapped to, so do not
    # present None as "derived from the start date".
    repeat_interval: int
    weekdays: list[int] | None
    created_at: datetime
    household: ChoreHouseholdRead
    # The full pool of people the chore can rotate between.
    assignees: list[UserRead]
    # Who is on the hook right now (the open occurrence's assignee); None when the
    # chore is unassigned/shared or has no open occurrence (a completed one-off).
    current_assignee: UserRead | None = None
    tags: list[TagRead]


class ChoreCreate(BaseModel):
    household_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    # >= 1; the "take turns" UI uses >= 2, 1 means hand off every completion.
    turn_length: int = Field(default=1, ge=1)
    # How many periods between occurrences. Capped at core.chores.MAX_INTERVAL, which is
    # what keeps a yearly rule's month arithmetic inside datetime's year range.
    repeat_interval: int = Field(default=1, ge=1, le=MAX_INTERVAL)
    # Which weekdays a weekly chore falls on; None or empty means unpinned.
    weekdays: list[Weekday] | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    # Who starts on the hook. Used for `manual` (you set it); for the auto strategies
    # the initial assignee is derived, but an explicit pool member is honoured.
    current_assignee_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonicalise_recurrence(self) -> Self:
        # Safe to assign in an "after" validator: validate_assignment is off, so this does
        # not re-trigger validation.
        self.repeat_interval, self.weekdays = _normalised_recurrence(
            self.repeats, self.repeat_interval, self.weekdays
        )
        return self


class ChoreUpdate(BaseModel):
    """Full replace of an editable chore. The household is fixed at creation and
    intentionally not editable here."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    turn_length: int = Field(default=1, ge=1)
    repeat_interval: int = Field(default=1, ge=1, le=MAX_INTERVAL)
    weekdays: list[Weekday] | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    current_assignee_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonicalise_recurrence(self) -> Self:
        self.repeat_interval, self.weekdays = _normalised_recurrence(
            self.repeats, self.repeat_interval, self.weekdays
        )
        return self
