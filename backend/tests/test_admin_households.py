from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Household, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


# --- list ---------------------------------------------------------------


async def test_admin_list_all_households(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await make_household(name="Mine", members=[member])
    await make_household(name="Empty")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/households")
    assert resp.status_code == 200
    body = resp.json()
    # Admin sees every household, even ones they don't belong to.
    assert body["total"] == 2
    assert {h["name"] for h in body["items"]} == {"Mine", "Empty"}


async def test_admin_list_status_filter(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_household(name="Active")
    await make_household(name="Gone", deleted_at=datetime.now(UTC))
    client = await auth_client(admin)

    active = await client.get("/api/v1/admin/households?status=active")
    assert [h["name"] for h in active.json()["items"]] == ["Active"]

    deleted = await client.get("/api/v1/admin/households?status=deleted")
    assert [h["name"] for h in deleted.json()["items"]] == ["Gone"]

    everything = await client.get("/api/v1/admin/households?status=all")
    assert {h["name"] for h in everything.json()["items"]} == {"Active", "Gone"}


async def test_admin_list_default_hides_deleted(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_household(name="Active")
    await make_household(name="Gone", deleted_at=datetime.now(UTC))
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/households")
    assert [h["name"] for h in resp.json()["items"]] == ["Active"]


async def test_admin_list_as_member_forbidden(make_user: MakeUser, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.get("/api/v1/admin/households")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin only"


async def test_admin_list_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/households")
    assert resp.status_code == 401


async def test_admin_list_invalid_status_rejected(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.get("/api/v1/admin/households?status=bogus")
    assert resp.status_code == 422


# --- create -------------------------------------------------------------


async def test_admin_create_household_owns_and_joins(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post("/api/v1/admin/households", json={"name": "HQ"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "HQ"
    # admin_id is required and must be a member, so the creating admin becomes
    # the owner and first member.
    assert body["admin_id"] == admin.id
    assert body["member_count"] == 1


async def test_admin_create_as_member_forbidden(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.post("/api/v1/admin/households", json={"name": "Nope"})
    assert resp.status_code == 403


# --- detail / update ----------------------------------------------------


async def test_admin_get_deleted_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    gone = await make_household(name="Gone", deleted_at=datetime.now(UTC))
    client = await auth_client(admin)

    resp = await client.get(f"/api/v1/admin/households/{gone.id}")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is not None


async def test_admin_get_missing_household_404(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.get("/api/v1/admin/households/999999")
    assert resp.status_code == 404


async def test_admin_update_any_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    household = await make_household(name="Old", members=[member])
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/admin/households/{household.id}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


# --- soft delete / restore ----------------------------------------------


async def test_admin_delete_household_soft(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    household = await make_household(name="Flat 3B")
    client = await auth_client(admin)

    resp = await client.delete(f"/api/v1/admin/households/{household.id}")
    assert resp.status_code == 204

    refreshed = await db_session.get(Household, household.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.deleted_at is not None


async def test_admin_delete_missing_household_404(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.delete("/api/v1/admin/households/999999")
    assert resp.status_code == 404


async def test_admin_restore_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    gone = await make_household(name="Gone", deleted_at=datetime.now(UTC))
    client = await auth_client(admin)

    resp = await client.post(f"/api/v1/admin/households/{gone.id}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None

    # It is active again, so the default listing shows it.
    listing = await client.get("/api/v1/admin/households")
    assert [h["name"] for h in listing.json()["items"]] == ["Gone"]


async def test_admin_restore_as_member_forbidden(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    member = await make_user(email="member@example.com")
    gone = await make_household(name="Gone", deleted_at=datetime.now(UTC))
    client = await auth_client(member)
    resp = await client.post(f"/api/v1/admin/households/{gone.id}/restore")
    assert resp.status_code == 403


# --- members ------------------------------------------------------------


async def test_admin_list_members(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", first_name="Mabel")
    household = await make_household(name="Flat 3B", members=[member])
    client = await auth_client(admin)

    resp = await client.get(f"/api/v1/admin/households/{household.id}/members")
    assert resp.status_code == 200
    assert [m["first_name"] for m in resp.json()["items"]] == ["Mabel"]


async def test_admin_remove_member(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    # owner is members[0] -> the household admin; member is a plain member.
    household = await make_household(name="Flat 3B", members=[owner, member])
    client = await auth_client(admin)

    resp = await client.delete(f"/api/v1/admin/households/{household.id}/members/{member.id}")
    assert resp.status_code == 204

    listing = await client.get(f"/api/v1/admin/households/{household.id}/members")
    assert {m["id"] for m in listing.json()["items"]} == {owner.id}


async def test_admin_remove_owner_conflict(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    household = await make_household(name="Flat 3B", members=[owner])
    client = await auth_client(admin)

    # Even a site admin must transfer ownership before removing the owner.
    resp = await client.delete(f"/api/v1/admin/households/{household.id}/members/{owner.id}")
    assert resp.status_code == 409


async def test_admin_set_household_owner(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(name="Flat 3B", members=[owner, other])
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}", json={"admin_id": other.id}
    )
    assert resp.status_code == 200
    assert resp.json()["admin_id"] == other.id

    # A non-member cannot be made owner.
    stranger = await make_user(email="stranger@example.com")
    bad = await client.patch(
        f"/api/v1/admin/households/{household.id}", json={"admin_id": stranger.id}
    )
    assert bad.status_code == 422


async def test_admin_remove_member_as_member_forbidden(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(name="Flat 3B", members=[member, other])
    client = await auth_client(member)

    resp = await client.delete(f"/api/v1/admin/households/{household.id}/members/{other.id}")
    assert resp.status_code == 403
