from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.household_invitation import HouseholdInvitationStatus


class HouseholdMemberRead(BaseModel):
    # Only what the member list / assignee picker needs (data minimisation: no
    # email here).
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str


class HouseholdListRead(BaseModel):
    """A household row for the management tables and the edit-page header.

    `member_count` counts active members only (disabled users are hidden
    everywhere); `chore_count` counts every chore in the household. `deleted_at`
    is NULL for active households and a timestamp for soft-deleted ones.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # The owner (household admin). Only this member may edit the household and
    # manage its members on the user surface.
    admin_id: int
    created_at: datetime
    deleted_at: datetime | None
    member_count: int
    chore_count: int


class HouseholdInvitationRead(BaseModel):
    """An invitation as the owner sees it in the list. `url` is the shareable
    link; `status` carries the full lifecycle including `expired` (set by the
    hourly sweep), which the UI uses for the display state and the row's action.
    `expires_at` is kept only for the "expires/expired {when}" label."""

    id: int
    url: str
    status: HouseholdInvitationStatus
    created_at: datetime
    expires_at: datetime


class HouseholdInvitationInfo(BaseModel):
    """Public info shown on the accept page: which household and who invited."""

    household_name: str
    invited_by: HouseholdMemberRead


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class HouseholdUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Transfer ownership: the new owner must be an active member of the household.
    admin_id: int | None = None
