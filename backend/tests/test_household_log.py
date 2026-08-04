"""The household activity log: what the four write paths record, what the owner-only read
endpoint returns, the chore diff that feeds an update entry, and the retention sweep."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.household_log import (
    CHORE_LOG_FIELDS,
    LOG_RETENTION,
    changed_chore_fields,
    prune_old_log_entries,
    run_prune_logs,
    snapshot_chore,
)
from app.core.scheduler import create_scheduler
from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdLogAction,
    HouseholdLogEntry,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
    User,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

DUE = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


async def _entries(session: AsyncSession) -> list[HouseholdLogEntry]:
    """Every log entry, oldest first."""
    result = await session.execute(select(HouseholdLogEntry).order_by(HouseholdLogEntry.id))
    return list(result.scalars().all())


def _chore_payload(**overrides: object) -> dict[str, object]:
    """A full chore body. PATCH is a documented full replace, so every field is always
    present and a resubmitted payload is what "no change" looks like."""
    return {
        "household_id": 0,
        "title": "Wash the dishes",
        "description": None,
        "start_date": "2026-07-01",
        "repeats": "daily",
        "assignment_type": "manual",
        "turn_length": 1,
        "repeat_interval": 1,
        "weekdays": None,
        "assignee_ids": [],
        "tag_ids": [],
    } | overrides


# --- the chore diff -----------------------------------------------------


def test_every_logged_field_is_on_the_snapshot() -> None:
    # CHORE_LOG_FIELDS drives changed_chore_fields via getattr, so a name that is not a
    # snapshot attribute would raise at the first edit rather than at import time.
    snapshot = snapshot_chore(
        Chore(
            title="t",
            description=None,
            start_date=date(2026, 7, 1),
            repeats=RepeatPeriod.daily,
            assignment_type=AssignmentType.manual,
            turn_length=1,
            repeat_interval=1,
            weekdays=None,
        )
    )
    for field in CHORE_LOG_FIELDS:
        assert hasattr(snapshot, field), field


def test_changed_chore_fields_reports_in_declaration_order() -> None:
    # The reader sees this order, so it has to come from CHORE_LOG_FIELDS and from nothing else.
    # The three fields are chosen so declaration order, alphabetical order and the order they
    # are handed over in are all different: declaration gives title, turn_length,
    # repeat_interval; sorted() would give repeat_interval, title, turn_length; construction
    # order (below) would give turn_length, repeat_interval, title. Only the first passes.
    def chore(**kwargs: object) -> Chore:
        base: dict[str, object] = {
            "turn_length": 1,
            "repeat_interval": 1,
            "title": "t",
            "description": None,
            "start_date": date(2026, 7, 1),
            "repeats": RepeatPeriod.daily,
            "assignment_type": AssignmentType.manual,
            "weekdays": None,
        }
        # `base | kwargs` keeps base's key order, so this dict is deliberately NOT in
        # CHORE_LOG_FIELDS order - which is what stops the assertion passing by coincidence.
        return Chore(**(base | kwargs))

    before = snapshot_chore(chore())
    after = snapshot_chore(chore(turn_length=3, repeat_interval=2, title="other"))
    assert changed_chore_fields(before, after) == ["title", "turn_length", "repeat_interval"]


def test_changed_chore_fields_is_empty_for_an_identical_snapshot() -> None:
    chore = Chore(
        title="t",
        description="<p>x</p>",
        start_date=date(2026, 7, 1),
        repeats=RepeatPeriod.weekly,
        assignment_type=AssignmentType.random,
        turn_length=2,
        repeat_interval=3,
        weekdays=[0, 4],
    )
    assert changed_chore_fields(snapshot_chore(chore), snapshot_chore(chore)) == []


def test_snapshot_does_not_alias_the_weekdays_array() -> None:
    # ARRAY mutation is not change-tracked, so a snapshot holding the live list would compare
    # equal to itself after an in-place edit and report no change.
    chore = Chore(
        title="t",
        description=None,
        start_date=date(2026, 7, 1),
        repeats=RepeatPeriod.weekly,
        assignment_type=AssignmentType.manual,
        turn_length=1,
        repeat_interval=1,
        weekdays=[0, 1],
    )
    before = snapshot_chore(chore)
    chore.weekdays.append(4)  # type: ignore[union-attr]
    assert changed_chore_fields(before, snapshot_chore(chore)) == ["weekdays"]


def test_snapshot_treats_an_empty_weekday_list_as_none() -> None:
    # A legacy row holding [] normalises to NULL on write; that is not a change worth
    # reporting, so both spellings of "unpinned" have to compare equal.
    def chore(weekdays: list[int] | None) -> Chore:
        return Chore(
            title="t",
            description=None,
            start_date=date(2026, 7, 1),
            repeats=RepeatPeriod.daily,
            assignment_type=AssignmentType.manual,
            turn_length=1,
            repeat_interval=1,
            weekdays=weekdays,
        )

    assert changed_chore_fields(snapshot_chore(chore([])), snapshot_chore(chore(None))) == []


# --- the write paths ----------------------------------------------------


async def test_creating_a_chore_logs_it(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores", json=_chore_payload(household_id=household.id, title="Wash the dishes")
    )
    assert resp.status_code == 201

    entries = await _entries(db_session)
    assert len(entries) == 1
    assert entries[0].action == HouseholdLogAction.chore_created
    assert entries[0].household_id == household.id
    assert entries[0].actor_user_id == user.id
    assert entries[0].chore_id == resp.json()["id"]
    assert entries[0].chore_title == "Wash the dishes"
    assert entries[0].changed_fields is None
    assert entries[0].target_user_id is None
    assert entries[0].impersonator_user_id is None


async def test_deleting_a_chore_logs_the_title_it_had(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Descale the kettle")
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/chores/{chore.id}")).status_code == 204

    entries = await _entries(db_session)
    assert [(e.action, e.chore_title) for e in entries] == [
        (HouseholdLogAction.chore_deleted, "Descale the kettle")
    ]


async def test_editing_a_chore_logs_only_the_fields_that_moved(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, title="Old title", repeats=RepeatPeriod.daily, start_date=DUE.date()
    )
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_chore_payload(
            title="New title",
            start_date=DUE.date().isoformat(),
            repeat_interval=2,
        ),
    )
    assert resp.status_code == 200

    entries = await _entries(db_session)
    assert len(entries) == 1
    assert entries[0].action == HouseholdLogAction.chore_updated
    assert entries[0].changed_fields == ["title", "repeat_interval"]


async def test_a_no_op_edit_logs_nothing(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Resubmitting the same form is not an event. Delete the `if changed:` guard in
    # update_chore and this fails.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household,
        title="Wash the dishes",
        repeats=RepeatPeriod.daily,
        start_date=DUE.date(),
    )
    client = await auth_client(user)
    payload = _chore_payload(title="Wash the dishes", start_date=DUE.date().isoformat())

    assert (await client.patch(f"/api/v1/chores/{chore.id}", json=payload)).status_code == 200

    assert await _entries(db_session) == []


async def test_moving_only_the_current_assignee_logs_nothing(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The open occurrence's assignee is deliberately off CHORE_LOG_FIELDS: it is derived, and
    # _reconcile_open_occurrence recomputes it on most edits, so logging it would mark nearly
    # every edit as an assignee change. Intended consequence, pinned here so it is not read
    # later as a missing feature.
    user = await make_user()
    other = await make_user(email="other@example.com")
    household = await make_household(members=[user, other])
    chore = await make_chore(
        household=household,
        title="Wash the dishes",
        repeats=RepeatPeriod.daily,
        start_date=DUE.date(),
        assignees=[user, other],
    )
    client = await auth_client(user)
    payload = _chore_payload(
        title="Wash the dishes",
        start_date=DUE.date().isoformat(),
        assignee_ids=[user.id, other.id],
        current_assignee_id=other.id,
    )

    assert (await client.patch(f"/api/v1/chores/{chore.id}", json=payload)).status_code == 200

    assert await _entries(db_session) == []


async def test_switching_to_unscheduled_logs_the_period_and_the_start_date(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The schema forces start_date to NULL for `manual`, so two fields move even though the
    # form only touched one - which is exactly why the diff reads the chore rather than the
    # payload.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, title="Fix the tap", repeats=RepeatPeriod.daily, start_date=DUE.date()
    )
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_chore_payload(title="Fix the tap", repeats="manual", start_date=None),
    )
    assert resp.status_code == 200

    entries = await _entries(db_session)
    assert entries[0].changed_fields == ["start_date", "repeats"]


async def test_a_403_edit_logs_nothing(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    household = await make_household(
        members=[owner, deputy], roles={deputy.id: HouseholdRole.deputy}
    )
    chore = await make_chore(household=household, title="Wash the dishes")
    client = await auth_client(deputy)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_chore_payload(title="Something else", start_date=DUE.date().isoformat()),
    )
    assert resp.status_code == 403
    assert await _entries(db_session) == []


async def test_undoing_a_completion_logs_it_with_the_recorded_completer(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, title="Take out the bins", with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=DUE,
    )
    client = await auth_client(owner)

    assert (await client.delete(f"/api/v1/completions/{occ.id}")).status_code == 204

    entries = await _entries(db_session)
    assert len(entries) == 1
    assert entries[0].action == HouseholdLogAction.completion_undone
    assert entries[0].actor_user_id == owner.id
    assert entries[0].target_user_id == helper.id
    assert entries[0].chore_id == chore.id
    assert entries[0].chore_title == "Take out the bins"


async def test_undoing_a_skip_is_its_own_action(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Fixing a mis-skip and erasing somebody's completed work read completely differently, so
    # the flag has to be resolved into the action at write time - nothing re-derives it later.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Mop the floor", with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
        skipped=True,
    )
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/completions/{occ.id}")).status_code == 204

    entries = await _entries(db_session)
    assert [e.action for e in entries] == [HouseholdLogAction.skip_undone]


async def test_undoing_an_older_closure_still_logs_its_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # An older closure is HARD-deleted, so this pins that an entry survives a row that does
    # not. Note what it does NOT pin: reading `occ.title` after `session.delete` still works,
    # because the attribute lives in the session until the commit flushes. The ordering that
    # actually needs a test is the reopen branch's, which nulls the fields in place - see
    # test_undoing_the_latest_closure_logs_the_title_before_it_is_cleared.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Water the plants", with_occurrence=False)
    older = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=1),
    )
    await make_occurrence(chore=chore, scheduled_for=DUE + timedelta(days=2))
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/completions/{older.id}")).status_code == 204

    # The occurrence really is gone, so the title can only have come from the snapshot.
    assert await db_session.get(ChoreOccurrence, older.id) is None
    entries = await _entries(db_session)
    assert [(e.action, e.chore_title, e.chore_id) for e in entries] == [
        (HouseholdLogAction.completion_undone, "Water the plants", chore.id)
    ]


async def test_undoing_the_latest_closure_logs_the_title_before_it_is_cleared(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The other branch reopens the row, which nulls its title and completer.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Hoover", with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/completions/{occ.id}")).status_code == 204

    await db_session.refresh(occ)
    assert occ.title is None and occ.completed_by_user_id is None
    entries = await _entries(db_session)
    assert [(e.chore_title, e.target_user_id) for e in entries] == [("Hoover", user.id)]


async def test_completing_and_skipping_log_nothing(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Routine work is History's job; the log is for changes to the setup and for undos. Doing
    # the chores would otherwise drown the page.
    user = await make_user()
    household = await make_household(members=[user])
    done = await make_chore(household=household, title="Dishes", start_date=DUE.date())
    skipped = await make_chore(household=household, title="Bins", start_date=DUE.date())
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{done.id}/complete", json={})).status_code == 201
    assert (await client.post(f"/api/v1/chores/{skipped.id}/skip")).status_code == 201

    assert await _entries(db_session) == []


async def test_tag_and_household_changes_log_nothing(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The log's scope is chore management and undos. Widening it is a decision, not a
    # side effect of touching these endpoints.
    user = await make_user()
    household = await make_household(members=[user], name="The Flat")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/tags", json={"household_id": household.id, "name": "kitchen", "color": "#0d9488"}
    )
    assert resp.status_code == 201
    assert (
        await client.patch(f"/api/v1/households/{household.id}", json={"name": "The Flat 2"})
    ).status_code == 200

    assert await _entries(db_session) == []


async def test_an_impersonated_change_records_the_operator(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Accountability: the household is told only that an admin session was behind it (see the
    # read test), but the operator's id is kept for the operator-level trail.
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    household = await make_household(members=[member])
    chore = await make_chore(household=household, title="Wash the dishes")
    client = await auth_client(admin)

    assert (await client.post(f"/api/v1/users/{member.id}/impersonate")).status_code == 200
    assert (await client.delete(f"/api/v1/chores/{chore.id}")).status_code == 204

    entries = await _entries(db_session)
    assert [(e.actor_user_id, e.impersonator_user_id) for e in entries] == [(member.id, admin.id)]


# --- the read endpoint --------------------------------------------------


async def test_logs_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/logs")).status_code == 401


async def test_the_owner_reads_their_households_log_newest_first(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user], name="The Flat")
    first = await make_chore(household=household, title="First")
    client = await auth_client(user)
    assert (await client.delete(f"/api/v1/chores/{first.id}")).status_code == 204
    resp = await client.post(
        "/api/v1/chores", json=_chore_payload(household_id=household.id, title="Second")
    )
    assert resp.status_code == 201

    resp = await client.get("/api/v1/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [(e["action"], e["chore_title"]) for e in body["items"]] == [
        ("chore_created", "Second"),
        ("chore_deleted", "First"),
    ]
    entry = body["items"][0]
    assert entry["household"] == {"id": household.id, "name": "The Flat"}
    assert entry["actor"]["id"] == user.id
    assert "email" not in entry["actor"]
    assert entry["target"] is None
    assert entry["changed_fields"] == []
    assert entry["by_admin"] is False


async def test_a_non_owner_organiser_gets_an_empty_log(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The whole point of the gate: ownership, not the organiser role. An empty page rather
    # than a 403, because the list spans several households and narrowing is what it does.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(
        members=[owner, organiser], roles={organiser.id: HouseholdRole.organiser}
    )
    chore = await make_chore(household=household, title="Wash the dishes")
    owner_client = await auth_client(owner)
    assert (await owner_client.delete(f"/api/v1/chores/{chore.id}")).status_code == 204
    # The owner does see it, which is what makes the assertion below about ownership rather
    # than about an empty table.
    assert (await owner_client.get("/api/v1/logs")).json()["total"] == 1

    client = await auth_client(organiser)
    resp = await client.get("/api/v1/logs")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


async def test_logs_exclude_a_household_you_do_not_own(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    other = await make_user(email="other@example.com")
    mine = await make_household(name="Mine", members=[user])
    theirs = await make_household(name="Theirs", members=[other, user])
    for household, title in ((mine, "Mine"), (theirs, "Theirs")):
        chore = await make_chore(household=household, title=title)
        db_session.add(
            HouseholdLogEntry(
                action=HouseholdLogAction.chore_created,
                household_id=household.id,
                actor_user_id=user.id,
                chore_id=chore.id,
                chore_title=title,
            )
        )
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/logs")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Mine"]
    assert resp.json()["total"] == 1

    # Asking for the other one by id narrows to nothing rather than refusing.
    resp = await client.get(f"/api/v1/logs?household_id={theirs.id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_logs_exclude_a_soft_deleted_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user], deleted_at=datetime.now(UTC))
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.chore_created,
            household_id=household.id,
            actor_user_id=user.id,
            chore_title="Gone",
        )
    )
    await db_session.commit()
    client = await auth_client(user)

    assert (await client.get("/api/v1/logs")).json()["total"] == 0


async def test_logs_filter_by_actor_and_action(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    other = await make_user(email="other@example.com")
    household = await make_household(members=[user, other])
    for actor, action, title in (
        (user, HouseholdLogAction.chore_created, "Mine created"),
        (user, HouseholdLogAction.chore_deleted, "Mine deleted"),
        (other, HouseholdLogAction.chore_created, "Theirs created"),
    ):
        db_session.add(
            HouseholdLogEntry(
                action=action,
                household_id=household.id,
                actor_user_id=actor.id,
                chore_title=title,
            )
        )
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/logs?user_id={other.id}")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Theirs created"]

    resp = await client.get("/api/v1/logs?action=chore_deleted")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Mine deleted"]

    resp = await client.get(f"/api/v1/logs?user_id={user.id}&action=chore_created")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Mine created"]


async def test_logs_reject_an_unknown_action_or_sort_key(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    assert (await client.get("/api/v1/logs?action=chore_archived")).status_code == 422
    assert (await client.get("/api/v1/logs?sort_by=chore_title")).status_code == 422


async def test_logs_paginate_and_sort_ascending(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    for i in range(5):
        db_session.add(
            HouseholdLogEntry(
                action=HouseholdLogAction.chore_created,
                household_id=household.id,
                actor_user_id=user.id,
                chore_title=f"Chore {i}",
                created_at=DUE + timedelta(minutes=i),
            )
        )
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/logs?page=2&page_size=2")
    body = resp.json()
    assert body["total"] == 5
    assert [e["chore_title"] for e in body["items"]] == ["Chore 2", "Chore 1"]

    resp = await client.get("/api/v1/logs?sort_dir=asc&page_size=2")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Chore 0", "Chore 1"]


async def test_logs_hide_an_entry_past_retention_before_any_pruning(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The retention promise holds even where the daily job has never run, so the window is a
    # predicate in the read too. The row is still in the table, which is what makes this about
    # the query rather than about a delete.
    user = await make_user()
    household = await make_household(members=[user])
    now = datetime.now(UTC)
    for title, age in (
        ("Just inside", LOG_RETENTION - timedelta(days=1)),
        ("Too old", LOG_RETENTION + timedelta(days=1)),
    ):
        db_session.add(
            HouseholdLogEntry(
                action=HouseholdLogAction.chore_created,
                household_id=household.id,
                actor_user_id=user.id,
                chore_title=title,
                created_at=now - age,
            )
        )
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/logs")
    assert [e["chore_title"] for e in resp.json()["items"]] == ["Just inside"]
    assert resp.json()["total"] == 1
    assert len(await _entries(db_session)) == 2


async def test_logs_report_a_hard_deleted_actor_as_unknown(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # SET NULL rather than CASCADE, so the entry survives the account. It has to read, not 500.
    user = await make_user()
    ghost = await make_user(email="ghost@example.com")
    household = await make_household(members=[user, ghost])
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.chore_created,
            household_id=household.id,
            actor_user_id=ghost.id,
            chore_title="Orphaned",
        )
    )
    await db_session.commit()
    await db_session.delete(ghost)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/logs")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["actor"] is None


async def test_logs_report_an_impersonated_change_as_by_admin_without_naming_the_operator(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    admin = await make_user(email="admin@example.com", is_admin=True)
    household = await make_household(members=[user])
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.chore_deleted,
            household_id=household.id,
            actor_user_id=user.id,
            impersonator_user_id=admin.id,
            chore_title="Wash the dishes",
        )
    )
    await db_session.commit()
    client = await auth_client(user)

    entry = (await client.get("/api/v1/logs")).json()["items"][0]
    assert entry["by_admin"] is True
    # A boolean and nothing else: the operator may be a stranger to this household.
    assert str(admin.id) not in str(entry)
    assert "impersonator" not in entry


async def test_logs_read_an_action_this_release_does_not_know(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # A row a newer release wrote, read by an older one - reachable on a rollback, or with two
    # image versions side by side. Coercing `action` back through the enum would raise
    # ValueError per row, i.e. a 500 on every page containing it that no filter can get past.
    # The wire keeps it a string and the client degrades; `changed_fields` already worked this
    # way, and the two must not disagree.
    user = await make_user()
    household = await make_household(members=[user])
    db_session.add(
        HouseholdLogEntry(
            action="chore_archived",
            household_id=household.id,
            actor_user_id=user.id,
            chore_title="From the future",
        )
    )
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/logs")
    assert resp.status_code == 200
    assert [e["action"] for e in resp.json()["items"]] == ["chore_archived"]

    # The query parameter keeps the enum, though: nonsense input there is a 422, not a filter
    # that silently matches nothing.
    assert (await client.get("/api/v1/logs?action=chore_archived")).status_code == 422


async def test_logs_round_trip_changed_fields(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.chore_updated,
            household_id=household.id,
            actor_user_id=user.id,
            chore_title="Wash the dishes",
            changed_fields=["title", "weekdays"],
        )
    )
    await db_session.commit()
    client = await auth_client(user)

    assert (await client.get("/api/v1/logs")).json()["items"][0]["changed_fields"] == [
        "title",
        "weekdays",
    ]


# --- retention ----------------------------------------------------------


async def test_prune_deletes_only_entries_past_the_window(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    now = datetime.now(UTC)
    for age in (
        timedelta(0),
        LOG_RETENTION - timedelta(days=1),
        LOG_RETENTION + timedelta(days=1),
        LOG_RETENTION + timedelta(days=400),
    ):
        db_session.add(
            HouseholdLogEntry(
                action=HouseholdLogAction.chore_created,
                household_id=household.id,
                actor_user_id=user.id,
                chore_title="x",
                created_at=now - age,
            )
        )
    await db_session.commit()

    assert await prune_old_log_entries(db_session) == 2
    await db_session.commit()
    assert len(await _entries(db_session)) == 2
    # Idempotent: a second pass has nothing left to do.
    assert await prune_old_log_entries(db_session) == 0


def test_scheduler_registers_the_daily_prune_job() -> None:
    scheduler = create_scheduler()
    job = scheduler.get_job("prune-logs")
    assert job is not None
    assert job.func is run_prune_logs
    assert str(job.trigger) == "cron[hour='3', minute='30', second='0']"


# --- the model ----------------------------------------------------------


async def test_the_action_column_holds_every_action(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    # What actually pins "a new action needs no migration": the column is a String wide
    # enough for the whole enum, so adding a member is a code change alone.
    user = await make_user()
    household = await make_household(members=[user])
    for action in HouseholdLogAction:
        db_session.add(
            HouseholdLogEntry(
                action=action,
                household_id=household.id,
                actor_user_id=user.id,
                chore_title="x",
            )
        )
    await db_session.commit()

    assert {e.action for e in await _entries(db_session)} == {a.value for a in HouseholdLogAction}


async def test_hard_deleting_a_user_leaves_their_entries_behind(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    # SET NULL on all three user references, so the trail outlives an account. Both the actor
    # and the target are checked: they are separate columns, and only one of them has a read
    # test (the actor's, via the API), so this is what covers the other two.
    owner = await make_user(email="owner@example.com")
    ghost = await make_user(email="ghost@example.com")
    admin = await make_user(email="admin@example.com", is_admin=True)
    household = await make_household(members=[owner, ghost, admin])
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.completion_undone,
            household_id=household.id,
            actor_user_id=ghost.id,
            target_user_id=ghost.id,
            impersonator_user_id=admin.id,
            chore_title="Bins",
        )
    )
    await db_session.commit()

    await db_session.delete(ghost)
    await db_session.delete(admin)
    await db_session.commit()

    entries = await _entries(db_session)
    assert len(entries) == 1
    assert entries[0].actor_user_id is None
    assert entries[0].target_user_id is None
    assert entries[0].impersonator_user_id is None
    # The row still says what happened, because the title never depended on a live row.
    assert entries[0].chore_title == "Bins"


async def test_hard_deleting_a_household_takes_its_log_with_it(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    # CASCADE. Unreachable through the API (households are soft-deleted), and not something
    # `seed --fresh` leans on either, since that clears this table explicitly and first - so it
    # is asserted at this level or nowhere, and what it buys is that a hard delete added later
    # cannot leave orphans behind.
    user = await make_user()
    household = await make_household(members=[user])
    db_session.add(
        HouseholdLogEntry(
            action=HouseholdLogAction.chore_created,
            household_id=household.id,
            actor_user_id=user.id,
            chore_title="x",
        )
    )
    await db_session.commit()

    await db_session.delete(household)
    await db_session.commit()

    assert await _entries(db_session) == []
