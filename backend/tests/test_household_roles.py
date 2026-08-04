"""Per-household roles: the ladder, who may set one, and what each role may reach.

Kept in one file on purpose, unlike the rest of the suite's router-per-file layout: the
question these answer is "what can a helper do?", and that spans chores, tags, history,
statistics and completion. Splitting it would leave the permission matrix reconstructable
only by reading five files.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.households import _ROLE_LADDER, roles_at_least
from app.core.security import generate_token
from app.models import (
    Chore,
    Household,
    HouseholdInvitation,
    HouseholdInvitationStatus,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
    Tag,
    User,
    UserStatus,
    household_members,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeTag = Callable[..., Awaitable[Tag]]
MakeOccurrence = Callable[..., Awaitable[object]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def _stored_role(session: AsyncSession, household_id: int, user_id: int) -> str | None:
    return await session.scalar(
        select(household_members.c.role).where(
            household_members.c.household_id == household_id,
            household_members.c.user_id == user_id,
        )
    )


# --- the ladder ---------------------------------------------------------


def test_roles_at_least_is_a_ladder() -> None:
    # The single source of the ordering. Everything else expands a minimum through this,
    # so if it is wrong every scoped query is wrong in the same direction.
    assert roles_at_least(HouseholdRole.organiser) == (HouseholdRole.organiser,)
    assert roles_at_least(HouseholdRole.deputy) == (HouseholdRole.deputy, HouseholdRole.organiser)
    assert roles_at_least(HouseholdRole.helper) == (
        HouseholdRole.helper,
        HouseholdRole.deputy,
        HouseholdRole.organiser,
    )


def test_every_role_is_on_the_ladder() -> None:
    # A role added to the enum and forgotten in _ROLE_LADDER makes roles_at_least raise
    # ValueError from .index() (a 500 if it ever reached a min_role) and satisfies no scoped
    # predicate at all, so a member holding it would silently see nothing. CLAUDE.md promises
    # a new role needs no query change; this is what makes that true.
    assert set(_ROLE_LADDER) == set(HouseholdRole)


def test_role_column_holds_every_role() -> None:
    # varchar(30), so a role longer than that would be a runtime error rather than a
    # validation one. Cheap to pin, and it is the reason a new role needs no migration.
    limit = household_members.c.role.type.length
    assert limit is not None
    assert all(len(role) <= limit for role in HouseholdRole)


# --- the role a new membership gets -------------------------------------


async def test_creator_of_a_household_is_an_organiser(
    make_user: MakeUser, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user()
    client = await auth_client(user)

    resp = await client.post("/api/v1/households", json={"name": "The Flat"})
    assert resp.status_code == 201
    # Nobody else could promote them, so the owner has to start out able to manage it.
    assert await _stored_role(db_session, resp.json()["id"], user.id) == HouseholdRole.organiser


async def test_accepting_an_invitation_joins_as_a_helper(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    joiner = await make_user(email="joiner@example.com")
    household = await make_household(members=[owner])
    token = generate_token()
    db_session.add(
        HouseholdInvitation(
            token=token,
            household_id=household.id,
            invited_by=owner.id,
            status=HouseholdInvitationStatus.pending,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()
    client = await auth_client(joiner)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 204
    # Least privilege: an invite link says nothing about who is on the other end.
    assert await _stored_role(db_session, household.id, joiner.id) == HouseholdRole.helper


async def test_transferring_ownership_promotes_the_new_owner(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    kid = await make_user(email="kid@example.com")
    household = await make_household(members=[owner, kid], roles={kid.id: HouseholdRole.helper})
    client = await auth_client(owner)

    resp = await client.patch(f"/api/v1/households/{household.id}", json={"admin_id": kid.id})
    assert resp.status_code == 200
    assert resp.json()["admin_id"] == kid.id
    # Without the promotion they would own a household they cannot manage the chores of,
    # and the role endpoint refuses to touch the owner's row, so nothing could fix it.
    assert await _stored_role(db_session, household.id, kid.id) == HouseholdRole.organiser
    # The previous owner stays an organiser, just no longer the owner.
    assert await _stored_role(db_session, household.id, owner.id) == HouseholdRole.organiser


async def test_admin_surface_transfer_also_promotes(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The two surfaces share set_household_admin, so the promotion has to hold on both.
    site_admin = await make_user(email="site@example.com", is_admin=True)
    owner = await make_user(email="owner@example.com")
    kid = await make_user(email="kid@example.com")
    household = await make_household(members=[owner, kid], roles={kid.id: HouseholdRole.helper})
    client = await auth_client(site_admin)

    resp = await client.patch(f"/api/v1/admin/households/{household.id}", json={"admin_id": kid.id})
    assert resp.status_code == 200
    assert await _stored_role(db_session, household.id, kid.id) == HouseholdRole.organiser


# --- reading roles ------------------------------------------------------


async def test_members_list_carries_each_role(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com", first_name="Dee")
    helper = await make_user(email="helper@example.com", first_name="Hal")
    household = await make_household(
        members=[owner, deputy, helper],
        roles={deputy.id: HouseholdRole.deputy, helper.id: HouseholdRole.helper},
    )
    client = await auth_client(helper)

    # Any member may read the roster, roles included: knowing who may do what is not
    # privileged information inside a household.
    resp = await client.get(f"/api/v1/households/{household.id}/members")
    assert resp.status_code == 200
    by_id = {m["id"]: m["role"] for m in resp.json()["items"]}
    assert by_id == {
        owner.id: HouseholdRole.organiser,
        deputy.id: HouseholdRole.deputy,
        helper.id: HouseholdRole.helper,
    }


async def test_me_reports_every_membership_with_its_role_and_ownership(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    user = await make_user()
    other = await make_user(email="other@example.com")
    organised = await make_household(name="Mine", members=[user])
    helped = await make_household(
        name="Theirs", members=[other, user], roles={user.id: HouseholdRole.helper}
    )
    # A soft-deleted household is not a live membership, so it must not appear: the
    # sidebar would otherwise light up for a household the user cannot reach.
    await make_household(name="Gone", members=[other, user], deleted_at=datetime.now(UTC))
    client = await auth_client(user)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    # `owned` is what gates the Logs page, and it is a different question from the role: the
    # second household here is somebody else's, so this pins that they are not conflated.
    assert resp.json()["memberships"] == [
        {"household_id": organised.id, "role": HouseholdRole.organiser, "owned": True},
        {"household_id": helped.id, "role": HouseholdRole.helper, "owned": False},
    ]


async def test_me_reports_an_organiser_who_does_not_own_as_not_owning(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # The case ownership exists separately for: an organiser is not an owner, so a household
    # they merely organise must come back `owned: false` and keep Logs out of their sidebar.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(
        members=[owner, organiser], roles={organiser.id: HouseholdRole.organiser}
    )
    client = await auth_client(organiser)

    resp = await client.get("/api/v1/auth/me")
    assert resp.json()["memberships"] == [
        {"household_id": household.id, "role": HouseholdRole.organiser, "owned": False}
    ]


async def test_login_response_carries_memberships(
    make_user: MakeUser, make_household: MakeHousehold, client: AsyncClient
) -> None:
    # Login sets the client's user directly rather than refetching /auth/me, so without
    # this the sidebar would render the minimal nav until the next page load - the state
    # most users would see first.
    user = await make_user(email="alice@example.com", password="password12345")
    household = await make_household(members=[user])

    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "password12345"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["memberships"] == [
        {"household_id": household.id, "role": HouseholdRole.organiser, "owned": True}
    ]


async def test_me_reports_no_memberships_for_a_member_of_none(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    # A normal, reachable state (nothing provisions a household), and the one the
    # frontend reads as "show the minimal sidebar".
    client = await auth_client(await make_user())

    resp = await client.get("/api/v1/auth/me")
    assert resp.json()["memberships"] == []


# --- setting a role -----------------------------------------------------


async def test_owner_sets_a_members_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(
        members=[owner, member], roles={member.id: HouseholdRole.helper}
    )
    client = await auth_client(owner)

    for role in (HouseholdRole.deputy, HouseholdRole.organiser, HouseholdRole.helper):
        resp = await client.patch(
            f"/api/v1/households/{household.id}/members/{member.id}", json={"role": role}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "id": member.id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "role": role,
        }
        assert await _stored_role(db_session, household.id, member.id) == role


async def test_owners_own_role_cannot_be_set(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(members=[owner, member])
    client = await auth_client(owner)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{owner.id}",
        json={"role": HouseholdRole.helper},
    )
    assert resp.status_code == 409
    assert "transfer ownership" in resp.json()["detail"].lower()
    # Refused, not silently ignored: nobody can demote themselves out of managing
    # their own household.
    assert await _stored_role(db_session, household.id, owner.id) == HouseholdRole.organiser


async def test_below_organiser_cannot_set_any_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, deputy, helper],
        roles={deputy.id: HouseholdRole.deputy, helper.id: HouseholdRole.helper},
    )

    for caller in (deputy, helper):
        client = await auth_client(caller)
        for role in (HouseholdRole.organiser, HouseholdRole.deputy):
            resp = await client.patch(
                f"/api/v1/households/{household.id}/members/{helper.id}",
                json={"role": role},
            )
            assert resp.status_code == 403, f"{caller.email} -> {role}"
            assert resp.json()["detail"] == "Only household organisers can do this"
    assert await _stored_role(db_session, household.id, helper.id) == HouseholdRole.helper


async def test_an_organiser_moves_people_between_deputy_and_helper(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The whole point of widening this: a house with several adults should not route every
    # membership change through one person.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(
        members=[owner, organiser, member], roles={member.id: HouseholdRole.helper}
    )
    client = await auth_client(organiser)

    for role in (HouseholdRole.deputy, HouseholdRole.helper):
        resp = await client.patch(
            f"/api/v1/households/{household.id}/members/{member.id}", json={"role": role}
        )
        assert resp.status_code == 200, role
        assert resp.json()["role"] == role
        assert await _stored_role(db_session, household.id, member.id) == role


async def test_an_organiser_cannot_hand_out_the_organiser_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The asymmetry that makes the widening safe: an organiser can share the load without
    # being able to grow the set of people who could demote them.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, organiser, helper], roles={helper.id: HouseholdRole.helper}
    )
    client = await auth_client(organiser)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{helper.id}",
        json={"role": HouseholdRole.organiser},
    )
    assert resp.status_code == 403
    assert (
        resp.json()["detail"] == "Only the household admin can grant or change the organiser role"
    )
    assert await _stored_role(db_session, household.id, helper.id) == HouseholdRole.helper


async def test_an_organiser_cannot_change_another_organiser(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    peer = await make_user(email="peer@example.com")
    # `peer` takes make_household's organiser default, which is the role under test here.
    household = await make_household(members=[owner, organiser, peer])
    client = await auth_client(organiser)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{peer.id}",
        json={"role": HouseholdRole.helper},
    )
    assert resp.status_code == 403
    assert await _stored_role(db_session, household.id, peer.id) == HouseholdRole.organiser


async def test_an_organiser_cannot_demote_themselves(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Falls out of the "cannot change an organiser" rule rather than needing its own check,
    # but it is the case a reader will come looking for, so pin it separately.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(members=[owner, organiser])
    client = await auth_client(organiser)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{organiser.id}",
        json={"role": HouseholdRole.helper},
    )
    assert resp.status_code == 403
    assert await _stored_role(db_session, household.id, organiser.id) == HouseholdRole.organiser


async def test_an_organiser_targeting_the_owner_gets_the_owner_rule(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    """409, not the organiser 403: the ordering of the two checks is deliberate.

    "The owner is always an organiser" is a property of the *target*, so everyone gets the
    same actionable answer - transfer ownership - rather than an organiser being told about a
    rule that is not the real reason they were refused.
    """
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(members=[owner, organiser])
    client = await auth_client(organiser)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{owner.id}",
        json={"role": HouseholdRole.helper},
    )
    assert resp.status_code == 409
    assert "transfer ownership" in resp.json()["detail"].lower()


async def test_an_organiser_manages_invitations(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    """Inviting moved from owner-only to organiser-level along with role-setting: both are
    managing people, which is the load a second adult should be able to share."""
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(members=[owner, organiser])
    client = await auth_client(organiser)

    created = await client.post(f"/api/v1/households/{household.id}/invitations")
    assert created.status_code == 201
    invitation_id = created.json()["id"]

    listed = await client.get(f"/api/v1/households/{household.id}/invitations")
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()] == [invitation_id]

    revoked = await client.post(
        f"/api/v1/households/{household.id}/invitations/{invitation_id}/revoke"
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    # Deleting is only allowed once revoked, which is why it comes last.
    deleted = await client.delete(f"/api/v1/households/{household.id}/invitations/{invitation_id}")
    assert deleted.status_code == 204


async def test_renaming_deleting_and_removing_stay_owner_only(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    """The line the widening did NOT cross. An organiser manages people; the household itself
    and who is in it at all remain the owner's."""
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    spare = await make_user(email="spare@example.com")
    household = await make_household(
        members=[owner, organiser, spare], roles={spare.id: HouseholdRole.helper}
    )
    client = await auth_client(organiser)

    for method, url, body in (
        ("patch", f"/api/v1/households/{household.id}", {"name": "Renamed"}),
        ("delete", f"/api/v1/households/{household.id}", None),
        # An ordinary member, not the owner: targeting the owner would collide with
        # remove_member's own 409 and pass without testing the endpoint's gate at all.
        ("delete", f"/api/v1/households/{household.id}/members/{spare.id}", None),
    ):
        resp = await getattr(client, method)(url, **({"json": body} if body else {}))
        assert resp.status_code == 403, f"{method} {url}"
        assert resp.json()["detail"] == "Only the household admin can do this"


