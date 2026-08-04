from datetime import datetime

from pydantic import BaseModel

from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead


class HistoryEntryRead(BaseModel):
    """One closed-occurrence row for the History view.

    `title` is the snapshot taken at closing time (survives a later rename or a
    soft-deleted chore); `completed_at` is when it was actually checked off and
    `scheduled_for` is the occurrence's due datetime, so `days_late` (>0 late, <=0
    on time/early) is the date-based difference between them. It is None for an
    unscheduled chore, which had no due date to be late against: there the slot merely
    records when the chore became available, so subtracting it would report the gap since
    the last completion as lateness. `completed_by` is
    None when the completer's account has been hard-deleted (users are normally
    soft-deleted, so in practice it stays set). Names only on `completed_by`
    (HouseholdMemberRead is data-minimised: no email).

    `skipped` marks the rows where the occurrence was closed without the work being done.
    They belong in the list (something did happen to that slot, and it can be undone like
    any other) but must be readable as distinct from real completions, which is what this
    flag is for. Their `days_late` is None too: there was a deadline, but no work to be
    punctual about."""

    id: int
    title: str
    scheduled_for: datetime
    completed_at: datetime
    skipped: bool
    days_late: int | None
    completed_by: HouseholdMemberRead | None
    household: ChoreHouseholdRead


class HistoryFilterOptions(BaseModel):
    """The option lists for the History filters: the households the current user
    belongs to, and the distinct active members across those households (the
    people who could appear in the "completed by" column)."""

    households: list[ChoreHouseholdRead]
    members: list[HouseholdMemberRead]
