from datetime import datetime

from pydantic import BaseModel

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
    modified). Omitted or None credits the current user (the default)."""

    completed_by_user_id: int | None = None


class CompletionRead(BaseModel):
    """The result of marking a chore done: the recorded completion plus the chore's
    recomputed due state. Always populated, since completing a chore always reopens it
    (an unscheduled chore reopens at the completion moment, so it reads as due today)."""

    id: int
    chore_id: int
    title: str
    scheduled_for: datetime
    completed_by_user_id: int | None
    created_at: datetime
    next_due: datetime
    days_until_due: int
    status: DueStatus