async def test_setting_a_role_in_someone_elses_household_is_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    outsider = await make_user(email="outsider@example.com")
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(members=[owner, member])
    client = await auth_client(outsider)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{member.id}",
        json={"role": HouseholdRole.deputy},
    )
    # A household you are not in stays invisible, so 404 before the 403.
    assert resp.status_code == 404


async def test_setting_the_role_of_a_non_member_is_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    owner = await make_user(email="owner@example.com")
    stranger = await make_user(email="stranger@example.com")
    household = await make_household(members=[owner])
    client = await auth_client(owner)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{stranger.id}",
        json={"role": HouseholdRole.deputy},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Household member not found"


async def test_setting_the_role_of_a_disabled_member_is_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # A disabled user keeps their membership row but is hidden everywhere, the members
    # list included, so re-roling one would change a permission nothing displays.
    owner = await make_user(email="owner@example.com")
    gone = await make_user(email="gone@example.com", status=UserStatus.disabled)
    household = await make_household(members=[owner, gone])
    client = await auth_client(owner)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{gone.id}",
        json={"role": HouseholdRole.deputy},
    )
    assert resp.status_code == 404


async def test_unknown_role_is_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    household = await make_household(
        members=[owner, member], roles={member.id: HouseholdRole.helper}
    )
    client = await auth_client(owner)

    resp = await client.patch(
        f"/api/v1/households/{household.id}/members/{member.id}", json={"role": "supervisor"}
    )
    # The closed set is enforced at the schema layer (the column is a plain varchar), so
    # this is the only thing standing between a typo and a stored role every permission
    # check reads as "nothing granted".
    assert resp.status_code == 422
    assert await _stored_role(db_session, household.id, member.id) == HouseholdRole.helper


