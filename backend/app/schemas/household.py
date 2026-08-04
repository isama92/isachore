from datetime import datetime
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.household import HouseholdRole
from app.models.household_invitation import HouseholdInvitationStatus

# Every IANA name this Python knows. Resolved once at import: `available_timezones()` walks
# the tz database directory, which is far too much work to repeat per request.
_KNOWN_ZONES = frozenset(available_timezones())


def _known_timezone(value: str) -> str:
    # Reads as copy, not as a field name: `value_error` is passed through verbatim by the
    # frontend's 422 formatter (lib/validationError.ts), so this string IS what the user sees.
    if value not in _KNOWN_ZONES:
        raise ValueError(f"{value!r} is not a known timezone")
    return value


# An IANA timezone name, validated against the tz database rather than a hand-kept list, so
# the closed set tracks whatever `tzdata` ships. The 64-character cap matches the column and
# runs first, so a huge string is rejected before it is looked up.
#
# Validating on write is what lets everything downstream treat the stored value as usable, and
# it is the reason `household_zone` can afford to fall back to UTC instead of raising: the only
# ways to reach a bad value are an operator DB edit or the tz database dropping a name.
Timezone = Annotated[str, Field(max_length=64), AfterValidator(_known_timezone)]


class HouseholdMemberRead(BaseModel):
    # Only what the member list / assignee picker needs (data minimisation: no
    # email here).
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str


class HouseholdMemberRoleRead(HouseholdMemberRead):
    """A member as the household's own members table sees them: with their role.

    Deliberately a subclass used by the two members endpoints alone. `role` lives on the
    `household_members` association row, and the six other payloads built from
    `HouseholdMemberRead` (assignees on Home, Unscheduled and a chore read, History's
    `completed_by`, the filter options, an invitation's `invited_by`) have no membership in
    hand to read one from - putting it on the base would either leak a role into all of them
    or fail validation there."""

    role: HouseholdRole


class HouseholdMemberUpdate(BaseModel):
    """Body of PATCH /households/{id}/members/{user_id}. Role is the only mutable
    thing about a membership, and an unknown one is a 422 rather than a stored value
    the permission checks would silently read as "no role"."""

    role: HouseholdRole


class HouseholdListRead(BaseModel):
    """A household row for the management tables and the edit-page header.

    `member_count` counts active members only (disabled users are hidden
    everywhere); `chore_count` counts every chore in the household. `deleted_at`
    is NULL for active households and a timestamp for soft-deleted ones.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # The owner (household admin). Only this member may edit or delete the household,
    # remove members and transfer it; setting roles and inviting are organiser-level.
    admin_id: int
    # The zone the household reckons its days in, which is what every due date on its chores
    # is anchored to. Sent as a plain `str` rather than the validated `Timezone`: a read model
    # that re-validates would raise on a row a newer tz database wrote, turning an unfilterable
    # 500 out of a page that only wanted to display the name. Validation belongs on the write
    # side, where a rejection is actionable.
    timezone: str
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
    # Required, with no default, deliberately. A default of UTC would let a client that has
    # not been updated create households that silently reckon days in the wrong place - which
    # is precisely the bug per-household zones exist to fix, reintroduced quietly instead of
    # as a 422 naming the missing field. The frontend fills it from the browser.
    timezone: Timezone


class HouseholdUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Transfer ownership: the new owner must be an active member of the household.
    admin_id: int | None = None
    # Moving this re-dates the household's scheduled chores so they keep the local dates they
    # already had (see `update_household`). Optional here because the PATCH is a partial
    # update, so omitting it means "leave it alone" rather than "reset it".
    timezone: Timezone | None = None
