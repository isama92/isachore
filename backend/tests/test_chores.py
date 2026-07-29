from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    OccurrenceStatus,
    RepeatPeriod,
    Tag,
    User,
    UserStatus,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeTag = Callable[..., Awaitable[Tag]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

# Monday-first weekday ordinals, as `date.weekday()` numbers them (NOT ISO-8601's 1..7).
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Clean the bathroom",
        "start_date": "2026-07-16",
        "repeats": "weekly",
        "assignment_type": "manual",
    }
    base.update(overrides)
    return base


async def _open_slot(session: AsyncSession, chore_id: int) -> datetime:
    """The `scheduled_for` of the chore's single open occurrence."""
    occ = (
        await session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one()
    return occ.scheduled_for


# --- create ---


async def test_create_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="deep-clean")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            title="Scrub the tub",
            description="Replace the towels",
            repeats="daily",
            assignment_type="least_done",
            assignee_ids=[user.id],
            tag_ids=[tag.id],
        ),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Scrub the tub"
    assert body["description"] == "Replace the towels"
    assert body["repeats"] == "daily"
    assert body["assignment_type"] == "least_done"
    assert body["household"] == {"id": household.id, "name": household.name}
    assert [a["id"] for a in body["assignees"]] == [user.id]
    assert [t["name"] for t in body["tags"]] == ["deep-clean"]

    listed = await client.get("/api/v1/chores")
    assert listed.json()["total"] == 1


async def test_create_chore_minimal(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=household.id))
    assert resp.status_code == 201
    body = resp.json()
    assert body["assignees"] == []
    assert body["tags"] == []
    assert body["description"] is None


async def test_create_chore_sets_initial_current_assignee_and_turn_length(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # alphabetical picks the first assignee by name as the starting current assignee.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    client = await auth_client(anna)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            assignment_type="alphabetical",
            assignee_ids=[bob.id, anna.id],
            turn_length=3,
        ),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["turn_length"] == 3
    assert body["current_assignee"]["id"] == anna.id


async def test_create_chore_defaults_turn_length_to_one_and_no_current_when_empty(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    body = (await client.post("/api/v1/chores", json=_payload(household_id=household.id))).json()
    assert body["turn_length"] == 1
    assert body["current_assignee"] is None  # no assignees -> shared/unassigned


async def test_create_chore_manual_honours_explicit_current_assignee(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    client = await auth_client(anna)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            assignment_type="manual",
            assignee_ids=[anna.id, bob.id],
            current_assignee_id=bob.id,
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["current_assignee"]["id"] == bob.id


async def test_create_chore_current_assignee_outside_pool_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    anna = await make_user(email="anna@example.com")
    outsider = await make_user(email="outsider@example.com")
    household = await make_household(members=[anna, outsider])
    client = await auth_client(anna)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id, assignee_ids=[anna.id], current_assignee_id=outsider.id
        ),
    )
    assert resp.status_code == 400


async def test_create_chore_turn_length_below_one_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores", json=_payload(household_id=household.id, turn_length=0)
    )
    assert resp.status_code == 422


async def test_create_chore_in_chosen_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # A user in several households picks which one the chore belongs to.
    user = await make_user()
    first = await make_household(name="First", members=[user])
    second = await make_household(name="Second", members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=second.id))
    assert resp.status_code == 201
    assert resp.json()["household"] == {"id": second.id, "name": "Second"}
    # ...and not the lowest-id one.
    assert second.id != first.id


async def test_create_chore_foreign_household_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=other.id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Household not found"


async def test_create_chore_deleted_household_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user], deleted_at=datetime.now(UTC))
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=household.id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Household not found"


async def test_create_chore_foreign_assignee_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    household = await make_household(name="Mine", members=[user])
    outsider = await make_user(email="outsider@example.com")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, assignee_ids=[outsider.id]),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Assignees must be members of your household"


