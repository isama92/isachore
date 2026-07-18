from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, CompletedChore, Household, RepeatPeriod, User, UserStatus

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeCompletion = Callable[..., Awaitable[CompletedChore]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

# A fixed reference day so date arithmetic in assertions is unambiguous.
DUE = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


async def test_completions_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 401


async def test_completions_lists_most_recent_first(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Dishes")
    # created_at pinned (func.now() is constant within the test transaction, so
    # unpinned rows would tie and only the id tiebreaker would order them).
    await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE, title="oldest"
    )
    await make_completion(
        chore=chore,
        scheduled_for=DUE + timedelta(days=1),
        completed_by=user,
        created_at=DUE + timedelta(days=1),
        title="middle",
    )
    await make_completion(
        chore=chore,
        scheduled_for=DUE + timedelta(days=2),
        completed_by=user,
        created_at=DUE + timedelta(days=2),
        title="newest",
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == ["newest", "middle", "oldest"]
    first = body["items"][0]
    assert first["completed_by"] == {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }
    assert first["household"] == {"id": household.id, "name": household.name}


async def test_completions_days_late_late_on_time_and_early(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    # Late by 3 days.
    await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE + timedelta(days=3)
    )
    # On time: same date, later in the day.
    await make_completion(
        chore=chore,
        scheduled_for=DUE + timedelta(days=10),
        completed_by=user,
        created_at=DUE + timedelta(days=10, hours=6),
    )
    # Early: completed the day before it was due.
    await make_completion(
        chore=chore,
        scheduled_for=DUE + timedelta(days=20),
        completed_by=user,
        created_at=DUE + timedelta(days=19),
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions?sort_by=created_at&sort_dir=asc")
    assert resp.status_code == 200
    assert [item["days_late"] for item in resp.json()["items"]] == [3, 0, -1]


async def test_completions_includes_other_members(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Me")
    other = await make_user(email="other@example.com", first_name="Otto", last_name="Ther")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household)
    await make_completion(chore=chore, scheduled_for=DUE, completed_by=other, created_at=DUE)
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["completed_by"]["id"] == other.id


async def test_completions_excludes_other_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    mine = await make_household(members=[me], name="Mine")
    theirs = await make_household(members=[stranger], name="Theirs")
    my_chore = await make_chore(household=mine, title="Mine")
    their_chore = await make_chore(household=theirs, title="Theirs")
    await make_completion(chore=my_chore, scheduled_for=DUE, completed_by=me, created_at=DUE)
    await make_completion(
        chore=their_chore, scheduled_for=DUE, completed_by=stranger, created_at=DUE
    )
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["title"] for item in items] == ["Mine"]


async def test_completions_filter_by_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    h1 = await make_household(members=[user], name="One")
    h2 = await make_household(members=[user], name="Two")
    c1 = await make_chore(household=h1, title="In one")
    c2 = await make_chore(household=h2, title="In two")
    await make_completion(chore=c1, scheduled_for=DUE, completed_by=user, created_at=DUE)
    await make_completion(chore=c2, scheduled_for=DUE, completed_by=user, created_at=DUE)
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/completions?household_id={h2.id}")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["In two"]


async def test_completions_filter_by_user(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household)
    await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=me, created_at=DUE, title="by me"
    )
    await make_completion(
        chore=chore,
        scheduled_for=DUE + timedelta(days=1),
        completed_by=other,
        created_at=DUE + timedelta(days=1),
        title="by other",
    )
    client = await auth_client(me)

    resp = await client.get(f"/api/v1/completions?user_id={other.id}")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["by other"]


async def test_completions_pagination(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    for offset in range(3):
        await make_completion(
            chore=chore,
            scheduled_for=DUE + timedelta(days=offset),
            completed_by=user,
            created_at=DUE + timedelta(days=offset),
        )
    client = await auth_client(user)

    page1 = (await client.get("/api/v1/completions?page=1&page_size=2")).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    page2 = (await client.get("/api/v1/completions?page=2&page_size=2")).json()
    assert page2["total"] == 3
    assert len(page2["items"]) == 1


async def test_completions_includes_soft_deleted_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Original title")
    # Title is snapshotted at completion; a later soft delete must not hide history.
    await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE, title="Snapshot"
    )
    chore.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["title"] for item in items] == ["Snapshot"]


async def test_completions_completed_by_null(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    # completed_by omitted -> completed_by_user_id is NULL (a hard-deleted user).
    await make_completion(chore=chore, scheduled_for=DUE, completed_by=None, created_at=DUE)
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["completed_by"] is None


async def test_completions_sort_by_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    # Distinct scheduled_for keeps the (chore_id, scheduled_for) unique guard happy.
    for offset, title in enumerate(["Cherry", "Apple", "Banana"]):
        await make_completion(
            chore=chore,
            scheduled_for=DUE + timedelta(days=offset),
            completed_by=user,
            created_at=DUE + timedelta(days=offset),
            title=title,
        )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions?sort_by=title&sort_dir=asc")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Apple", "Banana", "Cherry"]


