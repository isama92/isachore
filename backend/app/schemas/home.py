from datetime import datetime

from pydantic import BaseModel, Field

from app.core.chores import DueStatus
from app.models import RepeatPeriod
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead


class DueChoreRead(BaseModel):
    """A chore due within the Home window, with its computed due state plus the
    household it belongs to and its assignees, so a row can show whose chore it is
    (data-minimised member shape: no email)."""

    id: int
    title: str
    repeats: RepeatPeriod
    # The recurrence detail behind `repeats`, so a Home row can read "Every 2 days" or
    # "Weekly (Tue, Fri)" rather than a bare period.
    repeat_interval: int
    weekdays: list[int] | None
    next_due: datetime
    days_until_due: int  # negative = overdue, 0 = today, positive = upcoming
    status: DueStatus
    # How many occurrences are due by today: the open one plus every missed slot after it
    # (`due_slots`). 0 for an upcoming chore, 1 for one due today or overdue by a single slot.
    # The skip dialog offers "just one, all of them, or a custom number" only above 1, and
    # this is also the most `POST /chores/{id}/skip` accepts as a `count`.
    due_count: int
    # Whether the chore carries written instructions, NOT the instructions themselves: the row
    # only needs it to decide whether to offer the marker icon that opens the description
    # dialog, which fetches the chore itself on open. Sending the HTML here instead would put
    # every description in the household on the critical path of the app's landing page.
    has_description: bool
    household: ChoreHouseholdRead
    assignees: list[HouseholdMemberRead]


class UnscheduledChoreRead(BaseModel):
    """An unscheduled chore, as its own view lists it. Deliberately carries no due state:
    there is no deadline to report, and keeping `next_due` / `days_until_due` / `status` off
    the wire is what stops the due vocabulary creeping back into a view that has none. It
    reports how long since the chore was last done instead, which is what you actually want
    to know about something you do ad hoc. `repeats` is omitted too: every item here is
    unscheduled, so the label would be noise."""

    id: int
    title: str
    # Whole UTC days since the last completion (0 = earlier today), or None if the chore has
    # never been done. Drives both the row's label and its recency dot.
    days_since_last_completion: int | None
    # See DueChoreRead: a flag, not the description. Note this is not due state, so it does
    # not breach the "no due vocabulary here" rule above.
    has_description: bool
    household: ChoreHouseholdRead
    assignees: list[HouseholdMemberRead]


class UnscheduledRead(BaseModel):
    items: list[UnscheduledChoreRead]


class ProgressRead(BaseModel):
    """Today's progress: how many of the overdue-or-due-today chores are done."""

    done_today: int
    total_today: int


class HomeRead(BaseModel):
    progress: ProgressRead
    items: list[DueChoreRead]


class CompleteChoreRequest(BaseModel):
    """Optional body for POST /chores/{id}/complete. `completed_by_user_id` credits
    the completion to another member so the History shows it under their name;
    it must be one of the chore's current assignees (the chore itself is never
    modified). Omitted or None credits the current user (the default).

    `backdate` answers "when was it done" rather than "when was it ticked": it records the
    completion against the occurrence's own due day, for the chore somebody did and forgot
    to tick. Two things follow, and the second is the point - it reads as on time rather
    than late, and the successor advances exactly one slot instead of jumping past every
    occurrence that was missed, so a backlog is worked through one at a time rather than
    silently swallowed.

    A **flag, never a client-supplied datetime**: the server derives the instant as
    `min(end of the scheduled local day, now)`, which leaves no room for clock skew, a
    timestamp in the future, or a caller dating a completion to an arbitrary day. The clamp
    also makes the flag self-limiting rather than needing an overdue check - for a chore due
    today or early, the end of its due day is still ahead, so the answer is `now`, which is
    on time anyway.

    Refused with a 400 for an unscheduled (`manual`) chore, which is never due and so has no
    due day to be recorded against."""

    completed_by_user_id: int | None = None
    backdate: bool = False


class SkipChoreRequest(BaseModel):
    """Optional body for POST /chores/{id}/skip. `count` is how many due occurrences to skip,
    starting with the open one; each becomes its own skipped history row, and the chore
    reopens one slot after the last of them.

    Omitted, or None, skips every occurrence that is due by today, so a client that sends no
    body gets the same landing spot a skip always had. A number may not exceed the chore's
    `due_count` (refused with a 400, since that depends on the chore rather than on the
    request), except that a chore with nothing due yet still accepts a single skip.

    `completed_by_user_id` records the skip against another member instead of the caller, so
    the per-chore stats show who gave it up. Same rule as `CompleteChoreRequest`: it must be
    the caller or one of the chore's current assignees (400 otherwise). Omitted or None
    records the caller."""

    count: int | None = Field(default=None, ge=1)
    completed_by_user_id: int | None = None


class CompletionRead(BaseModel):
    """The result of closing a chore's occurrence: the recorded closure plus the chore's
    recomputed due state. Always populated, since closing a chore always reopens it
    (an unscheduled chore reopens at the completion moment, so it reads as due today).

    Shared by `POST /chores/{id}/complete` and `POST /chores/{id}/skip`, and `skipped` is
    what tells them apart. It is echoed rather than inferred from the route so a non-browser
    client can read what it created straight off the 201; `completed_by_user_id` is whoever
    the closure is recorded against either way, which for a skip is always the caller."""

    id: int
    chore_id: int
    title: str
    scheduled_for: datetime
    completed_by_user_id: int | None
    skipped: bool
    created_at: datetime
    next_due: datetime
    days_until_due: int
    status: DueStatus
