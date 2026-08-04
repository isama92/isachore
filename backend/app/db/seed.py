"""Dev/test data seeder.

Populates a realistic dataset so every feature can be exercised by hand: five users,
a solo household each plus one shared household, tags, and many chores covering the whole
option matrix (0/1/many assignees, all four assignment strategies, all five repeat
periods, repeat intervals, pinned weekdays, turn lengths 1..7, every due bucket) with
completion history. Invoked via `python -m app.cli seed [--fresh]`; the CLI entry refuses
to run outside a dev
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
from app.core.chores import RecurrenceRule, first_occurrence, next_occurrence_after
from app.core.household_log import record_log_entry
from app.core.households import add_member, personal_household_name
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
    HouseholdLogAction,
    HouseholdLogEntry,
    HouseholdRole,
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

# Roles in the shared household, so every role can be signed into and compared side by
# side. Alex owns it and is therefore an organiser whatever this says; anyone left out is a
# helper, the role a real invite lands on. Bram is a second organiser (so "several
# organisers, one owner" is exercised), Cara a deputy, Dan and Eve helpers.
_SHARED_ROLES = {
    "bram@example.com": HouseholdRole.organiser,
    "cara@example.com": HouseholdRole.deputy,
}

_TAG_COLORS = ["#0d9488", "#7c6bf0", "#e0a458"]


@dataclass
class ChoreSpec:
    """One chore to seed. `start_days_ago` sets the first occurrence (negative = starts
    in the future, for due-soon/far chores); `completions` is how many past occurrences
    to mark done (capped so a future occurrence is never completed). `current_email` sets
    an explicit starting assignee (used by `manual`); otherwise the strategy derives it.
    `weekdays` pins a `weekly` chore to Monday-first weekdays (0 = Mon .. 6 = Sun) and is
    ignored for every other period. Note that pinning weekdays or raising
    `repeat_interval` fits fewer slots into the same window, so such specs need a larger
    `start_days_ago` to seed any history.

    For a `manual` (unscheduled) chore the written `start_date` is NULL whatever this says,
    since those have none; `start_days_ago` still dates the occurrence chain, so it controls
    how long ago the chore looks like it was last done."""

    title: str
    repeats: RepeatPeriod
    assignment: AssignmentType
    assignee_emails: list[str]
    start_days_ago: int
    completions: int = 0
    turn_length: int = 1
    repeat_interval: int = 1
    weekdays: list[int] | None = None
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
        start_days_ago=70,  # 10 Tuesdays back, so all 10 completions below fit
        completions=10,
        weekdays=[1],  # Tuesdays only
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
    # The four unscheduled chores that follow cover every state of the unscheduled view's
    # recency dot between them: never done (grey), done today (green), done this week
    # (yellow) and done long ago (grey with a date). "Bleed the radiators" needs three
    # completions to land one today, because each completion reopens the chore at its own
    # timestamp and the loop in _create_chore only completes slots strictly before today:
    # 1 day ago at 00:00 -> 08:00 -> 16:00 -> today 00:00.
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
        "Bleed the radiators",
        RepeatPeriod.manual,
        AssignmentType.manual,
        ["bram@example.com"],
        start_days_ago=1,
        completions=3,
        current_email="bram@example.com",
    ),
    ChoreSpec(
        "Sort out the loft",
        RepeatPeriod.manual,
        AssignmentType.alphabetical,
        ["admin@example.com", "eve@example.com"],
        start_days_ago=25,
        completions=1,
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
    # Interval and weekday-pinned recurrence (weekdays are Monday-first: 0 = Mon .. 6 = Sun).
    ChoreSpec(
        "Start the washing machine",
        RepeatPeriod.weekly,
        AssignmentType.least_done,
        ["cara@example.com", "dan@example.com"],
        start_days_ago=42,
        completions=11,
        weekdays=[1, 4],  # twice a week: Tuesdays and Fridays, so the stride alternates 3/4
    ),
    ChoreSpec(
        "Run the dishwasher",
        RepeatPeriod.daily,
        AssignmentType.alphabetical,
        [e for e, *_ in _USERS],
        start_days_ago=30,
        completions=13,
        repeat_interval=2,  # every other day
        tags=["kitchen"],
    ),
    ChoreSpec(
        "Scrub the shower",
        RepeatPeriod.weekly,
        AssignmentType.random,
        ["admin@example.com", "eve@example.com"],
        start_days_ago=84,
        completions=5,
        repeat_interval=2,
        weekdays=[5],  # every other Saturday: interval and pinning together
        tags=["cleaning"],
    ),
    ChoreSpec(
        "Change the bedsheets",
        RepeatPeriod.weekly,
        AssignmentType.manual,
        ["bram@example.com"],
        start_days_ago=63,
        completions=2,
        repeat_interval=3,  # an interval with no pinning, so weekdays stay NULL
        current_email="bram@example.com",
    ),
    ChoreSpec(
        "Sort the recycling",
        RepeatPeriod.weekly,
        AssignmentType.alphabetical,
        ["dan@example.com", "eve@example.com"],
        start_days_ago=28,
        completions=18,
        weekdays=[0, 1, 2, 3, 4],  # weekdays only, never the weekend
        tags=["outdoor"],
    ),
    ChoreSpec(
        "Deep clean the oven",
        RepeatPeriod.monthly,
        AssignmentType.manual,
        ["cara@example.com"],
        start_days_ago=200,
        completions=2,
        repeat_interval=3,  # quarterly
        current_email="cara@example.com",
        tags=["kitchen"],
    ),
    ChoreSpec(
        "Service the boiler",
        RepeatPeriod.yearly,
        AssignmentType.manual,
        ["admin@example.com"],
        start_days_ago=900,
        completions=1,
        repeat_interval=2,  # every other year
        current_email="admin@example.com",
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
    # First: it references households, chores and users. The household_id CASCADE would
    # clear it anyway, which is exactly why leaving it out would fail silently - and
    # `seed --fresh` promises to wipe app data rather than to rely on an ondelete a later
    # change could relax. Same reasoning that put AuditEvent on this list.
    HouseholdLogEntry,
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
    # Store what the rule normalised rather than the raw spec, so a spec cannot seed a
    # weekday set on a non-weekly chore, or an unsorted one, and diverge from what the API
    # would have written.
    rule = RecurrenceRule.of(spec.repeats, spec.repeat_interval, spec.weekdays)
    chore = Chore(
        household_id=household_id,
        title=spec.title,
        description=None,
        # An unscheduled chore has no start date (the API's canonicalisation guarantees it).
        # `start_days_ago` still dates its occurrence chain below, which is how a seeded one
        # can look like it has been sitting around for a fortnight.
        start_date=None if spec.repeats == RepeatPeriod.manual else start,
        repeats=spec.repeats,
        assignment_type=spec.assignment,
        turn_length=spec.turn_length,
        repeat_interval=rule.interval,
        weekdays=list(rule.weekdays) or None,
    )
    if pool:
        chore.assignees.extend(pool)
    if tags:
        chore.tags.extend(tags)
    session.add(chore)

    assignee = current if current is not None else initial_assignee(spec.assignment, pool, rng=rng)
    scheduled = first_occurrence(start, rule)
    counts: dict[int, int] = {}
    occurrences = 0
    today = now.date()

    # `closure` counts every closed occurrence; `completed` counts only the ones that were
    # really done, which is what should_reassign expects (1-based).
    completed = 0
    for closure in range(1, spec.completions + 1):
        # Never complete an occurrence that isn't in the past: today's/future slots stay
        # open (the terminal row below).
        if scheduled.date() >= today:
            break
        # Every fifth closure of a *scheduled* chore is a skip rather than a completion, so a
        # freshly seeded stack actually exercises the new surfaces: History's badge and outcome
        # filter, the grey series on the time chart, the fourth punctuality slice. Never an
        # unscheduled chore, because the skip endpoint refuses those and stats' punctuality
        # relies on every skipped row having had a real deadline.
        was_skipped = spec.repeats != RepeatPeriod.manual and closure % 5 == 0
        completed_at = min(scheduled + timedelta(hours=8), now)
        session.add(
            ChoreOccurrence(
                chore=chore,
                scheduled_for=scheduled,
                assignee_id=assignee.id if assignee is not None else None,
                status=OccurrenceStatus.done,
                skipped=was_skipped,
                title=spec.title,
                completed_by_user_id=assignee.id if assignee is not None else None,
                completed_at=completed_at,
                created_at=completed_at,  # so History's created_at sort matches chronology
            )
        )
        occurrences += 1
        nxt = next_occurrence_after(scheduled, completed_at, rule)
        # A skip earns no rotation credit and spends none of the turn, exactly as
        # `_close_occurrence` has it: it neither feeds the least_done tally nor advances the
        # handoff, so whoever skipped is still up next.
        if not was_skipped:
            completed += 1
            if assignee is not None:
                counts[assignee.id] = counts.get(assignee.id, 0) + 1
            if (
                spec.assignment != AssignmentType.manual
                and pool
                and should_reassign(completed, spec.turn_length)
            ):
                assignee = next_assignee(spec.assignment, pool, assignee, counts, rng=rng)
        scheduled = nxt

    # The single terminal open occurrence. Every chore gets one, whatever its period: an
    # unscheduled chore reopens at each completion rather than terminating.
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
    memberships: list[tuple[str, User, HouseholdRole]] = []

    def add_household(
        key: str,
        name: str,
        owner: User,
        members: list[User],
        tag_names: list[str],
        roles: dict[str, HouseholdRole] | None = None,
    ) -> None:
        hh = Household(name=name, admin_id=owner.id)
        session.add(hh)
        households[key] = hh
        # Memberships are recorded now and inserted after the flush below, via add_member:
        # `hh.members.extend(...)` would go through the relationship, which writes the two
        # foreign keys only and would leave every seeded member on the column's helper
        # default. Owners are organisers; anyone `roles` does not name is a helper.
        for member in members:
            role = (
                HouseholdRole.organiser
                if member is owner
                else (roles or {}).get(member.email, HouseholdRole.helper)
            )
            memberships.append((key, member, role))
        for i, tag_name in enumerate(tag_names):
            tags[(key, tag_name)] = Tag(
                household=hh, name=tag_name, color=_TAG_COLORS[i % len(_TAG_COLORS)]
            )

    for user in users:
        add_household(
            f"solo:{user.email}",
            personal_household_name(user.first_name),
            user,
            [user],
            ["home", "errands"],
        )
    add_household(
        _SHARED,
        "The Flat",
        by_email["admin@example.com"],
        users,
        ["cleaning", "kitchen", "outdoor"],
        _SHARED_ROLES,
    )
    session.add_all(tags.values())
    await session.flush()  # assigns household ids, which add_member needs
    for key, member, role in memberships:
        await add_member(session, households[key].id, member.id, role)
    summary.households = len(households)

    # (household, chore) per seeded chore, so the log entries below can be written once the
    # ids exist. The seeder builds chores directly rather than through the endpoints, so it has
    # to write its own entries or a freshly seeded stack would show an empty Logs page.
    built: list[tuple[Household, Chore]] = []

    def build(hh_key: str, spec: ChoreSpec) -> None:
        pool = [by_email[e] for e in spec.assignee_emails]
        current = by_email[spec.current_email] if spec.current_email else None
        spec_tags = [tags[(hh_key, name)] for name in spec.tags if (hh_key, name) in tags]
        chore, occ = _seed_chore(
            session,
            household_id=households[hh_key].id,
            spec=spec,
            pool=pool,
            current=current,
            tags=spec_tags,
            rng=rng,
            now=now,
        )
        built.append((households[hh_key], chore))
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

    # One `chore_created` entry per seeded chore, credited to the household owner and stamped
    # now (the column's server_default), so it sits inside the retention window and the owner
    # has something to read. Flushed first, because the entries need the chore ids.
    await session.flush()
    for household, chore in built:
        await record_log_entry(
            session,
            action=HouseholdLogAction.chore_created,
            household_id=household.id,
            actor_id=household.admin_id,
            chore_id=chore.id,
            chore_title=chore.title,
        )

    await session.commit()
    return summary
