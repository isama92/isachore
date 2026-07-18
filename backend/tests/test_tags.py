from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models import Household, Tag, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeTag = Callable[..., Awaitable[Tag]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def test_list_tags(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    await make_tag(household=household, name="deep-clean", color="#0d9488")
    await make_tag(household=household, name="shared", color="#7c6bf0")
    client = await auth_client(user)

    resp = await client.get("/api/v1/tags")
    assert resp.status_code == 200
    body = resp.json()
    assert [t["name"] for t in body] == ["deep-clean", "shared"]
    assert body[0]["color"] == "#0d9488"


async def test_list_tags_scoped_to_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    mine = await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    await make_tag(household=mine, name="mine-tag")
    await make_tag(household=other, name="other-tag")
    client = await auth_client(user)

    resp = await client.get("/api/v1/tags")
    assert [t["name"] for t in resp.json()] == ["mine-tag"]


async def test_list_tags_for_chosen_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    # With an explicit household_id, the tag picker loads that household's tags
    # rather than the caller's lowest-id one.
    user = await make_user()
    first = await make_household(name="First", members=[user])
    second = await make_household(name="Second", members=[user])
    await make_tag(household=first, name="first-tag")
    await make_tag(household=second, name="second-tag")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/tags?household_id={second.id}")
    assert resp.status_code == 200
    assert [t["name"] for t in resp.json()] == ["second-tag"]


async def test_list_tags_foreign_household_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/tags?household_id={other.id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Household not found"


async def test_list_tags_without_household(make_user: MakeUser, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.get("/api/v1/tags")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "You are not a member of any household"


async def test_list_tags_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/tags")
    assert resp.status_code == 401
