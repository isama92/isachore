from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Household, HouseholdRole, User, UserStatus, household_members

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

    resp = await client.post("/api/v1/admin/households", json={"name": "HQ", "timezone": "UTC"})
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
    resp = await client.post("/api/v1/admin/households", json={"name": "Nope", "timezone": "UTC"})
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


# --- admin: member roles ------------------------------------------------


async def test_admin_sets_any_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """A site admin is unrestricted here, unlike an organiser on the user surface.

    That asymmetry exists so an organiser cannot grow the set of people who could demote them,
    which is a rule about a household member; an operator who can already transfer the household
    and remove members has no such relationship to protect.
    """
    site_admin = await make_user(email="site@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(
        name="HQ", members=[owner, member], roles={member.id: HouseholdRole.helper}
    )
    client = await auth_client(site_admin)

    for role in (HouseholdRole.organiser, HouseholdRole.deputy, HouseholdRole.helper):
        resp = await client.patch(
            f"/api/v1/admin/households/{household.id}/members/{member.id}", json={"role": role}
        )
        assert resp.status_code == 200, role
        assert resp.json() == {
            "id": member.id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "role": role,
        }
        stored = await db_session.scalar(
            select(household_members.c.role).where(
                household_members.c.household_id == household.id,
                household_members.c.user_id == member.id,
            )
        )
        assert stored == role


async def test_admin_cannot_set_the_owners_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Same 409 as the user surface, from the shared `refuse_owner_row`: the owner's role is
    # derived from owning the household, and a site admin has the transfer path this names.
    site_admin = await make_user(email="site@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    household = await make_household(name="HQ", members=[owner])
    client = await auth_client(site_admin)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}/members/{owner.id}",
        json={"role": HouseholdRole.helper},
    )
    assert resp.status_code == 409
    assert "transfer ownership" in resp.json()["detail"].lower()
    stored = await db_session.scalar(
        select(household_members.c.role).where(
            household_members.c.household_id == household.id,
            household_members.c.user_id == owner.id,
        )
    )
    assert stored == HouseholdRole.organiser


async def test_admin_set_role_non_member_and_disabled_are_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    site_admin = await make_user(email="site@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    stranger = await make_user(email="stranger@example.com")
    gone = await make_user(email="gone@example.com", status=UserStatus.disabled)
    household = await make_household(name="HQ", members=[owner, gone])
    client = await auth_client(site_admin)

    for target in (stranger, gone):
        resp = await client.patch(
            f"/api/v1/admin/households/{household.id}/members/{target.id}",
            json={"role": HouseholdRole.deputy},
        )
        assert resp.status_code == 404, target.email
        assert resp.json()["detail"] == "Household member not found"


async def test_admin_sets_a_role_on_a_deleted_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # Reaches soft-deleted households like the other routes here, which resolve through
    # `_get_household_or_404`: a wrong role is worth fixing before restoring one.
    site_admin = await make_user(email="site@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(
        name="HQ",
        members=[owner, member],
        roles={member.id: HouseholdRole.helper},
        deleted_at=datetime.now(UTC),
    )
    client = await auth_client(site_admin)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}/members/{member.id}",
        json={"role": HouseholdRole.deputy},
    )
    assert resp.status_code == 200


async def test_admin_set_role_as_member_forbidden(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # AdminUser is the only gate on this router, so an ordinary member gets 403 even though the
    # user surface would let this exact caller (an organiser by make_household's default) set a
    # helper's role on its own endpoint.
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(
        name="Flat 3B", members=[member, other], roles={other.id: HouseholdRole.helper}
    )
    client = await auth_client(member)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}/members/{other.id}",
        json={"role": HouseholdRole.deputy},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin only"
