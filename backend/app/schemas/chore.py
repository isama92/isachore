from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import AssignmentType, RepeatPeriod
from app.schemas.tag import TagRead
from app.schemas.user import UserRead


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
    assignee_ids: list[int] = Field(default_factory=list)
    # Who starts on the hook. Used for `manual` (you set it); for the auto strategies
    # the initial assignee is derived, but an explicit pool member is honoured.
    current_assignee_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)


class ChoreUpdate(BaseModel):
    """Full replace of an editable chore. The household is fixed at creation and
    intentionally not editable here."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    turn_length: int = Field(default=1, ge=1)
    assignee_ids: list[int] = Field(default_factory=list)
    current_assignee_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)