async def test_create_chore_inactive_assignee_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    inactive = await make_user(email="ghost@example.com", status=UserStatus.disabled)
    household = await make_household(name="Mine", members=[user, inactive])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, assignee_ids=[inactive.id]),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Assignees must be members of your household"


async def test_create_chore_foreign_tag_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    household = await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_tag = await make_tag(household=other, name="not-mine")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, tag_ids=[other_tag.id]),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Tags must belong to your household"


async def test_create_chore_empty_title_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=household.id, title=""))
    assert resp.status_code == 422


async def test_create_chore_bad_enum_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores", json=_payload(household_id=household.id, repeats="fortnightly")
    )
    assert resp.status_code == 422


async def test_create_chore_missing_household_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload())
    assert resp.status_code == 422


async def test_create_chore_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/chores", json=_payload(household_id=1))
    assert resp.status_code == 401


# --- list ---


async def test_list_chores_empty(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}


async def test_list_chores_with_assignees_and_tags(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="deep-clean", color="#0d9488")
    await make_chore(household=household, title="Scrub the tub", assignees=[user], tags=[tag])
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    chore = body["items"][0]
    assert chore["title"] == "Scrub the tub"
    assert chore["household"] == {"id": household.id, "name": household.name}
    assert [a["id"] for a in chore["assignees"]] == [user.id]
    assert [t["name"] for t in chore["tags"]] == ["deep-clean"]
    assert chore["repeats"] == "weekly"
    assert chore["assignment_type"] == "manual"


async def test_list_chores_excludes_other_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    mine = await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    await make_chore(household=mine, title="Mine chore")
    await make_chore(household=other, title="Other chore")
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 200
    assert [c["title"] for c in resp.json()["items"]] == ["Mine chore"]


async def test_list_chores_spans_all_my_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    first = await make_household(name="First", members=[user])
    second = await make_household(name="Second", members=[user])
    await make_chore(household=first, title="First chore")
    await make_chore(household=second, title="Second chore")
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores?sort_by=title&sort_dir=asc")
    assert [c["title"] for c in resp.json()["items"]] == ["First chore", "Second chore"]