# --- what each role may reach -------------------------------------------


async def test_every_role_can_complete_a_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, deputy, helper],
        roles={deputy.id: HouseholdRole.deputy, helper.id: HouseholdRole.helper},
    )
    # One chore each, since completing closes the occurrence.
    for caller in (owner, deputy, helper):
        chore = await make_chore(household=household, title=f"Chore for {caller.email}")
        client = await auth_client(caller)
        resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
        assert resp.status_code == 201, caller.email


async def test_unscheduled_chores_are_completable_by_a_helper(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The ad-hoc chores are the ones a helper is most likely to be handed, and they go
    # through the same endpoint, so this pins the intent rather than a second code path.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    client = await auth_client(helper)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201


async def test_non_organisers_cannot_change_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, deputy, helper],
        roles={deputy.id: HouseholdRole.deputy, helper.id: HouseholdRole.helper},
    )
    chore = await make_chore(household=household)
    payload = {
        "household_id": household.id,
        "title": "Something new",
        "start_date": "2026-08-01",
        "repeats": "weekly",
        "assignment_type": "manual",
        "turn_length": 1,
        "repeat_interval": 1,
        "weekdays": None,
        "assignee_ids": [],
        "tag_ids": [],
    }
    for caller in (deputy, helper):
        client = await auth_client(caller)
        for method, url, body in (
            ("post", "/api/v1/chores", payload),
            ("patch", f"/api/v1/chores/{chore.id}", payload),
            ("delete", f"/api/v1/chores/{chore.id}", None),
        ):
            resp = await getattr(client, method)(url, **({"json": body} if body else {}))
            assert resp.status_code == 403, f"{caller.email} {method} {url}"
            assert resp.json()["detail"] == "Only household organisers can do this"


