from datetime import datetime

from pydantic import BaseModel

from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead


class LogEntryRead(BaseModel):
    """One row of a household's activity log, for the owner-only Logs view.

    `chore_title` is the snapshot taken when the entry was written, so a renamed or
    soft-deleted chore still reads correctly; `chore_id` is carried alongside it so a future UI
    could link to the chore (nothing does yet), and is None only after a hard delete (chores are
    soft-deleted, so in practice it stays set). `actor` is None when that account has been
    hard-deleted, the same way History's `completed_by` is. `target` is who a closure was
    recorded against, and is None for the three chore actions.

    Both people are `HouseholdMemberRead` (data-minimised: no email), and there is no IP
    address here at all - unlike `audit_events`, which this table deliberately is not.

    `action` and `changed_fields` are both plain strings on the wire rather than the enum and a
    Literal union, for the same reason: a value written by a differently-versioned server must
    not break a read, so the closed set lives on the client, which degrades an unknown name
    instead. Coercing `action` back through `HouseholdLogAction` here would raise `ValueError`
    on a row a newer release wrote - a 500 on every page containing it, unfilterable, because
    the coercion is per row after the query. The enum still guards the `action` *query
    parameter*, where a 422 on nonsense input is exactly right.

    `changed_fields` is populated for `chore_updated` alone and is a plain list of names, never
    values, in the order `CHORE_LOG_FIELDS` declares.

    `by_admin` says the action was taken through an impersonated session. A boolean, never the
    operator's identity: the impersonator is a site admin, potentially a stranger to this
    household, so who they were stays in the table for the operator-level trail.
    """

    id: int
    action: str
    created_at: datetime
    household: ChoreHouseholdRead
    actor: HouseholdMemberRead | None
    target: HouseholdMemberRead | None
    chore_id: int | None
    chore_title: str | None
    changed_fields: list[str] = []
    by_admin: bool = False
