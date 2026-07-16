from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import AssignmentType, RepeatPeriod
from app.schemas.tag import TagRead
from app.schemas.user import UserRead


class ChoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    created_at: datetime
    assignees: list[UserRead]
    tags: list[TagRead]


class ChoreCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_date: date
    repeats: RepeatPeriod
    assignment_type: AssignmentType
    assignee_ids: list[int] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