async def test_write_gates_are_per_household_not_anywhere(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    """An organiser of one household writing into another where they are not one.

    The tests either side of this one give the caller a single, non-organiser membership, so
    they would all still pass if `require_role` were a global "organises somewhere" check -
    the per-household clause of the gate is never exercised by them. This is the case where
    getting that wrong is a privilege escalation rather than merely extra data on a page, and
    it is reachable: `RequireRole` lets this caller into the management pages on the strength
    of their own household.
    """
    user = await make_user()
    other = await make_user(email="other@example.com")
    mine = await make_household(name="Mine", members=[user])
    theirs = await make_household(
        name="Theirs", members=[other, user], roles={user.id: HouseholdRole.helper}
    )
    their_chore = await make_chore(household=theirs, title="Not mine")
    their_tag = await make_tag(household=theirs, name="not-mine")
    client = await auth_client(user)

    # Sanity: they really are an organiser somewhere, so a global check would let all of the
    # below through. Without this the test could pass by having no privileges at all.
    assert (
        await client.post(
            "/api/v1/tags",
            json={"household_id": mine.id, "name": "ok-here", "color": "#0d9488"},
        )
    ).status_code == 201

    chore_payload = {
        "household_id": theirs.id,
        "title": "Something new",
        "start_date": "2026-08-01",
        "repeats": "weekly",
        "assignment_type": "manual",
        "turn_length": 1,
        "repeat_interval": 1,
        "weekdays": None,
        "assignee_ids": [],
        "tag_ids": [],
    }
    for method, url, body in (
        ("post", "/api/v1/chores", chore_payload),
        ("patch", f"/api/v1/chores/{their_chore.id}", chore_payload),
        ("delete", f"/api/v1/chores/{their_chore.id}", None),
        (
            "post",
            "/api/v1/tags",
            {"household_id": theirs.id, "name": "nope", "color": "#0d9488"},
        ),
        ("patch", f"/api/v1/tags/{their_tag.id}", {"name": "nope", "color": "#0d9488"}),
        ("delete", f"/api/v1/tags/{their_tag.id}", None),
    ):
        resp = await getattr(client, method)(url, **({"json": body} if body else {}))
        assert resp.status_code == 403, f"{method} {url}"
        assert resp.json()["detail"] == "Only household organisers can do this"


async def test_reading_one_chore_stays_open_to_every_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Load-bearing: the description dialog on Home and Unscheduled fetches the full chore,
    # and helpers are exactly the people who need to read the instructions.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, description="<p>Under the sink</p>")
    client = await auth_client(helper)

    resp = await client.get(f"/api/v1/chores/{chore.id}")
    assert resp.status_code == 200
    assert resp.json()["description"] == "<p>Under the sink</p>"


async def test_the_open_chore_read_carries_no_personal_data(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    """The counterweight to the test above: this read is open to every role, so it must not
    ship anything a helper should not have.

    It used to serialise each assignee as a full `UserRead` - email, is_admin, status,
    confirmed_at, created_at, the appearance preferences, two_factor_enabled and avatar_url -
    which handed a helper their housemates' email addresses over an endpoint they legitimately
    need for the description dialog. Asserting the exact key set rather than `"email" not in`,
    so re-widening the schema by any field fails here rather than only the one field somebody
    thought to check.
    """
    owner = await make_user(email="owner@example.com", first_name="Olive", last_name="Owner")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, assignees=[owner], current_assignee=owner)
    client = await auth_client(helper)

    body = (await client.get(f"/api/v1/chores/{chore.id}")).json()
    assert body["assignees"] == [{"id": owner.id, "first_name": "Olive", "last_name": "Owner"}]
    assert set(body["current_assignee"]) == {"id", "first_name", "last_name"}

    # The same shape on the management list and on a write response, since all three share the
    # schema. This half has to run as the OWNER: the list is narrowed to organised households,
    # so a helper's page is empty and a loop over it would assert nothing at all.
    client = await auth_client(owner)
    listed_resp = await client.get("/api/v1/chores")
    assert listed_resp.status_code == 200
    listed = listed_resp.json()
    assert listed["items"], "the owner organises this household, so the page must not be empty"
    for row in listed["items"]:
        for assignee in row["assignees"]:
            assert set(assignee) == {"id", "first_name", "last_name"}
    patched_resp = await client.patch(
        f"/api/v1/chores/{chore.id}",
        json={
            "title": chore.title,
            "start_date": "2026-08-01",
            "repeats": "weekly",
            "assignment_type": "manual",
            "turn_length": 1,
            "repeat_interval": 1,
            "weekdays": None,
            "assignee_ids": [owner.id],
            "tag_ids": [],
        },
    )
    assert patched_resp.status_code == 200
    assert set(patched_resp.json()["assignees"][0]) == {"id", "first_name", "last_name"}


async def test_chores_list_only_shows_organised_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    other = await make_user(email="other@example.com")
    mine = await make_household(name="Mine", members=[user])
    theirs = await make_household(
        name="Theirs", members=[other, user], roles={user.id: HouseholdRole.helper}
    )
    await make_chore(household=mine, title="Mine to manage")
    await make_chore(household=theirs, title="Not mine to manage")
    client = await auth_client(user)

    resp = await client.get("/api/v1/chores")
    assert resp.status_code == 200
    # Less data rather than a 403: the management list spans every household at once, and
    # the helper household's chores are still fully visible on Home.
    assert [c["title"] for c in resp.json()["items"]] == ["Mine to manage"]

    # Asking for the helper household by name yields an empty page, not an error.
    resp = await client.get(f"/api/v1/chores?household_id={theirs.id}")
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_home_still_shows_a_helpers_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The counterpart to the test above: gating management must not hide the work itself.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    await make_chore(household=household, title="Wash up")
    client = await auth_client(helper)

    resp = await client.get("/api/v1/home")
    assert resp.status_code == 200
    assert [c["title"] for c in resp.json()["items"]] == ["Wash up"]


async def test_unscheduled_still_shows_a_helpers_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The twin of test_home_still_shows_a_helpers_chores, and the reason chore_scope carries a
    # "do not add a min_role" comment: the ad-hoc chores are the ones a helper is most likely to
    # be handed. Without this, narrowing unscheduled.py alone would break nothing in the suite.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    await make_chore(household=household, title="Fix the leaky tap", repeats=RepeatPeriod.manual)
    client = await auth_client(helper)

    resp = await client.get("/api/v1/unscheduled")
    assert resp.status_code == 200
    assert [c["title"] for c in resp.json()["items"]] == ["Fix the leaky tap"]


async def test_tags_are_organiser_only(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    auth_client: AuthClient,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    household = await make_household(
        members=[owner, deputy], roles={deputy.id: HouseholdRole.deputy}
    )
    tag = await make_tag(household=household)
    client = await auth_client(deputy)

    # Reads are gated too, unlike chores: nothing outside the management pages shows a
    # tag, so a deputy has no legitimate read of one either. The expected status is spelled
    # out per route rather than "403 or 404": the two come from different guards (the
    # household resolution narrows, the tag helper checks the role), so accepting either
    # would let a route pass on the wrong one.
    for method, url, body, expected in (
        ("get", f"/api/v1/tags?household_id={household.id}", None, 404),
        ("get", f"/api/v1/tags/{tag.id}", None, 403),
        (
            "post",
            "/api/v1/tags",
            {"household_id": household.id, "name": "x", "color": "#0d9488"},
            403,
        ),
        ("patch", f"/api/v1/tags/{tag.id}", {"name": "x", "color": "#0d9488"}, 403),
        ("delete", f"/api/v1/tags/{tag.id}", None, 403),
    ):
        resp = await getattr(client, method)(url, **({"json": body} if body else {}))
        assert resp.status_code == expected, f"{method} {url}"
        if expected == 403:
            assert resp.json()["detail"] == "Only household organisers can do this"

    # And the no-household_id fallback must not quietly resolve to a household the
    # caller cannot manage.
    resp = await client.get("/api/v1/tags")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "You are not a household organiser anywhere"


async def test_history_narrows_for_a_helper_and_stats_still_needs_a_deputy(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, deputy, helper],
        roles={deputy.id: HouseholdRole.deputy, helper.id: HouseholdRole.helper},
    )
    for completer, title in ((helper, "Helper's own"), (owner, "Somebody else's")):
        chore = await make_chore(household=household, title=title, with_occurrence=False)
        await make_occurrence(
            chore=chore,
            scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
            status=OccurrenceStatus.done,
            completed_by=completer,
            completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        )
    client = await auth_client(helper)

    # History narrows rather than refusing: their own closure, and only that one. The
    # housemate's row is what makes this about the narrowing rather than about an empty
    # database, and `total` has to agree or the pager offers a page that comes back empty.
    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert [e["title"] for e in resp.json()["items"]] == ["Helper's own"]
    assert resp.json()["total"] == 1

    # Statistics is still closed to them, which is the rung History left.
    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    assert resp.json()["kpis"]["completed_in_range"] == 0

    # A deputy in the same household sees both rows and both numbers. `auth_client` hands
    # back the same client with the cookie swapped, hence the reassignment.
    client = await auth_client(deputy)
    assert len((await client.get("/api/v1/completions")).json()["items"]) == 2
    assert (await client.get("/api/v1/stats")).json()["kpis"]["completed_in_range"] == 2


async def test_a_helper_sees_their_own_skips_in_history_too(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The narrowing is on who the closure is recorded against, NOT on what kind it is: a
    # helper who skipped a chore has to be able to find that row, since a mis-skip moves the
    # schedule and undoing it is the whole point of them reaching History.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, title="Bins", with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        skipped=True,
    )
    client = await auth_client(helper)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert [(e["title"], e["skipped"]) for e in resp.json()["items"]] == [("Bins", True)]


async def test_a_helper_filtering_by_a_housemate_gets_an_empty_page(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Not a 403: the list spans every household at once, so it narrows rather than refusing,
    # and a helper asking for somebody else's rows simply has none.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=owner,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(helper)

    resp = await client.get(f"/api/v1/completions?user_id={owner.id}")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}

    # Their own id in the same household does return their own row, which is what makes the
    # assertion above about the narrowing rather than about the filter being broken.
    resp = await client.get(f"/api/v1/completions?user_id={helper.id}")
    assert resp.json()["total"] == 0
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 21, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    )
    resp = await client.get(f"/api/v1/completions?user_id={helper.id}")
    assert resp.json()["total"] == 1


