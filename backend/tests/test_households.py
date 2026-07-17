from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models import Household, User, UserStatus

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def test_list_households_with_members(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com", first_name="Alice", last_name="Adams")
    bob = await make_user(email="bob@example.com", first_name="Bob", last_name="Brown")
    await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Flat 3B"
    assert {m["first_name"] for m in body[0]["members"]} == {"Alice", "Bob"}
    assert {m["last_name"] for m in body[0]["members"]} == {"Adams", "Brown"}
    # data minimisation: the picker payload carries no email
    assert "email" not in body[0]["members"][0]


async def test_list_households_excludes_inactive_members(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com", first_name="Alice", last_name="Adams")
    ghost = await make_user(
        email="ghost@example.com",
        first_name="Ghost",
        last_name="Gone",
        status=UserStatus.disabled,
    )
    await make_household(name="Flat 3B", members=[alice, ghost])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    assert {m["first_name"] for m in resp.json()[0]["members"]} == {"Alice"}


async def test_list_households_only_mine(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Mine", members=[alice])
    await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    assert [h["name"] for h in resp.json()] == ["Mine"]


async def test_list_households_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/households")
    assert resp.status_code == 401
