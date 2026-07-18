from datetime import datetime

from pydantic import BaseModel

from app.core.chores import DueStatus
from app.models import RepeatPeriod


class DueChoreRead(BaseModel):
    """A chore due within the Home window, with its computed due state."""

    id: int
    title: str
    repeats: RepeatPeriod
    next_due: datetime
    days_until_due: int  # negative = overdue, 0 = today, positive = upcoming
    status: DueStatus


class ProgressRead(BaseModel):
    """Today's progress: how many of the overdue-or-due-today chores are done."""

    done_today: int
    total_today: int


class HomeRead(BaseModel):
    progress: ProgressRead
    items: list[DueChoreRead]


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