async def test_history_drops_own_closures_from_a_household_you_left(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The membership clause inside the own-rows branch, tested head-on: a closure of the
    # caller's OWN in a household they are no longer in must not come back. Without that
    # clause the completed_by match alone would carry it, which is the one way the narrowing
    # could turn into a widening.
    user = await make_user()
    other = await make_user(email="other@example.com")
    household = await make_household(members=[other, user], roles={user.id: HouseholdRole.helper})
    chore = await make_chore(household=household, title="Left behind", with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(user)
    assert [e["title"] for e in (await client.get("/api/v1/completions")).json()["items"]] == [
        "Left behind"
    ]

    await db_session.execute(
        household_members.delete().where(
            household_members.c.household_id == household.id,
            household_members.c.user_id == user.id,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


async def test_history_is_empty_for_a_member_of_no_household(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    # Zero households is a normal, reachable state (it is where every new account starts),
    # and History is unconditional now - so this must be an empty page rather than an error.
    client = await auth_client(await make_user())

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


async def test_filter_options_stay_open_to_a_helper(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    # /completions/filters also feeds the Home and Unscheduled filter bars, so narrowing
    # it by role would empty the pickers there.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        name="The Flat", members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    client = await auth_client(helper)

    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 200
    assert [h["id"] for h in resp.json()["households"]] == [household.id]
    assert {m["id"] for m in resp.json()["members"]} == {owner.id, helper.id}


async def test_a_helper_undoes_their_own_closure(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Undoing your own closure needs no role at all. It used to 404 on the deputy scope,
    # which left a helper's mis-skip undoable by nobody: they could not reach History, and
    # everybody who could got the self-only 403.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(helper)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 204
    # The effect, not just the status: its only closure, so the row reopens rather than
    # being deleted, and the chore is available again.
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.open
    assert occ.completed_by_user_id is None


async def test_a_helper_cannot_undo_a_housemates_closure(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # 403 rather than 404 now: they are a member and they can see the row on History (they
    # cannot, in fact - the list hides other people's from them - but the resource is inside
    # their household, so a role complaint is the honest answer).
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=owner,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(helper)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 403


async def test_undo_is_still_self_only_for_a_deputy(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Seeing the whole household's history does not mean editing it: undoing somebody else's
    # closure is organiser-level, and a deputy is one rung below.
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    household = await make_household(
        members=[owner, deputy], roles={deputy.id: HouseholdRole.deputy}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=owner,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(deputy)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 403
    assert (
        resp.json()["detail"]
        == "You can only undo your own entries unless you are a household organiser"
    )


async def test_an_organiser_undoes_a_housemates_closure(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The organiser half of the rule, held by somebody who does NOT own the household: the
    # check reads their membership row, so ownership is not what grants this.
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, organiser, helper],
        roles={organiser.id: HouseholdRole.organiser, helper.id: HouseholdRole.helper},
    )
    assert household.admin_id == owner.id
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        assignee=helper,
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(organiser)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 204
    # Reopened with the ORIGINAL assignee, not handed to whoever pressed undo.
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.open
    assert occ.assignee_id == helper.id


async def test_the_owner_undoes_a_housemates_closure(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The owner passes on their membership row, which is always an organiser - the endpoint
    # never reads admin_id, which is the tempting wrong implementation.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(owner)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 204


async def test_an_organiser_of_one_household_cannot_undo_in_another(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The rule is per household, not "organiser anywhere". Organiser of A, helper in B, and
    # the closure is a housemate's in B.
    user = await make_user()
    other = await make_user(email="other@example.com")
    await make_household(name="A", members=[user])
    b = await make_household(name="B", members=[other, user], roles={user.id: HouseholdRole.helper})
    chore = await make_chore(household=b, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=other,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 403


async def test_an_organiser_undoes_a_housemates_skip(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The case the widening exists for: a mis-skip moves the chore's schedule rather than
    # just logging a row, and the person who made it may not be able to fix it.
    owner = await make_user(email="owner@example.com")
    helper = await make_user(email="helper@example.com")
    household = await make_household(
        members=[owner, helper], roles={helper.id: HouseholdRole.helper}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=helper,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        skipped=True,
    )
    client = await auth_client(owner)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 204
    # The flag has to be cleared with the rest, or completing the slot for real later would
    # still land in history as a skip.
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.open
    assert occ.skipped is False


async def test_undo_in_a_household_you_do_not_belong_to_is_a_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Membership is what makes the row exist for you at all, so a stranger's household is
    # still a 404 rather than the new 403. The caller is a site admin, which buys nothing
    # here: the user surface reads memberships, and Admin > Households is the other door.
    outsider = await make_user(is_admin=True)
    other = await make_user(email="other@example.com")
    household = await make_household(members=[other])
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=other,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(outsider)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 404


async def test_a_deputy_undoes_their_own_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    owner = await make_user(email="owner@example.com")
    deputy = await make_user(email="deputy@example.com")
    household = await make_household(
        members=[owner, deputy], roles={deputy.id: HouseholdRole.deputy}
    )
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_by=deputy,
        completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
    )
    client = await auth_client(deputy)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 204


async def test_mixed_roles_narrow_history_per_household_but_stats_by_role(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The cross-household case the "union for nav, scope the data" rule exists for:
    # organiser in one household, helper in another. History narrows per household -
    # everything from the first, own rows only from the second - while statistics still
    # counts the first household alone, since it needs a deputy outright.
    user = await make_user()
    other = await make_user(email="other@example.com")
    mine = await make_household(name="Mine", members=[user])
    theirs = await make_household(
        name="Theirs", members=[other, user], roles={user.id: HouseholdRole.helper}
    )
    for household, title, completer in (
        (mine, "Mine done", user),
        (theirs, "Theirs, mine", user),
        (theirs, "Theirs, not mine", other),
    ):
        chore = await make_chore(household=household, title=title, with_occurrence=False)
        await make_occurrence(
            chore=chore,
            scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
            status=OccurrenceStatus.done,
            completed_by=completer,
            completed_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        )
    client = await auth_client(user)

    # A set, not a list: all three share `completed_at`, so the order is decided by the
    # occurrence-id tiebreaker rather than by anything this test is about.
    resp = await client.get("/api/v1/completions")
    assert {e["title"] for e in resp.json()["items"]} == {"Mine done", "Theirs, mine"}
    assert resp.json()["total"] == 2
    assert (await client.get("/api/v1/stats")).json()["kpis"]["completed_in_range"] == 1
