from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, Household, Tag, User
from app.models.chore import chore_tags

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeTag = Callable[..., Awaitable[Tag]]
MakeChore = Callable[..., Awaitable[Chore]]
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


# --- create -----------------------------------------------------------------


async def test_create_tag(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/tags",
        json={"household_id": household.id, "name": "urgent", "color": "#ff0000"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "urgent"
    assert body["color"] == "#ff0000"

    # It shows up in the household's list.
    listed = await client.get("/api/v1/tags")
    assert [t["name"] for t in listed.json()] == ["urgent"]


async def test_create_tag_foreign_household_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/tags",
        json={"household_id": other.id, "name": "sneaky", "color": "#0d9488"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Household not found"


async def test_create_tag_duplicate_name_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    await make_tag(household=household, name="shared", color="#7c6bf0")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/tags",
        json={"household_id": household.id, "name": "shared", "color": "#0d9488"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "A tag with this name already exists"


async def test_create_tag_same_name_other_household_allowed(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # The unique constraint is per-household, so the same name is fine elsewhere.
    user = await make_user()
    first = await make_household(name="First", members=[user])
    second = await make_household(name="Second", members=[user])
    client = await auth_client(user)

    a = await client.post(
        "/api/v1/tags", json={"household_id": first.id, "name": "shared", "color": "#0d9488"}
    )
    b = await client.post(
        "/api/v1/tags", json={"household_id": second.id, "name": "shared", "color": "#0d9488"}
    )
    assert a.status_code == 201
    assert b.status_code == 201


async def test_create_tag_rejects_bad_input(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    async def post(name: str, color: str) -> int:
        resp = await client.post(
            "/api/v1/tags", json={"household_id": household.id, "name": name, "color": color}
        )
        return resp.status_code

    assert await post("", "#0d9488") == 422  # blank name
    assert await post("x" * 51, "#0d9488") == 422  # name too long
    assert await post("ok", "teal") == 422  # colour not a hex
    assert await post("ok", "#0d948") == 422  # colour too short


async def test_create_tag_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/tags", json={"household_id": 1, "name": "x", "color": "#0d9488"}
    )
    assert resp.status_code == 401


# --- get one ----------------------------------------------------------------


async def test_get_tag(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="deep-clean", color="#0d9488")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/tags/{tag.id}")
    assert resp.status_code == 200
    assert resp.json() == {"id": tag.id, "name": "deep-clean", "color": "#0d9488"}


async def test_get_tag_foreign_household_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    tag = await make_tag(household=other, name="other-tag")
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/tags/{tag.id}")
    assert resp.status_code == 404


async def test_get_tag_not_found(make_user: MakeUser, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.get("/api/v1/tags/99999")
    assert resp.status_code == 404


# --- update -----------------------------------------------------------------


async def test_update_tag(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="old", color="#0d9488")
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/tags/{tag.id}", json={"name": "new", "color": "#ff0000"})
    assert resp.status_code == 200
    assert resp.json() == {"id": tag.id, "name": "new", "color": "#ff0000"}

    reloaded = await client.get(f"/api/v1/tags/{tag.id}")
    assert reloaded.json()["name"] == "new"


async def test_update_tag_duplicate_name_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    await make_tag(household=household, name="taken", color="#0d9488")
    mine = await make_tag(household=household, name="mine", color="#7c6bf0")
    client = await auth_client(user)

    resp = await client.patch(f"/api/v1/tags/{mine.id}", json={"name": "taken", "color": "#7c6bf0"})
    assert resp.status_code == 409


async def test_update_tag_foreign_household_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    tag = await make_tag(household=other, name="other-tag")
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/tags/{tag.id}", json={"name": "hijacked", "color": "#0d9488"}
    )
    assert resp.status_code == 404


async def test_update_tag_rejects_bad_input(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="ok")
    client = await auth_client(user)

    blank = await client.patch(f"/api/v1/tags/{tag.id}", json={"name": "", "color": "#0d9488"})
    bad_color = await client.patch(f"/api/v1/tags/{tag.id}", json={"name": "ok", "color": "teal"})
    assert blank.status_code == 422
    assert bad_color.status_code == 422


async def test_get_tag_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/tags/1")
    assert resp.status_code == 401


async def test_update_tag_requires_auth(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/tags/1", json={"name": "x", "color": "#0d9488"})
    assert resp.status_code == 401


async def test_delete_tag_requires_auth(client: AsyncClient) -> None:
    resp = await client.delete("/api/v1/tags/1")
    assert resp.status_code == 401


# --- delete -----------------------------------------------------------------


async def test_delete_tag(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="temporary")
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/tags/{tag.id}")
    assert resp.status_code == 204

    listed = await client.get("/api/v1/tags")
    assert listed.json() == []


async def test_delete_tag_foreign_household_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    user = await make_user(email="me@example.com")
    await make_household(name="Mine", members=[user])
    other = await make_household(name="Other")
    tag = await make_tag(household=other, name="other-tag")
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/tags/{tag.id}")
    assert resp.status_code == 404


async def test_delete_tag_not_found(make_user: MakeUser, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.delete("/api/v1/tags/99999")
    assert resp.status_code == 404


async def test_delete_tag_detaches_from_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Deleting a tag that a chore uses removes it from the chore (chore_tags
    # cascade) without deleting the chore itself.
    user = await make_user()
    household = await make_household(members=[user])
    tag = await make_tag(household=household, name="deep-clean")
    chore = await make_chore(household=household, title="Scrub", tags=[tag])
    tag_id, chore_id = tag.id, chore.id
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/tags/{tag_id}")
    assert resp.status_code == 204

    # The join row is gone (chore_tags cascade) but the chore itself survives.
    # Assert at the DB level: the shared test session's identity map would keep a
    # stale chore.tags collection (production uses a fresh session per request).
    links = await db_session.scalar(
        select(func.count()).select_from(chore_tags).where(chore_tags.c.tag_id == tag_id)
    )
    assert links == 0
    surviving = await db_session.scalar(select(Chore).where(Chore.id == chore_id))
    assert surviving is not None