async def test_list_chores_household_filter(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    first = await make_household(name="First", members=[user])
    second = await make_household(name="Second", members=[user])
    await make_chore(household=first, title="First chore")
    await make_chore(household=second, title="Second chore")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/chores?household_id={second.id}")
    assert [c["title"] for c in resp.json()["items"]] == ["Second chore"]


async def test_list_chores_title_filter(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    outside = await make_household(name="Outside")
    await make_chore(household=household, title="Clean the kitchen")
    await make_chore(household=household, title="Clean the bathroom")
    await make_chore(household=household, title="Water the plants")
    # A matching title in a household the user does not belong to must stay hidden.
    await make_chore(household=outside, title="Clean the garage")
    client = await auth_client(user)

    # Case-insensitive substring match, still scoped to my households.
    resp = await client.get("/api/v1/chores?title=CLEAN&sort_by=title&sort_dir=asc")
    assert resp.status_code == 200
    assert [c["title"] for c in resp.json()["items"]] == [
        "Clean the bathroom",
        "Clean the kitchen",
    ]

    # A non-matching term yields an empty page.
    empty = await client.get("/api/v1/chores?title=zzz")
    assert empty.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}

    # A whitespace-only title is a no-op: the whole (in-household) list is returned.
    blank = await client.get("/api/v1/chores?title=%20%20")
    assert blank.json()["total"] == 3


async def test_list_chores_title_filter_escapes_wildcards(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, title="50% off day")
    await make_chore(household=household, title="Full clean")
    client = await auth_client(user)

    # "%" is escaped, so it matches a literal percent sign, not every row.
    resp = await client.get("/api/v1/chores?title=%25")  # %25 = URL-encoded "%"
    assert [c["title"] for c in resp.json()["items"]] == ["50% off day"]


async def test_list_chores_excludes_soft_deleted(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Gone soon")
    await make_chore(household=household, title="Still here")
    client = await auth_client(user)

    await client.delete(f"/api/v1/chores/{chore.id}")

    resp = await client.get("/api/v1/chores")
    assert [c["title"] for c in resp.json()["items"]] == ["Still here"]


async def test_list_chores_excludes_deleted_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    active = await make_household(name="Active", members=[user])
    gone = await make_household(name="Gone", members=[user], deleted_at=datetime.now(UTC))
    await make_chore(household=active, title="Kept")
    await make_chore(household=gone, title="Hidden")
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert [c["title"] for c in resp.json()["items"]] == ["Kept"]


async def test_list_chores_pagination(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    for i in range(5):
        await make_chore(household=household, title=f"Chore {i}")
    client = await auth_client(user)

    first = await client.get("/api/v1/chores?page=1&page_size=2&sort_by=id&sort_dir=asc")
    first_body = first.json()
    assert first_body["total"] == 5
    assert len(first_body["items"]) == 2
    second = await client.get("/api/v1/chores?page=2&page_size=2&sort_by=id&sort_dir=asc")
    first_ids = {c["id"] for c in first_body["items"]}
    second_ids = {c["id"] for c in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert max(first_ids) < min(second_ids)


async def test_list_chores_sort_by_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    for title in ("Gamma", "Alpha", "Beta"):
        await make_chore(household=household, title=title)
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores?sort_by=title&sort_dir=asc")
    assert [c["title"] for c in resp.json()["items"]] == ["Alpha", "Beta", "Gamma"]


async def test_list_chores_sort_by_created_at(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    # created_at is a server_default of now(), which Postgres freezes for the whole
    # transaction, so every fixture chore here would otherwise share one timestamp and the
    # id tiebreaker would decide the order. Setting them by hand, deliberately out of step
    # with the insertion order, is what makes this assert the created_at sort rather than
    # the tiebreaker: an id-desc fallback would answer Middle, Newest, Oldest.
    oldest = await make_chore(household=household, title="Oldest")
    newest = await make_chore(household=household, title="Newest")
    middle = await make_chore(household=household, title="Middle")
    oldest.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    newest.created_at = datetime(2026, 3, 1, tzinfo=UTC)
    middle.created_at = datetime(2026, 2, 1, tzinfo=UTC)
    await db_session.flush()
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores?sort_by=created_at&sort_dir=desc")
    assert [c["title"] for c in resp.json()["items"]] == ["Newest", "Middle", "Oldest"]
    resp = await client.get("/api/v1/chores?sort_by=created_at&sort_dir=asc")
    assert [c["title"] for c in resp.json()["items"]] == ["Oldest", "Middle", "Newest"]


async def test_list_chores_sort_by_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    alpha = await make_household(name="Alpha", members=[user])
    zulu = await make_household(name="Zulu", members=[user])
    await make_chore(household=zulu, title="In Zulu")
    await make_chore(household=alpha, title="In Alpha")
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores?sort_by=household&sort_dir=asc")
    assert [c["household"]["name"] for c in resp.json()["items"]] == ["Alpha", "Zulu"]


async def test_list_chores_invalid_params_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    for query in ("sort_by=bogus", "sort_dir=sideways", "page_size=101", "page=0"):
        resp = await client.get(f"/api/v1/chores?{query}")
        assert resp.status_code == 422, query


async def test_list_chores_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_list_chores_without_household(make_user: MakeUser, auth_client: AuthClient) -> None:
    # No longer a 404: the list scopes across memberships, so no household just
    # means an empty page.
    user = await make_user()
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


# --- get one ---


async def test_get_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Vacuum")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Vacuum"
    assert body["household"] == {"id": household.id, "name": household.name}


async def test_get_chore_other_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_chore = await make_chore(household=other, title="Not mine")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/chores/{other_chore.id}")
    assert resp.status_code == 404


async def test_get_chore_requires_auth(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    client: AsyncClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)

    resp = await client.get(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 401


# --- update ---


async def test_update_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    other_member = await make_user(email="other@example.com")
    household = await make_household(members=[user, other_member])
    tag = await make_tag(household=household, name="urgent")
    chore = await make_chore(household=household, title="Old", assignees=[user])
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(
            title="New",
            description="Updated notes",
            repeats="monthly",
            assignment_type="random",
            assignee_ids=[other_member.id],
            tag_ids=[tag.id],
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New"
    assert body["description"] == "Updated notes"
    assert body["repeats"] == "monthly"
    assert body["assignment_type"] == "random"
    assert [a["id"] for a in body["assignees"]] == [other_member.id]
    assert [t["name"] for t in body["tags"]] == ["urgent"]
    # The household is unchanged and not part of the update payload.
    assert body["household"] == {"id": household.id, "name": household.name}


async def test_update_chore_recomputes_current_assignee_when_dropped_from_pool(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    # alphabetical: the current assignee starts as Anna.
    chore = await make_chore(
        household=household,
        assignment_type=AssignmentType.alphabetical,
        assignees=[anna, bob],
    )
    client = await auth_client(anna)

    # Drop Anna from the pool: the open occurrence's assignee must move off her.
    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(assignment_type="alphabetical", assignee_ids=[bob.id], turn_length=2),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["turn_length"] == 2
    assert body["current_assignee"]["id"] == bob.id


async def test_update_chore_start_date_moves_due_date_before_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # A never-completed chore's open occurrence follows a start_date edit.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, start_date=date(2026, 7, 16), repeats=RepeatPeriod.daily
    )
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(start_date="2026-08-01", repeats="daily")
    )
    assert resp.status_code == 200
    occ = (
        await db_session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one()
    assert occ.scheduled_for == datetime(2026, 8, 1, tzinfo=UTC)


async def test_update_chore_revives_completed_one_off_into_recurring(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Editing a done one-off into a recurring chore materialises a fresh open
    # occurrence, so it becomes due (and completable) again instead of staying dead.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 409  # dead

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(repeats="daily", start_date=today.isoformat())
    )
    assert resp.status_code == 200
    # Revived: completable again.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201


async def test_update_chore_clear_assignees(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, assignees=[user])
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["assignees"] == []


async def test_update_chore_foreign_assignee_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    household = await make_household(members=[user])
    outsider = await make_user(email="outsider@example.com")
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(assignee_ids=[outsider.id])
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Assignees must be members of your household"


async def test_update_chore_foreign_tag_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    household = await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_tag = await make_tag(household=other, name="not-mine")
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(tag_ids=[other_tag.id]))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Tags must belong to your household"


async def test_update_chore_empty_title_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(title=""))
    assert resp.status_code == 422


async def test_update_chore_other_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_chore = await make_chore(household=other, title="Not mine")
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{other_chore.id}", json=_payload(title="Hijack"))
    assert resp.status_code == 404


async def test_update_chore_requires_auth(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    client: AsyncClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(title="Nope"))
    assert resp.status_code == 401


# --- recurrence interval and weekdays ---
#
# Every date here is fixed rather than relative to today, because `_payload` and
# `make_chore` both pin start_date. For reference: 16 Jul 2026 is a Thursday, so that
# week's Tuesday is the 14th and its Friday the 17th; 1 Aug 2026 is a Saturday.


async def test_create_chore_with_interval_and_weekdays(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, repeat_interval=2, weekdays=[TUE, FRI]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["repeat_interval"] == 2
    assert body["weekdays"] == [TUE, FRI]
    # The 16th is a Thursday, so the first occurrence snaps forward to Friday the 17th.
    assert await _open_slot(db_session, body["id"]) == datetime(2026, 7, 17, tzinfo=UTC)


async def test_create_chore_sorts_and_deduplicates_weekdays(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores", json=_payload(household_id=household.id, weekdays=[FRI, TUE, TUE])
    )
    assert resp.status_code == 201
    assert resp.json()["weekdays"] == [TUE, FRI]


async def test_create_chore_empty_weekdays_reads_back_as_null(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # An empty selection means what NULL means - unpinned - so it collapses to null.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores", json=_payload(household_id=household.id, weekdays=[])
    )
    assert resp.status_code == 201
    assert resp.json()["weekdays"] is None


async def test_create_chore_drops_weekdays_for_a_non_weekly_period(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # Normalised, not rejected: the form would otherwise 422 every time someone flipped
    # the period from weekly to daily before clearing the weekday list.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, repeats="daily", weekdays=[TUE, FRI]),
    )
    assert resp.status_code == 201
    assert resp.json()["weekdays"] is None


async def test_create_chore_forces_interval_to_one_for_a_one_off(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # A `manual` chore never recurs, so repeat_interval > 1 in the DB always implies
    # "recurring".
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, repeats="manual", repeat_interval=5),
    )
    assert resp.status_code == 201
    assert resp.json()["repeat_interval"] == 1


async def test_create_chore_defaults_the_recurrence_fields(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # A payload predating these fields still works and behaves exactly as before.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(household_id=household.id))
    assert resp.status_code == 201
    body = resp.json()
    assert body["repeat_interval"] == 1
    assert body["weekdays"] is None


async def test_create_chore_rejects_bad_recurrence_values(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    for bad in ({"repeat_interval": 0}, {"repeat_interval": 366}, {"repeat_interval": "x"}):
        resp = await client.post("/api/v1/chores", json=_payload(household_id=household.id, **bad))
        assert resp.status_code == 422, bad
    for bad_days in ([7], [-1], ["mon"], [1.5]):
        resp = await client.post(
            "/api/v1/chores", json=_payload(household_id=household.id, weekdays=bad_days)
        )
        assert resp.status_code == 422, bad_days


async def test_get_and_list_expose_the_recurrence_fields(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.weekly, repeat_interval=2, weekdays=[TUE, FRI]
    )
    client = await auth_client(user)

    one = await client.get(f"/api/v1/chores/{chore.id}")
    assert one.status_code == 200
    assert one.json()["repeat_interval"] == 2
    assert one.json()["weekdays"] == [TUE, FRI]

    listed = await client.get("/api/v1/chores")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["weekdays"] == [TUE, FRI]


async def test_update_chore_pinning_weekdays_moves_the_open_slot_forward(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Pinning weekdays on a chore with history redefines its grid, so the open row snaps
    # onto it: forward only, and by days rather than a whole cycle.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    done = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 15, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 22, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(weekdays=[TUE]))
    assert resp.status_code == 200
    # Wed 22 Jul -> Tue 28 Jul, the nearest Tuesday forward.
    assert await _open_slot(db_session, chore.id) == datetime(2026, 7, 28, tzinfo=UTC)
    # History is a record of what happened and is never re-gridded.
    await db_session.refresh(done)
    assert done.scheduled_for == datetime(2026, 7, 15, tzinfo=UTC)


async def test_update_chore_pinning_can_push_a_barely_overdue_chore_into_the_future(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The snap moves forward by up to six days, so a chore overdue by fewer than that can
    # leave the overdue bucket. Deliberate rather than a bug - the edit just declared which
    # weekdays the chore happens on - but worth pinning so it cannot change unnoticed.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime.combine(yesterday - timedelta(days=7), time(), tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime.combine(yesterday - timedelta(days=7), time(9), tzinfo=UTC),
    )
    await make_occurrence(
        chore=chore, scheduled_for=datetime.combine(yesterday, time(), tzinfo=UTC)
    )
    client = await auth_client(user)

    # Pin to tomorrow's weekday: the only slot forward of yesterday is two days on.
    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(weekdays=[(today + timedelta(days=1)).weekday()]),
    )
    assert resp.status_code == 200
    assert await _open_slot(db_session, chore.id) == datetime.combine(
        today + timedelta(days=1), time(), tzinfo=UTC
    )


async def test_update_chore_pinning_keeps_an_already_selected_slot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 14, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 21, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(weekdays=[TUE]))
    assert resp.status_code == 200
    # The 21st is already a Tuesday, so snapping is a no-op.
    assert await _open_slot(db_session, chore.id) == datetime(2026, 7, 21, tzinfo=UTC)


async def test_update_chore_interval_change_leaves_the_open_slot_alone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The new stride takes effect from the next completion, so the date shown on Home does
    # not jump just because someone edited the interval.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 15, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 22, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(repeat_interval=3))
    assert resp.status_code == 200
    assert resp.json()["repeat_interval"] == 3
    assert await _open_slot(db_session, chore.id) == datetime(2026, 7, 22, tzinfo=UTC)


async def test_update_chore_start_date_and_weekdays_move_the_first_slot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Before any completion the open row is still the chore's first occurrence, so it
    # follows a start_date edit and a weekday edit together.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.weekly)
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(start_date="2026-08-01", weekdays=[TUE])
    )
    assert resp.status_code == 200
    # 1 Aug 2026 is a Saturday, so the first Tuesday on or after it is the 4th.
    assert await _open_slot(db_session, chore.id) == datetime(2026, 8, 4, tzinfo=UTC)


async def test_update_chore_weekly_to_manual_keeps_the_slot_and_completes_once(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.weekly, weekdays=[TUE], with_occurrence=False
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 14, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 21, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(repeats="manual"))
    assert resp.status_code == 200
    assert resp.json()["weekdays"] is None
    # A one-off keeps the due date it already had, then dies after a single completion.
    assert await _open_slot(db_session, chore.id) == datetime(2026, 7, 21, tzinfo=UTC)
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 409


async def test_update_chore_full_replace_resets_the_recurrence_fields(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # ChoreUpdate is a full replace, so a payload omitting these fields resets them. This
    # is the trap any client has to send them to avoid.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.weekly, repeat_interval=2, weekdays=[TUE, FRI]
    )
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["repeat_interval"] == 1
    assert body["weekdays"] is None


async def test_update_chore_rejects_bad_recurrence_values(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    for bad in ({"repeat_interval": 0}, {"repeat_interval": 366}, {"weekdays": [7]}):
        resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(**bad))
        assert resp.status_code == 422, bad


async def test_update_chore_slot_collision_is_a_conflict_not_a_crash(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Snapping is forward-only, and an open row's slot is always later than every done row's,
    # so this cannot happen through the API. Nothing in the schema enforces that invariant
    # though, so the commit is guarded: a collision must read as 409, never 500.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 28, tzinfo=UTC),  # deliberately after the open row
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 22, tzinfo=UTC))
    client = await auth_client(user)

    # Wed 22 Jul snaps to Tue 28 Jul, which the done row already occupies.
    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(weekdays=[TUE]))
    assert resp.status_code == 409


# --- delete (soft) ---


async def test_delete_chore_soft(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 204

    # Hidden from the list...
    listed = await client.get("/api/v1/chores")
    assert listed.json()["items"] == []
    # ...but the row remains, with deleted_at set (soft delete).
    remaining = (
        await db_session.execute(select(Chore).where(Chore.id == chore.id))
    ).scalar_one_or_none()
    assert remaining is not None
    assert remaining.deleted_at is not None


async def test_delete_chore_already_deleted_not_found(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/chores/{chore.id}")).status_code == 204
    # A second delete can't find the soft-deleted chore.
    assert (await client.delete(f"/api/v1/chores/{chore.id}")).status_code == 404


async def test_delete_chore_not_found(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.delete("/api/v1/chores/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Chore not found"


async def test_delete_chore_from_other_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_chore = await make_chore(household=other, title="Not mine")
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/chores/{other_chore.id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Chore not found"


async def test_delete_chore_requires_auth(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    client: AsyncClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)

    resp = await client.delete(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 401
