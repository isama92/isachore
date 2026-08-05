from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.richtext import MAX_RICH_TEXT_LENGTH
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
    assert body["household"] == {
        "id": household.id,
        "name": household.name,
        "timezone": household.timezone,
    }
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
    assert resp.json()["household"] == {"id": second.id, "name": "Second", "timezone": "UTC"}
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
    assert chore["household"] == {
        "id": household.id,
        "name": household.name,
        "timezone": household.timezone,
    }
    assert [a["id"] for a in chore["assignees"]] == [user.id]
    assert [t["name"] for t in chore["tags"]] == ["deep-clean"]
    assert chore["repeats"] == "weekly"
    assert chore["assignment_type"] == "manual"


async def test_list_chores_reports_a_description_flag_not_the_html(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The management table never renders the markup, and at 100 rows a page a
    # MAX_RICH_TEXT_LENGTH field on each was the largest payload in the app.
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, title="With", description="<p>Under the sink</p>")
    await make_chore(household=household, title="Without", description=None)
    client = await auth_client(user)

    items = (await client.get("/api/v1/chores?sort_by=title")).json()["items"]
    assert [(c["title"], c["has_description"]) for c in items] == [
        ("With", True),
        ("Without", False),
    ]
    assert all("description" not in c for c in items)


async def test_list_chores_treats_visually_empty_html_as_no_description(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # Posted through the API rather than seeded, because the coupling being pinned is
    # end-to-end: an untouched editor submits <p><br></p>, the write path collapses it to
    # NULL, and *that* is what lets the flag be a bare IS NOT NULL rather than needing an
    # emptiness check of its own. Seeding a pre-sanitised value would only re-test
    # core.richtext.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)
    created = await client.post(
        "/api/v1/chores",
        json={
            "household_id": household.id,
            "title": "Looks written in, is not",
            "description": "<p><br></p>",
            "start_date": "2026-07-16",
            "repeats": "weekly",
            "assignment_type": "manual",
        },
    )
    assert created.status_code == 201
    assert created.json()["description"] is None

    assert (await client.get("/api/v1/chores")).json()["items"][0]["has_description"] is False


async def test_list_chore_row_carries_no_more_than_the_table_needs(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Deliberately an exact set, mirroring test_unscheduled / test_home: a subset check
    # would pass while `description` crept back in. Adding a field here means extending
    # this list on purpose, which is the review moment worth keeping.
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, description="<p>Under the sink</p>")
    client = await auth_client(user)

    item = (await client.get("/api/v1/chores")).json()["items"][0]
    assert set(item) == {
        "id",
        "title",
        "has_description",
        "start_date",
        "repeats",
        "assignment_type",
        "turn_length",
        "repeat_interval",
        "weekdays",
        "created_at",
        "household",
        "assignees",
        "current_assignee",
        "tags",
    }


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
    assert body["household"] == {
        "id": household.id,
        "name": household.name,
        "timezone": household.timezone,
    }


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
    assert body["household"] == {
        "id": household.id,
        "name": household.name,
        "timezone": household.timezone,
    }


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


async def test_update_chore_honours_explicit_current_assignee_for_an_auto_strategy(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The chore edit page offers the current-assignee picker for every strategy, not
    # just manual, which rests entirely on _reconcile_open_occurrence having no
    # assignment_type gate around the explicit choice. Nothing else pins that: the
    # frontend mocks fetch, and the other update cases only cover the null re-derive.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    # alphabetical would derive Anna on its own, so asking for Bob is a real override.
    chore = await make_chore(
        household=household,
        assignment_type=AssignmentType.alphabetical,
        assignees=[anna, bob],
    )
    client = await auth_client(anna)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(
            assignment_type="alphabetical",
            assignee_ids=[anna.id, bob.id],
            current_assignee_id=bob.id,
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["current_assignee"]["id"] == bob.id


async def test_update_chore_rejects_a_current_assignee_outside_the_pool(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    chore = await make_chore(household=household, assignees=[anna])
    client = await auth_client(anna)

    # Bob is a household member but not an assignee, so he cannot be "on it".
    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(assignee_ids=[anna.id], current_assignee_id=bob.id),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "The current assignee must be one of the chore's assignees"


async def test_completing_after_an_override_re_derives_the_next_assignee(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The UI tells the user an override "applies to the current turn; the next one
    # follows the rotation again". This is that promise: completing hands off through
    # the strategy from whoever was pinned, rather than sticking on them.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    cara = await make_user(email="cara@example.com", first_name="Cara")
    household = await make_household(members=[anna, bob, cara])
    chore = await make_chore(
        household=household,
        assignment_type=AssignmentType.alphabetical,
        assignees=[anna, bob, cara],
        repeats=RepeatPeriod.daily,
    )
    client = await auth_client(anna)

    override = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(
            assignment_type="alphabetical",
            repeats="daily",
            assignee_ids=[anna.id, bob.id, cara.id],
            current_assignee_id=cara.id,
        ),
    )
    assert override.json()["current_assignee"]["id"] == cara.id

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    after = await client.get(f"/api/v1/chores/{chore.id}")
    # Alphabetical order is Anna, Bob, Cara: the successor to the pinned Cara wraps to
    # Anna. Notably NOT Cara again, and not Bob (who would be next from the derived
    # Anna the chore started on).
    assert after.json()["current_assignee"]["id"] == anna.id


async def test_an_override_holds_for_the_rest_of_a_multi_completion_turn(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # With turn_length > 1 the hint's "applies to the current turn" is doing real work:
    # the override survives a completion, because should_reassign counts the chore's
    # total completions rather than counting from the override. Getting this wrong in
    # either direction (handing off immediately, or sticking forever) would make the
    # copy a lie, so pin the boundary from both sides.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    chore = await make_chore(
        household=household,
        assignment_type=AssignmentType.alphabetical,
        assignees=[anna, bob],
        repeats=RepeatPeriod.daily,
        turn_length=2,
    )
    client = await auth_client(anna)

    body = _payload(
        assignment_type="alphabetical",
        repeats="daily",
        turn_length=2,
        assignee_ids=[anna.id, bob.id],
        current_assignee_id=bob.id,
    )
    override = await client.patch(f"/api/v1/chores/{chore.id}", json=body)
    assert override.json()["current_assignee"]["id"] == bob.id

    # First completion of a two-per-turn chore: still Bob's turn.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    mid = await client.get(f"/api/v1/chores/{chore.id}")
    assert mid.json()["current_assignee"]["id"] == bob.id

    # Second completes the turn, so it hands off through the strategy.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    after = await client.get(f"/api/v1/chores/{chore.id}")
    assert after.json()["current_assignee"]["id"] == anna.id


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


async def test_update_chore_revives_a_chore_with_no_open_occurrence(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # A chore with completion history but no open occurrence: what the pre-unscheduled
    # one-off semantics left behind (the migration reopens those, and a concurrent undo can
    # produce it too). Editing it materialises a fresh open occurrence rather than leaving a
    # chore nothing can ever complete.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.manual, with_occurrence=False
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 14, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
    )
    client = await auth_client(user)

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


async def test_create_chore_forces_interval_to_one_when_unscheduled(
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


async def test_create_unscheduled_chore_drops_the_start_date(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # An unscheduled chore has no start: the date is dropped rather than rejected (the same
    # ignore-when-irrelevant rule as repeat_interval above, so a form that has not cleared
    # the field yet still works), and its first occurrence opens at creation time instead.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)
    before = datetime.now(UTC)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, repeats="manual", start_date="2020-01-01"),
    )
    assert resp.status_code == 201
    assert resp.json()["start_date"] is None
    # Opened now, NOT at the 2020 date it was told: an unscheduled chore that dated its slot
    # from a stale payload would read as "waiting since 2020".
    assert before <= await _open_slot(db_session, resp.json()["id"]) <= datetime.now(UTC)


async def test_create_chore_without_start_date_is_rejected_when_it_recurs(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # The one part of the schedule that is rejected rather than normalised: a recurring chore
    # needs a start date to seed its first slot, and defaulting it would silently invent a
    # schedule. Sent WITH a recurring period, so this pins the requirement rather than the
    # unscheduled path that drops the field.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    payload = _payload(household_id=household.id, repeats="weekly")
    del payload["start_date"]
    resp = await client.post("/api/v1/chores", json=payload)
    assert resp.status_code == 422


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
    # Going unscheduled drops the start date, and the open slot stands: there is no grid
    # left to snap it to, and it now records availability rather than a due date.
    assert resp.json()["start_date"] is None
    assert await _open_slot(db_session, chore.id) == datetime(2026, 7, 21, tzinfo=UTC)
    # ...and it stays completable, over and over, rather than dying after one completion.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201


async def test_update_chore_unscheduled_to_recurring_restarts_from_the_new_date(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # An unscheduled chore's open slot is its last completion moment ("available since"), not
    # a grid position, so giving the chore a schedule has to re-seed the slot from the start
    # date the user picked. Snapping it instead would hand a non-deadline to the due
    # machinery and land a chore dated "today" a month overdue.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.manual, with_occurrence=False
    )
    # Done 30 days ago, and reopened at that moment (what completing an unscheduled chore
    # writes). The completion is what makes this the case snap_to_slot used to mishandle.
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime.now(UTC) - timedelta(days=40),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=datetime.now(UTC) - timedelta(days=30),
    )
    await make_occurrence(chore=chore, scheduled_for=datetime.now(UTC) - timedelta(days=30))
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(repeats="daily", start_date=today.isoformat())
    )
    assert resp.status_code == 200

    midnight_today = datetime(today.year, today.month, today.day, tzinfo=UTC)
    assert await _open_slot(db_session, chore.id) == midnight_today
    # ...and it therefore reads as due today rather than a month overdue.
    home = (await client.get("/api/v1/home")).json()
    assert [(i["title"], i["days_until_due"]) for i in home["items"]] == [(chore.title, 0)]


async def test_update_chore_back_to_recurring_skips_slots_already_completed(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # "Did it today, parked it as unscheduled, later put it back on a schedule" is an ordinary
    # sequence, and the form pre-fills the revealed start date with today - which re-seeds the
    # slot onto a midnight the chore already has a `done` row for. Assigning that blind trips
    # uq_occurrence_chore_scheduled and surfaces a 409 no retry can clear, since the same edit
    # recomputes the same occupied slot every time.
    #
    # Driven entirely through the API: the collision only shows up in the real create ->
    # complete -> edit -> complete -> edit order.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    midnight = datetime(today.year, today.month, today.day, tzinfo=UTC)
    client = await auth_client(user)

    created = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, repeats="weekly", start_date=today.isoformat()),
    )
    chore_id = created.json()["id"]
    # Completes today's slot (a done row at midnight today) and opens next week's.
    assert (await client.post(f"/api/v1/chores/{chore_id}/complete")).status_code == 201
    # Park it: the open slot stays a week out, since an unscheduled chore keeps its slot.
    assert (
        await client.patch(f"/api/v1/chores/{chore_id}", json=_payload(repeats="manual"))
    ).status_code == 200
    # Completing it now writes a done row at NEXT week's midnight too, and reopens at `now`.
    assert (await client.post(f"/api/v1/chores/{chore_id}/complete")).status_code == 201

    resp = await client.patch(
        f"/api/v1/chores/{chore_id}",
        json=_payload(repeats="weekly", start_date=today.isoformat()),
    )
    assert resp.status_code == 200
    # Today and today+7 are both spent, so the chore is due today+14: the walk continues past
    # every completed slot, where advancing a single step would have landed on the second one.
    assert await _open_slot(db_session, chore_id) == midnight + timedelta(days=14)


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


async def test_update_chore_snap_skips_a_slot_already_completed(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # A done row LATER than the open one, which unscheduled chores made reachable: one anchors
    # its successors at completion timestamps, so a chore parked as unscheduled for a while ends
    # up with done rows on both sides of its open row. Pinning a weekday then snaps forward onto
    # the occupied slot, and assigning it would trip uq_occurrence_chore_scheduled and 409.
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

    # Wed 22 Jul snaps to Tue 28 Jul, which the done row already occupies...
    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(weekdays=[TUE]))
    assert resp.status_code == 200
    # ...so it carries on to the following Tuesday rather than conflicting. A slot the chore has
    # already been completed for is not one it can be due for again.
    assert await _open_slot(db_session, chore.id) == datetime(2026, 8, 4, tzinfo=UTC)


async def test_update_chore_snap_skips_a_slot_that_was_skipped(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The same slot conflict, but the occupying row is a SKIP rather than a completion.

    `_free_slot_from` is one of the two queries that deliberately does not filter skipped rows
    out (see `ChoreOccurrence.skipped`): the question is which slots are taken, and a skipped
    slot is taken. Without this the previous test passes either way, since its occupying row is
    an ordinary completion - so adding `skipped.is_(False)` there would look free while
    reintroducing a 409 that retrying can never clear.
    """
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 28, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
        skipped=True,
    )
    await make_occurrence(chore=chore, scheduled_for=datetime(2026, 7, 22, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(weekdays=[TUE]))
    assert resp.status_code == 200
    assert await _open_slot(db_session, chore.id) == datetime(2026, 8, 4, tzinfo=UTC)


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


# --- description sanitisation ---
# The allowlist itself is covered exhaustively in test_richtext.py. These prove it is wired
# into both write paths and that the response reflects what was stored, which is what a
# validator that is merely importable would fail.


async def test_create_chore_sanitises_the_description(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            description=(
                '<h1>Steps</h1><p onclick="x">Scrub the tub<script>alert(1)</script></p>'
                '<ul><li>towels</li></ul><img src="data:image/png;base64,AAA">'
            ),
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["description"] == ("Steps<p>Scrub the tub</p><ul><li>towels</li></ul>")


async def test_update_chore_sanitises_the_description(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(description='<p style="position:fixed">notes</p><iframe></iframe>'),
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "<p>notes</p>"


async def test_create_chore_stores_null_for_visually_empty_html(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    # Deliberately NOT "": an empty string already became None before rich text, so it would
    # pass whether or not the blank-HTML collapse exists. Each of these is a truthy string
    # that an untouched editor really does submit.
    for blank in ("<p></p>", "<p><br></p>", "<p>&nbsp;</p>", "<script>alert(1)</script>"):
        resp = await client.post(
            "/api/v1/chores", json=_payload(household_id=household.id, description=blank)
        )
        assert resp.status_code == 201, blank
        assert resp.json()["description"] is None, blank


async def test_update_chore_clears_a_description_with_visually_empty_html(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, description="<p>old notes</p>")
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}", json=_payload(description="<p><br></p>")
    )
    assert resp.status_code == 200
    assert resp.json()["description"] is None


async def test_write_paths_reject_an_oversized_description(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    over = "<p>" + ("x" * MAX_RICH_TEXT_LENGTH) + "</p>"
    # Markup that sanitises down to two characters but arrives oversized. This is the case
    # that pins the ordering: the cap has to bound what the server agrees to parse, so a
    # payload cannot buy its way under the limit by being mostly junk that gets stripped.
    junk = "<table>" * 4_000 + "hi" + "</table>" * 4_000

    for bad in (over, junk):
        resp = await client.post(
            "/api/v1/chores", json=_payload(household_id=household.id, description=bad)
        )
        assert resp.status_code == 422, len(bad)
        resp = await client.patch(f"/api/v1/chores/{chore.id}", json=_payload(description=bad))
        assert resp.status_code == 422, len(bad)


async def test_description_at_the_length_limit_is_accepted(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(household_id=household.id, description="x" * MAX_RICH_TEXT_LENGTH),
    )
    assert resp.status_code == 201
    assert resp.json()["description"] == "x" * MAX_RICH_TEXT_LENGTH


# --- clearing the current assignee ---
# `current_assignee_id: null` deliberately means "no explicit choice" and keeps a still-valid
# assignee, so `clear_current_assignee` is the only way to say "nobody". An unassigned chore is
# shared: home.py's assignee filter keeps unassigned chores for every member.


async def test_update_chore_clears_the_current_assignee(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bram = await make_user(email="bram@example.com", first_name="Bram")
    household = await make_household(members=[anna, bram])
    chore = await make_chore(household=household, assignees=[anna, bram])
    client = await auth_client(anna)

    # Assign, then unassign, so the clear has something to undo.
    assigned = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(assignee_ids=[anna.id, bram.id], current_assignee_id=anna.id),
    )
    assert assigned.json()["current_assignee"]["id"] == anna.id

    cleared = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(assignee_ids=[anna.id, bram.id], clear_current_assignee=True),
    )
    assert cleared.status_code == 200
    assert cleared.json()["current_assignee"] is None
    # The pool is untouched: unassigned means "nobody in particular right now", not "nobody can
    # ever be given this".
    assert {a["id"] for a in cleared.json()["assignees"]} == {anna.id, bram.id}


async def test_update_chore_keeps_a_valid_assignee_when_none_is_given(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    """The reason clear_current_assignee has to exist at all. A null current_assignee_id means
    "no opinion" and must NOT clear, because ChoreForm submits null whenever its picker is
    hidden - so if this regressed, editing a chore's title would silently unassign it."""
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bram = await make_user(email="bram@example.com", first_name="Bram")
    household = await make_household(members=[anna, bram])
    chore = await make_chore(household=household, assignees=[anna, bram])
    client = await auth_client(anna)

    await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(assignee_ids=[anna.id, bram.id], current_assignee_id=bram.id),
    )
    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(title="Renamed", assignee_ids=[anna.id, bram.id], current_assignee_id=None),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed"
    assert resp.json()["current_assignee"]["id"] == bram.id


async def test_clear_current_assignee_wins_over_an_explicit_choice(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Both fields set is a contradictory payload; the clear is documented as taking precedence,
    # so this pins which one wins rather than leaving it to whichever branch runs first.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    household = await make_household(members=[anna])
    chore = await make_chore(household=household, assignees=[anna])
    client = await auth_client(anna)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(
            assignee_ids=[anna.id], current_assignee_id=anna.id, clear_current_assignee=True
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["current_assignee"] is None


async def test_clear_current_assignee_survives_an_auto_strategy_reconcile(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    """The branch-ordering guard. `alphabetical` would otherwise re-derive an assignee from the
    strategy the moment the clear left the slot empty, so a clear that merely fell through to
    the "recompute" elif would look like it did nothing."""
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bram = await make_user(email="bram@example.com", first_name="Bram")
    household = await make_household(members=[anna, bram])
    chore = await make_chore(
        household=household, assignees=[anna, bram], assignment_type=AssignmentType.alphabetical
    )
    client = await auth_client(anna)

    resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json=_payload(
            assignee_ids=[anna.id, bram.id],
            assignment_type="alphabetical",
            clear_current_assignee=True,
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["current_assignee"] is None


async def test_create_chore_can_start_unassigned_under_an_auto_strategy(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # Without the flag an auto strategy always picks somebody at creation, so this is the only
    # way to create a shared chore that already has a rotation pool.
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bram = await make_user(email="bram@example.com", first_name="Bram")
    household = await make_household(members=[anna, bram])
    client = await auth_client(anna)

    resp = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            assignment_type="alphabetical",
            assignee_ids=[anna.id, bram.id],
            clear_current_assignee=True,
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["current_assignee"] is None

    # And the default still picks somebody, so the flag is what changed the outcome.
    plain = await client.post(
        "/api/v1/chores",
        json=_payload(
            household_id=household.id,
            title="Other",
            assignment_type="alphabetical",
            assignee_ids=[anna.id, bram.id],
        ),
    )
    assert plain.json()["current_assignee"]["id"] == anna.id
