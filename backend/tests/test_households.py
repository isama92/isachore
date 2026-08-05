from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.households import personal_household_name
from app.models import Chore, Household, User, UserStatus, household_members

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


# --- naming helper ------------------------------------------------------


def test_personal_household_name_fits_the_column() -> None:
    # Only `seed` names a household this way now, and its first names are short, so
    # nothing exercises the clipping in practice. Pin it anyway: households.name is
    # varchar(255) and Postgres rejects an over-long INSERT outright rather than
    # truncating, so an unclipped 255-character first name would turn seeding into
    # an error instead of a slightly shortened name.
    name = personal_household_name("N" * 255)
    assert len(name) <= 255
    assert name.endswith("'s place")
    # A normal name is untouched.
    assert personal_household_name("Alex") == "Alex's place"


# --- list ---------------------------------------------------------------


async def test_list_households_enveloped(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["items"][0]["name"] == "Flat 3B"


async def test_list_households_only_mine(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Mine", members=[alice])
    await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    assert [h["name"] for h in resp.json()["items"]] == ["Mine"]


async def test_list_households_excludes_soft_deleted(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Active", members=[alice])
    await make_household(name="Gone", members=[alice], deleted_at=datetime.now(UTC))
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    assert [h["name"] for h in resp.json()["items"]] == ["Active"]


async def test_list_households_counts_members_and_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    alice = await make_user(email="alice@example.com", first_name="Alice")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    ghost = await make_user(email="ghost@example.com", status=UserStatus.disabled)
    household = await make_household(name="Flat 3B", members=[alice, bob, ghost])
    await make_chore(household=household, title="Dishes")
    await make_chore(household=household, title="Bins")
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households")
    row = resp.json()["items"][0]
    # ghost is disabled, so member_count is the two active members only
    assert row["member_count"] == 2
    assert row["chore_count"] == 2
    assert row["deleted_at"] is None


async def test_list_households_chore_count_excludes_soft_deleted(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await make_chore(household=household, title="Dishes")
    doomed = await make_chore(household=household, title="Bins")
    client = await auth_client(alice)

    await client.delete(f"/api/v1/chores/{doomed.id}")

    resp = await client.get("/api/v1/households")
    assert resp.json()["items"][0]["chore_count"] == 1


async def test_list_households_pagination(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    for i in range(5):
        await make_household(name=f"House {i}", members=[alice])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households?page=1&page_size=2&sort_by=id&sort_dir=asc")
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    first_ids = [h["id"] for h in body["items"]]

    resp = await client.get("/api/v1/households?page=2&page_size=2&sort_by=id&sort_dir=asc")
    second_ids = [h["id"] for h in resp.json()["items"]]
    assert set(first_ids).isdisjoint(second_ids)
    assert max(first_ids) < min(second_ids)

    resp = await client.get("/api/v1/households?page=3&page_size=2&sort_by=id&sort_dir=asc")
    assert len(resp.json()["items"]) == 1  # remainder


async def test_list_households_sort_by_name(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Beta", members=[alice])
    await make_household(name="Alpha", members=[alice])
    await make_household(name="Gamma", members=[alice])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households?sort_by=name&sort_dir=asc")
    assert [h["name"] for h in resp.json()["items"]] == ["Alpha", "Beta", "Gamma"]


async def test_list_households_filter_by_name(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="Beach House", members=[alice])
    await make_household(name="City Flat", members=[alice])
    client = await auth_client(alice)

    resp = await client.get("/api/v1/households?name=beach")
    assert [h["name"] for h in resp.json()["items"]] == ["Beach House"]


async def test_list_households_name_filter_escapes_wildcards(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    await make_household(name="a%b", members=[alice])
    await make_household(name="axxb", members=[alice])
    client = await auth_client(alice)

    # A literal % must not act as a wildcard, so only the exact "a%b" matches.
    resp = await client.get("/api/v1/households?name=a%25b")
    assert [h["name"] for h in resp.json()["items"]] == ["a%b"]


async def test_list_households_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/households")
    assert resp.status_code == 401


async def test_list_households_invalid_params_rejected(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    client = await auth_client(alice)
    for query in ("sort_by=bogus", "sort_dir=sideways", "page_size=101", "page=0"):
        resp = await client.get(f"/api/v1/households?{query}")
        assert resp.status_code == 422, query


# --- create -------------------------------------------------------------


async def test_create_household_adds_creator_as_member(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    client = await auth_client(alice)

    resp = await client.post("/api/v1/households", json={"name": "New Place", "timezone": "UTC"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Place"
    assert body["member_count"] == 1
    assert body["chore_count"] == 0
    # The creator becomes the household owner.
    assert body["admin_id"] == alice.id

    # It shows up in the creator's own list.
    listing = await client.get("/api/v1/households")
    assert [h["name"] for h in listing.json()["items"]] == ["New Place"]


async def test_create_household_blank_name_rejected(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    client = await auth_client(alice)
    resp = await client.post("/api/v1/households", json={"name": "", "timezone": "UTC"})
    assert resp.status_code == 422


async def test_create_household_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/households", json={"name": "Nope", "timezone": "UTC"})
    assert resp.status_code == 401


# --- detail -------------------------------------------------------------


async def test_get_household(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{household.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Flat 3B"


async def test_get_household_not_mine_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{theirs.id}")
    assert resp.status_code == 404


async def test_get_household_soft_deleted_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    gone = await make_household(name="Gone", members=[alice], deleted_at=datetime.now(UTC))
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{gone.id}")
    assert resp.status_code == 404


# --- update -------------------------------------------------------------


async def test_update_household_renames(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Old", members=[alice])
    client = await auth_client(alice)

    resp = await client.patch(f"/api/v1/households/{household.id}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


async def test_update_household_not_mine_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.patch(f"/api/v1/households/{theirs.id}", json={"name": "Mine now"})
    assert resp.status_code == 404


# --- soft delete --------------------------------------------------------


async def test_delete_household_soft(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await make_chore(household=household, title="Dishes")
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{household.id}")
    assert resp.status_code == 204

    # Row survives with deleted_at set and drops out of the list.
    refreshed = await db_session.get(Household, household.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.deleted_at is not None

    listing = await client.get("/api/v1/households")
    assert listing.json()["items"] == []

    # Chores are left untouched by the soft delete.
    chore_count = await db_session.scalar(
        select(func.count()).select_from(Chore).where(Chore.household_id == household.id)
    )
    assert chore_count == 1


async def test_delete_household_not_mine_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{theirs.id}")
    assert resp.status_code == 404


# --- members ------------------------------------------------------------


async def test_list_members_active_only(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com", first_name="Alice")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    ghost = await make_user(
        email="ghost@example.com", first_name="Ghost", status=UserStatus.disabled
    )
    household = await make_household(name="Flat 3B", members=[alice, bob, ghost])
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{household.id}/members?sort_by=name&sort_dir=asc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [m["first_name"] for m in body["items"]] == ["Alice", "Bob"]
    # data minimisation: no email in the member payload
    assert "email" not in body["items"][0]


async def test_list_members_invalid_params_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)
    for query in ("sort_by=email", "sort_dir=sideways", "page_size=101", "page=0"):
        resp = await client.get(f"/api/v1/households/{household.id}/members?{query}")
        assert resp.status_code == 422, query


async def test_list_members_not_mine_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{theirs.id}/members")
    assert resp.status_code == 404


async def test_remove_member(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{household.id}/members/{bob.id}")
    assert resp.status_code == 204

    remaining = await db_session.scalar(
        select(func.count())
        .select_from(household_members)
        .where(household_members.c.household_id == household.id)
    )
    assert remaining == 1


async def test_remove_member_not_a_member_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    stranger = await make_user(email="stranger@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{household.id}/members/{stranger.id}")
    assert resp.status_code == 404


async def test_remove_member_household_not_mine_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    theirs = await make_household(name="Theirs", members=[bob])
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{theirs.id}/members/{bob.id}")
    assert resp.status_code == 404


# --- ownership ----------------------------------------------------------


async def test_non_owner_member_cannot_edit_or_manage(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # alice (members[0]) is the owner; bob is a plain member.
    household = await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(bob)

    rename = await client.patch(f"/api/v1/households/{household.id}", json={"name": "Bob's"})
    assert rename.status_code == 403
    assert rename.json()["detail"] == "Only the household admin can do this"

    delete = await client.delete(f"/api/v1/households/{household.id}")
    assert delete.status_code == 403

    remove = await client.delete(f"/api/v1/households/{household.id}/members/{alice.id}")
    assert remove.status_code == 403


async def test_owner_can_edit_and_remove(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(alice)

    assert (
        await client.patch(f"/api/v1/households/{household.id}", json={"name": "Renamed"})
    ).status_code == 200
    assert (
        await client.delete(f"/api/v1/households/{household.id}/members/{bob.id}")
    ).status_code == 204


async def test_owner_cannot_be_removed(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{household.id}/members/{alice.id}")
    assert resp.status_code == 409


async def test_owner_transfers_ownership(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(alice)

    resp = await client.patch(f"/api/v1/households/{household.id}", json={"admin_id": bob.id})
    assert resp.status_code == 200
    assert resp.json()["admin_id"] == bob.id

    # alice is no longer the owner; bob now is.
    assert (
        await client.patch(f"/api/v1/households/{household.id}", json={"name": "nope"})
    ).status_code == 403
    bob_client = await auth_client(bob)
    assert (
        await bob_client.patch(f"/api/v1/households/{household.id}", json={"name": "yes"})
    ).status_code == 200


async def test_transfer_to_non_member_rejected(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    stranger = await make_user(email="stranger@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.patch(f"/api/v1/households/{household.id}", json={"admin_id": stranger.id})
    assert resp.status_code == 422


# --- leaving -----------------------------------------------------------


async def test_non_owner_can_leave(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # alice (members[0]) owns; bob is a plain member and may leave.
    household = await make_household(name="Flat 3B", members=[alice, bob])
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/households/{household.id}/leave")
    assert resp.status_code == 204

    remaining = await db_session.scalar(
        select(func.count())
        .select_from(household_members)
        .where(household_members.c.household_id == household.id)
    )
    assert remaining == 1  # only alice remains


async def test_owner_cannot_leave(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{household.id}/leave")
    assert resp.status_code == 409


async def test_leave_household_not_a_member_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{theirs.id}/leave")
    assert resp.status_code == 404


async def test_leave_soft_deleted_household_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    gone = await make_household(name="Gone", members=[alice], deleted_at=datetime.now(UTC))
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{gone.id}/leave")
    assert resp.status_code == 404


async def test_leave_household_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/households/1/leave")
    assert resp.status_code == 401
