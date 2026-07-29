from datetime import date, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.core.chores import MAX_INTERVAL
from app.core.richtext import MAX_RICH_TEXT_LENGTH, sanitise_description
from app.models import AssignmentType, RepeatPeriod
from app.schemas.tag import TagRead
from app.schemas.user import UserRead

# A Monday-first weekday ordinal, as Python's `date.weekday()` numbers them (0 = Monday ..
# 6 = Sunday). NOT ISO-8601, which numbers weekdays 1..7, and not JavaScript's
# `Date.getDay()`, which starts at Sunday: the frontend indexes a Monday-first key array
# rather than calling getDay(), so the two agree.
Weekday = Annotated[int, Field(ge=0, le=6)]

# A rich text field: length-checked on the raw markup, then reduced to the allowlist in
# `app.core.richtext`, which is where the format and the reasoning behind it live.
#
# The cap sits *inside* the Annotated rather than on the field so the ordering is visible
# where it is defined. Pydantic runs constraints before an AfterValidator either way, and
# that is the order we want: the cap bounds what the server agrees to parse, and sanitising
# can only shrink from there, never rescue an oversized payload.
#
# This is the mirror image of NormalisedEmail (schemas/user.py), where the None sits outside
# the alias so the validator only sees the non-None member. Here it is inside, so the
# validator also runs for a missing value - deliberate, because collapsing blank HTML to
# NULL is the same job and `sanitise_description` handles None itself.
SanitisedHtml = Annotated[
    str | None,
    Field(max_length=MAX_RICH_TEXT_LENGTH),
    AfterValidator(sanitise_description),
]


def _normalised_schedule(
    repeats: RepeatPeriod,
    start_date: date | None,
    repeat_interval: int,
    weekdays: list[int] | None,
) -> tuple[date | None, int, list[int] | None]:
    """The canonical (start_date, repeat_interval, weekdays) triple: weekdays sorted and
    deduplicated but kept only for `weekly`, and the interval (forced to 1) plus the start
    date (forced to None) dropped for `manual`, which never recurs and so has nothing to
    start from - it opens at creation and reopens at each completion instead.

    Normalising rather than rejecting, because a 422 here would fire every time someone
    flipped the period from weekly to daily before the form cleared the weekday list -
    `turn_length` sets the same ignore-when-irrelevant precedent. Dropping the value rather
    than merely ignoring it stops a stale weekday set silently reactivating on a switch
    back to weekly, and the read-back (`weekdays: null`) makes the drop visible. An empty
    list means what NULL means, unpinned, so it collapses to None too.

    A *missing* start date is the one thing rejected rather than normalised, for the periods
    that need one: defaulting it would silently invent a schedule, and `first_occurrence`
    has no slot to open without it.
    """
    if repeats == RepeatPeriod.manual:
        return None, 1, None
    if start_date is None:
        raise ValueError("start_date is required unless the chore is unscheduled")
    if repeats != RepeatPeriod.weekly or not weekdays:
        return start_date, repeat_interval, None
    return start_date, repeat_interval, sorted(set(weekdays))


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
    # None for an unscheduled chore, which has no start date (see the model).
    start_date: date | None
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
    # chore is unassigned/shared. Every live chore has an open occurrence, whatever
    # its period, so this is not a "no occurrence" signal.
    current_assignee: UserRead | None = None
    tags: list[TagRead]


class ChoreCreate(BaseModel):
    household_id: int
    title: str = Field(min_length=1, max_length=255)
    description: SanitisedHtml = None
    # Required for every period but `manual`, where it is dropped; see _normalised_schedule.
    start_date: date | None = None
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
    def _canonicalise_schedule(self) -> Self:
        # Safe to assign in an "after" validator: validate_assignment is off, so this does
        # not re-trigger validation.
        self.start_date, self.repeat_interval, self.weekdays = _normalised_schedule(
            self.repeats, self.start_date, self.repeat_interval, self.weekdays
        )
        return self


class ChoreUpdate(BaseModel):
    """Full replace of an editable chore. The household is fixed at creation and
    intentionally not editable here."""

    title: str = Field(min_length=1, max_length=255)
    description: SanitisedHtml = None
    start_date: date | None = None
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    turn_length: int = Field(default=1, ge=1)
    repeat_interval: int = Field(default=1, ge=1, le=MAX_INTERVAL)
    weekdays: list[Weekday] | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    current_assignee_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonicalise_schedule(self) -> Self:
        self.start_date, self.repeat_interval, self.weekdays = _normalised_schedule(
            self.repeats, self.start_date, self.repeat_interval, self.weekdays
        )
        return self
