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


async def test_list_tags_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/tags")
    assert resp.status_code == 401
