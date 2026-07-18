from datetime import datetime

from pydantic import BaseModel

from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead


class HistoryEntryRead(BaseModel):
    """One completed-chore row for the History view.

    `title` is the snapshot taken at completion time (survives a later rename or a
    soft-deleted chore); `completed_at` is when it was actually checked off and
    `scheduled_for` is the occurrence's due datetime, so `days_late` (>0 late, <=0
    on time/early) is the date-based difference between them. `completed_by` is
    None when the completer's account has been hard-deleted (users are normally
    soft-deleted, so in practice it stays set). Names only on `completed_by`
    (HouseholdMemberRead is data-minimised: no email)."""

    id: int
    title: str
    scheduled_for: datetime
    completed_at: datetime
    days_late: int
    completed_by: HouseholdMemberRead | None
    household: ChoreHouseholdRead


class HistoryFilterOptions(BaseModel):
    """The option lists for the History filters: the households the current user
    belongs to, and the distinct active members across those households (the
    people who could appear in the "completed by" column)."""

    households: list[ChoreHouseholdRead]
    members: list[HouseholdMemberRead]
