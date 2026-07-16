from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models import Chore, Household, Tag, User

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
    assert [a["id"] for a in body["assignees"]] == [user.id]
    assert [t["name"] for t in body["tags"]] == ["deep-clean"]

    listed = await client.get("/api/v1/chores")
    assert len(listed.json()) == 1


async def test_create_chore_minimal(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["assignees"] == []
    assert body["tags"] == []
    assert body["description"] is None


async def test_create_chore_foreign_assignee_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    outsider = await make_user(email="outsider@example.com")
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(assignee_ids=[outsider.id]))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Assignees must be members of your household"


async def test_create_chore_foreign_tag_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    other_tag = await make_tag(household=other, name="not-mine")
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(tag_ids=[other_tag.id]))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Tags must belong to your household"


async def test_create_chore_empty_title_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(title=""))
    assert resp.status_code == 422


async def test_create_chore_bad_enum_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload(repeats="fortnightly"))
    assert resp.status_code == 422


async def test_create_chore_without_household(make_user: MakeUser, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.post("/api/v1/chores", json=_payload())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "You are not a member of any household"


async def test_create_chore_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/chores", json=_payload())
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
    assert resp.json() == []


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
    assert len(body) == 1
    chore = body[0]
    assert chore["title"] == "Scrub the tub"
    assert [a["id"] for a in chore["assignees"]] == [user.id]
    assert [t["name"] for t in chore["tags"]] == ["deep-clean"]
    assert chore["repeats"] == "weekly"
    assert chore["assignment_type"] == "manual"


async def test_list_chores_scoped_to_household(
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
    titles = [c["title"] for c in resp.json()]
    assert titles == ["Mine chore"]


async def test_list_chores_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_list_chores_without_household(make_user: MakeUser, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "You are not a member of any household"


# --- delete ---


async def test_delete_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 204

    listed = await client.get("/api/v1/chores")
    assert listed.json() == []


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
