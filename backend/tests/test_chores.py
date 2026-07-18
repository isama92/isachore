from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, Household, Tag, User, UserStatus

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeTag = Callable[..., Awaitable[Tag]]
MakeChore = Callable[..., Awaitable[Chore]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Clean the bathroom",
        "start_date": "2026-07-16",
        "repeats": "weekly",
        "assignment_type": "manual",
    }
    base.update(overrides)
    return base


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