async def test_completions_excludes_soft_deleted_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # A completion in a since-deleted household drops out of scope, because
    # member_household_ids only returns active households.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    await make_completion(chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE)
    household.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_completions_invalid_sort_422(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.get("/api/v1/completions?sort_by=nonsense")
    assert resp.status_code == 422


async def test_completion_filters_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 401


async def test_completion_filters_options(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Aaron")
    alice = await make_user(email="alice@example.com", first_name="Alice")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    stranger = await make_user(email="stranger@example.com", first_name="Stranger")
    # me shares two households; alice is in both (must appear once), bob in one.
    await make_household(members=[me, alice], name="Beta")
    await make_household(members=[me, alice, bob], name="Alpha")
    # A household me is NOT in: neither it nor its member should surface.
    await make_household(members=[stranger], name="Zeta")
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 200
    body = resp.json()
    assert [h["name"] for h in body["households"]] == ["Alpha", "Beta"]
    member_ids = [m["id"] for m in body["members"]]
    # Ordered by first name; alice appears once despite being in both households.
    assert [m["first_name"] for m in body["members"]] == ["Aaron", "Alice", "Bob"]
    assert stranger.id not in member_ids


async def test_completion_filters_excludes_disabled_members(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Aaron")
    gone = await make_user(email="gone@example.com", first_name="Gone", status=UserStatus.disabled)
    await make_household(members=[me, gone])
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 200
    assert gone.id not in [m["id"] for m in resp.json()["members"]]


# --- undo (DELETE /completions/{id}) --------------------------------------


async def test_undo_latest_reverts_last_completed_at(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    t1, t2 = DUE, DUE + timedelta(days=1)
    chore = await make_chore(household=household, repeats=RepeatPeriod.daily, last_completed_at=t2)
    await make_completion(chore=chore, scheduled_for=DUE, completed_by=user, created_at=t1)
    latest = await make_completion(chore=chore, scheduled_for=t2, completed_by=user, created_at=t2)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{latest.id}")
    assert resp.status_code == 204

    refreshed = (await db_session.execute(select(Chore).where(Chore.id == chore.id))).scalar_one()
    # Rolled back to the previous completion's timestamp: the chore is due again.
    assert refreshed.last_completed_at == t1
    remaining = (await db_session.execute(select(CompletedChore.id))).scalars().all()
    assert latest.id not in remaining


async def test_undo_only_completion_clears_last_completed_at(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, last_completed_at=DUE)
    only = await make_completion(chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{only.id}")
    assert resp.status_code == 204

    refreshed = (await db_session.execute(select(Chore).where(Chore.id == chore.id))).scalar_one()
    assert refreshed.last_completed_at is None


async def test_undo_older_completion_leaves_schedule_unchanged(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    t1, t2, t3 = DUE, DUE + timedelta(days=1), DUE + timedelta(days=2)
    chore = await make_chore(household=household, repeats=RepeatPeriod.daily, last_completed_at=t3)
    await make_completion(chore=chore, scheduled_for=DUE, completed_by=user, created_at=t1)
    middle = await make_completion(chore=chore, scheduled_for=t2, completed_by=user, created_at=t2)
    await make_completion(chore=chore, scheduled_for=t3, completed_by=user, created_at=t3)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{middle.id}")
    assert resp.status_code == 204

    refreshed = (await db_session.execute(select(Chore).where(Chore.id == chore.id))).scalar_one()
    # Deleting a non-latest completion is a history edit: MAX(created_at) is still t3.
    assert refreshed.last_completed_at == t3


async def test_undo_another_members_completion_403(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household)
    completion = await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=other, created_at=DUE
    )
    client = await auth_client(me)

    resp = await client.delete(f"/api/v1/completions/{completion.id}")
    assert resp.status_code == 403


async def test_undo_completion_in_other_household_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    theirs = await make_household(members=[stranger], name="Theirs")
    chore = await make_chore(household=theirs)
    completion = await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=stranger, created_at=DUE
    )
    client = await auth_client(me)

    resp = await client.delete(f"/api/v1/completions/{completion.id}")
    assert resp.status_code == 404


async def test_undo_missing_completion_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.delete("/api/v1/completions/999999")
    assert resp.status_code == 404


async def test_undo_requires_auth(
    client: AsyncClient,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_completion: MakeCompletion,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    completion = await make_completion(
        chore=chore, scheduled_for=DUE, completed_by=user, created_at=DUE
    )
    resp = await client.delete(f"/api/v1/completions/{completion.id}")
    assert resp.status_code == 401


async def test_occurrence_can_be_completed_again_after_undo(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Full round-trip through the real complete endpoint: undo frees the
    # (chore_id, scheduled_for) unique row so the occurrence is completable again.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    client = await auth_client(user)

    first = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert first.status_code == 201
    undo = await client.delete(f"/api/v1/completions/{first.json()['id']}")
    assert undo.status_code == 204
    again = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert again.status_code == 201
