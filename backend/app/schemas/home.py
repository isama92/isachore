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
    household: ChoreHouseholdRead
    assignees: list[HouseholdMemberRead]


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
    """The result of marking a chore done: the recorded completion plus the
    chore's recomputed due state (None fields when a manual one-off is now done)."""

    id: int
    chore_id: int
    title: str
    scheduled_for: datetime
    completed_by_user_id: int | None
    created_at: datetime
    next_due: datetime | None
    days_until_due: int | None
    status: DueStatus | None
