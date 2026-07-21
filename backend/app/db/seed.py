"""Dev/test data seeder.

Populates a realistic dataset so every feature can be exercised by hand: five users,
a solo household each plus one shared household, tags, and many chores covering the whole
option matrix (0/1/many assignees, all four assignment strategies, all five repeat
periods, turn lengths 1..7, every due bucket) with completion history. Invoked via
`python -m app.cli seed [--fresh]`; the CLI entry refuses to run outside a dev
environment. `seed --fresh` wipes all app data first, which also makes it a reliable way
to reset test data.

History is built by replaying completions purely through the same helpers the
`/complete` endpoint uses (`initial_assignee` / `next_assignee` / `should_reassign` /
`next_occurrence_after`), so seeded occurrence chains are identical in shape to real ones:
a run of `done` rows plus exactly one `open` row per active chore.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assignment import initial_assignee, next_assignee, should_reassign
from app.core.chores import first_occurrence, next_occurrence_after
from app.core.security import hash_password
from app.models import (
    AssignmentType,
    AuditEvent,
    AuthToken,
    Chore,
    ChoreOccurrence,
    ConfirmationToken,
    Household,
    HouseholdInvitation,
    OccurrenceStatus,
    RepeatPeriod,
    Tag,
    User,
    UserStatus,
)

# Every seeded user shares this password (>= 8 chars). Dev-only placeholder.
SEED_PASSWORD = "password"
# Fixed so a `random` strategy (and thus the whole dataset) is reproducible.
_RNG_SEED = 20260721

# (email, first_name, last_name, is_admin) - first names sort alphabetically so the
# alphabetical strategy rotates in an obvious order.
_USERS = [
    ("admin@example.com", "Alex", "Admin", True),
    ("bram@example.com", "Bram", "Bakker", False),
    ("cara@example.com", "Cara", "Cruz", False),
    ("dan@example.com", "Dan", "Dekker", False),
    ("eve@example.com", "Eve", "Evers", False),
]

_SHARED = "flat"  # dataset key for the shared household

_TAG_COLORS = ["#0d9488", "#7c6bf0", "#e0a458"]


@dataclass
class ChoreSpec:
    """One chore to seed. `start_days_ago` sets the first occurrence (negative = starts
    in the future, for due-soon/far chores); `completions` is how many past occurrences
    to mark done (capped so a future occurrence is never completed). `current_email` sets
    an explicit starting assignee (used by `manual`); otherwise the strategy derives it."""

    title: str
    repeats: RepeatPeriod
    assignment: AssignmentType
    assignee_emails: list[str]
    start_days_ago: int
    completions: int = 0
    turn_length: int = 1
    current_email: str | None = None
    tags: list[str] = field(default_factory=list)


# Shared-household chores: the coverage matrix (see module docstring).
_SHARED_CHORES = [
    ChoreSpec(
        "Water the plants",
        RepeatPeriod.daily,
        AssignmentType.alphabetical,
        ["admin@example.com", "bram@example.com"],
        start_days_ago=14,
        completions=20,
        turn_length=7,
        tags=["outdoor"],
    ),
    ChoreSpec(
        "Wash the dishes",
        RepeatPeriod.daily,
        AssignmentType.least_done,
        [e for e, *_ in _USERS],
        start_days_ago=15,
        completions=20,
        tags=["kitchen"],
    ),
    ChoreSpec(
        "Mop the kitchen floor",
        RepeatPeriod.weekly,
        AssignmentType.alphabetical,
        ["cara@example.com", "dan@example.com", "eve@example.com"],
        start_days_ago=42,
        completions=10,
        turn_length=2,
        tags=["cleaning", "kitchen"],
    ),
    ChoreSpec(
        "Water the herbs",
        RepeatPeriod.daily,
        AssignmentType.random,
        ["admin@example.com", "eve@example.com"],
        start_days_ago=12,
        completions=20,
        turn_length=3,
        tags=["outdoor"],
    ),
    ChoreSpec(
        "Take out the bins",
        RepeatPeriod.weekly,
        AssignmentType.random,
        ["bram@example.com", "cara@example.com"],
        start_days_ago=35,
        completions=10,
        tags=["outdoor"],
    ),
    ChoreSpec(
        "Vacuum the living room",
        RepeatPeriod.weekly,
        AssignmentType.manual,
        ["dan@example.com"],
        start_days_ago=28,
        completions=10,
        current_email="dan@example.com",
        tags=["cleaning"],
    ),
    ChoreSpec(
        "Pay the rent",
        RepeatPeriod.monthly,
        AssignmentType.manual,
        ["admin@example.com"],
        start_days_ago=150,
        completions=10,
        current_email="admin@example.com",
    ),
    ChoreSpec(
        "Descale the kettle",
        RepeatPeriod.yearly,
        AssignmentType.manual,
        ["bram@example.com"],
        start_days_ago=1,
        completions=1,
        current_email="bram@example.com",
        tags=["kitchen"],
    ),
    ChoreSpec(
        "Fix the leaky tap",
        RepeatPeriod.manual,
        AssignmentType.manual,
        ["cara@example.com"],
        start_days_ago=0,
        completions=0,
        current_email="cara@example.com",
    ),
    ChoreSpec(
        "Assemble the bookshelf",
        RepeatPeriod.manual,
        AssignmentType.manual,
        ["dan@example.com"],
        start_days_ago=2,
        completions=1,
        current_email="dan@example.com",
    ),
    ChoreSpec(
        "Tidy the shared shelf",
        RepeatPeriod.daily,
        AssignmentType.manual,
        [],
        start_days_ago=3,
        completions=0,
        tags=["cleaning"],
    ),
    ChoreSpec(
        "Check the smoke alarms",
        RepeatPeriod.monthly,
        AssignmentType.manual,
        ["eve@example.com"],
        start_days_ago=-3,
        completions=0,
        current_email="eve@example.com",
    ),
    ChoreSpec(
        "Buy the groceries",
        RepeatPeriod.weekly,
        AssignmentType.least_done,
        [e for e, *_ in _USERS],
        start_days_ago=56,
        completions=12,
        tags=["kitchen"],
    ),
]


@dataclass
class SeedSummary:
    users: int = 0
    households: int = 0
    chores: int = 0
    occurrences: int = 0

    def __str__(self) -> str:
        return (
            f"seeded {self.users} users, {self.households} households, "
            f"{self.chores} chores, {self.occurrences} occurrences"
        )


# App tables to clear for --fresh, in FK-safe order (occurrences before chores because
# chore_id is ON DELETE RESTRICT; households before users because households.admin_id has
# no ON DELETE; user-referencing tables before users). Association tables cascade with
# their parent (chore/household). app_settings and alembic_version are left untouched.
_WIPE_ORDER = [
    ChoreOccurrence,
    Chore,
    Tag,
    HouseholdInvitation,
    Household,
    AuthToken,
    ConfirmationToken,
    AuditEvent,
    User,
]


async def _wipe(session: AsyncSession) -> None:
    for model in _WIPE_ORDER:
        await session.execute(delete(model))
    await session.flush()


def _make_users() -> list[User]:
    pw = hash_password(SEED_PASSWORD)
    now = datetime.now(UTC)
    return [
        User(
            email=email,
            first_name=first,
            last_name=last,
            password_hash=pw,
            is_admin=is_admin,
            status=UserStatus.active,
            confirmed_at=now,
        )
        for email, first, last, is_admin in _USERS
    ]


def _seed_chore(
    session: AsyncSession,
    *,
    household_id: int,
    spec: ChoreSpec,
    pool: list[User],
    current: User | None,
    tags: list[Tag],
    rng: random.Random,
    now: datetime,
) -> tuple[Chore, int]:
    """Create the chore and its occurrence chain (history + one open row). Returns the
    chore and how many occurrences were written."""
    start = now.date() - timedelta(days=spec.start_days_ago)
    chore = Chore(
        household_id=household_id,
        title=spec.title,
        description=None,
        start_date=start,
        repeats=spec.repeats,
        assignment_type=spec.assignment,
        turn_length=spec.turn_length,
    )
    if pool:
        chore.assignees.extend(pool)
    if tags:
        chore.tags.extend(tags)
    session.add(chore)

    assignee = current if current is not None else initial_assignee(spec.assignment, pool, rng=rng)
    scheduled: datetime | None = first_occurrence(start)
    counts: dict[int, int] = {}
    occurrences = 0
    today = now.date()

    # `done` is the 1-based running completion count (what should_reassign expects).
    for done in range(1, spec.completions + 1):
        # Never complete an occurrence that isn't in the past: today's/future slots stay
        # open (the terminal row below).
        if scheduled is None or scheduled.date() >= today:
            break
        completed_at = min(scheduled + timedelta(hours=8), now)
        session.add(
            ChoreOccurrence(
                chore=chore,
                scheduled_for=scheduled,
                assignee_id=assignee.id if assignee is not None else None,
                status=OccurrenceStatus.done,
                title=spec.title,
                completed_by_user_id=assignee.id if assignee is not None else None,
                completed_at=completed_at,
                created_at=completed_at,  # so History's created_at sort matches chronology
            )
        )
        occurrences += 1
        if assignee is not None:
            counts[assignee.id] = counts.get(assignee.id, 0) + 1
        nxt = next_occurrence_after(scheduled, completed_at, spec.repeats)
        if nxt is None:  # a completed manual one-off has no successor
            scheduled = None
            break
        if (
            spec.assignment != AssignmentType.manual
            and pool
            and should_reassign(done, spec.turn_length)
        ):
            assignee = next_assignee(spec.assignment, pool, assignee, counts, rng=rng)
        scheduled = nxt

    # The single terminal open occurrence (unless this was a completed one-off).
    if scheduled is not None:
        session.add(
            ChoreOccurrence(
                chore=chore,
                scheduled_for=scheduled,
                assignee_id=assignee.id if assignee is not None else None,
                status=OccurrenceStatus.open,
            )
        )
        occurrences += 1
    return chore, occurrences


async def seed(session: AsyncSession, *, fresh: bool = False) -> SeedSummary:
    """Populate the dev dataset. With `fresh`, wipe all app data first; otherwise refuse
    on a non-empty DB. Commits on success. The caller (CLI) guards against non-dev
    environments before this runs."""
    if fresh:
        await _wipe(session)
    elif await session.scalar(select(User.id).limit(1)) is not None:
        raise RuntimeError("data already present; pass --fresh to wipe and reseed")

    rng = random.Random(_RNG_SEED)
    now = datetime.now(UTC)
    summary = SeedSummary()

    users = _make_users()
    session.add_all(users)
    await session.flush()
    by_email = {u.email: u for u in users}
    summary.users = len(users)

    # A solo household per user, plus one shared household with everyone. Keyed for the
    # chore specs; tags are created per household so tag filtering is testable.
    households: dict[str, Household] = {}
    tags: dict[tuple[str, str], Tag] = {}

    def add_household(key: str, name: str, owner: User, members: list[User], tag_names: list[str]):
        hh = Household(name=name, admin_id=owner.id)
        hh.members.extend(members)
        session.add(hh)
        households[key] = hh
        for i, tag_name in enumerate(tag_names):
            tags[(key, tag_name)] = Tag(
                household=hh, name=tag_name, color=_TAG_COLORS[i % len(_TAG_COLORS)]
            )

    for user in users:
        add_household(
            f"solo:{user.email}", f"{user.first_name}'s place", user, [user], ["home", "errands"]
        )
    add_household(
        _SHARED,
        "The Flat",
        by_email["admin@example.com"],
        users,
        ["cleaning", "kitchen", "outdoor"],
    )
    session.add_all(tags.values())
    await session.flush()
    summary.households = len(households)

    def build(hh_key: str, spec: ChoreSpec) -> None:
        pool = [by_email[e] for e in spec.assignee_emails]
        current = by_email[spec.current_email] if spec.current_email else None
        spec_tags = [tags[(hh_key, name)] for name in spec.tags if (hh_key, name) in tags]
        _, occ = _seed_chore(
            session,
            household_id=households[hh_key].id,
            spec=spec,
            pool=pool,
            current=current,
            tags=spec_tags,
            rng=rng,
            now=now,
        )
        summary.chores += 1
        summary.occurrences += occ

    for spec in _SHARED_CHORES:
        build(_SHARED, spec)

    # Each solo household: a few single-assignee chores (a due-today one with history and
    # an overdue one), so every household has something to look at.
    for user in users:
        key = f"solo:{user.email}"
        for spec in (
            ChoreSpec(
                "Make the bed",
                RepeatPeriod.daily,
                AssignmentType.manual,
                [user.email],
                start_days_ago=10,
                completions=15,
                current_email=user.email,
                tags=["home"],
            ),
            ChoreSpec(
                "Do the laundry",
                RepeatPeriod.weekly,
                AssignmentType.manual,
                [user.email],
                start_days_ago=21,
                completions=10,
                current_email=user.email,
                tags=["home"],
            ),
            ChoreSpec(
                "Water the desk plant",
                RepeatPeriod.daily,
                AssignmentType.manual,
                [user.email],
                start_days_ago=2,
                completions=0,
                current_email=user.email,
            ),
        ):
            build(key, spec)

    await session.commit()
    return summary
