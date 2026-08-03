from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token
from app.models import (
    Household,
    HouseholdInvitation,
    HouseholdInvitationStatus,
    HouseholdRole,
    User,
    household_members,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def _make_invitation(
    session: AsyncSession,
    household: Household,
    inviter: User,
    ttl: timedelta = timedelta(hours=24),
    status: HouseholdInvitationStatus = HouseholdInvitationStatus.pending,
) -> str:
    raw = generate_token()
    session.add(
        HouseholdInvitation(
            token=raw,
            household_id=household.id,
            invited_by=inviter.id,
            status=status,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.commit()
    return raw


async def _invitation_status(session: AsyncSession, token: str) -> str | None:
    return await session.scalar(
        select(HouseholdInvitation.status).where(HouseholdInvitation.token == token)
    )


async def _invitation_id(session: AsyncSession, token: str) -> int | None:
    return await session.scalar(
        select(HouseholdInvitation.id).where(HouseholdInvitation.token == token)
    )


async def _member_count(session: AsyncSession, household_id: int, user_id: int) -> int:
    query = (
        select(func.count())
        .select_from(household_members)
        .where(
            household_members.c.household_id == household_id,
            household_members.c.user_id == user_id,
        )
    )
    return await session.scalar(query) or 0


# --- owner: create / list / delete --------------------------------------


async def test_owner_creates_invitation(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 201
    body = resp.json()
    assert "/invite?token=" in body["url"]
    assert body["status"] == "pending"
    # `expired` is no longer a separate field; it's a value of `status`.
    assert "expired" not in body
    # expires_at is rounded up to a whole hour so the hourly sweep lands on it.
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert (expires_at.minute, expires_at.second, expires_at.microsecond) == (0, 0, 0)


async def test_cap_message_names_the_household_not_the_caller(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The 409 detail is rendered verbatim by `HouseholdInvitations`, and inviting is no longer
    one person's job: the 5 pending invites are as likely to be somebody else's, so "you already
    have" would point an organiser at invitations they never made."""
    owner = await make_user(email="owner@example.com")
    organiser = await make_user(email="organiser@example.com")
    household = await make_household(name="Flat 3B", members=[owner, organiser])
    # All five minted by the OWNER, so the caller below genuinely has none of their own.
    for _ in range(5):
        await _make_invitation(db_session, household, owner)
    client = await auth_client(organiser)

    resp = await client.post(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "This household already has 5 pending invitations; revoke one first."
    )


async def test_below_organiser_cannot_create_invitation(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # Bob is a helper: inviting is open to the owner and to organisers, and
    # make_household defaults members to organiser, so the role has to be said out loud
    # or this would pass for the wrong reason.
    household = await make_household(
        name="Flat 3B", members=[alice, bob], roles={bob.id: HouseholdRole.helper}
    )
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 403


async def test_create_invitation_not_member_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    theirs = await make_household(name="Theirs")
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{theirs.id}/invitations")
    assert resp.status_code == 404


async def test_list_invitations_includes_expired(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await _make_invitation(db_session, household, alice)
    await _make_invitation(db_session, household, alice, status=HouseholdInvitationStatus.expired)
    client = await auth_client(alice)

    resp = await client.get(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {item["status"] for item in body} == {"pending", "expired"}


async def test_delete_live_pending_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await _make_invitation(db_session, household, alice)
    client = await auth_client(alice)

    invitation_id = (await client.get(f"/api/v1/households/{household.id}/invitations")).json()[0][
        "id"
    ]
    # A live pending invite must be revoked, not deleted.
    resp = await client.delete(f"/api/v1/households/{household.id}/invitations/{invitation_id}")
    assert resp.status_code == 409


async def test_delete_terminal_or_expired_invitation(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    # A revoked, an accepted, and an expired invite are all deletable.
    await _make_invitation(db_session, household, alice, status=HouseholdInvitationStatus.revoked)
    await _make_invitation(db_session, household, alice, status=HouseholdInvitationStatus.accepted)
    await _make_invitation(db_session, household, alice, status=HouseholdInvitationStatus.expired)
    client = await auth_client(alice)

    path = f"/api/v1/households/{household.id}/invitations"
    ids = [item["id"] for item in (await client.get(path)).json()]
    for invitation_id in ids:
        resp = await client.delete(f"{path}/{invitation_id}")
        assert resp.status_code == 204
    assert (await client.get(path)).json() == []


async def test_delete_invitation_missing_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.delete(f"/api/v1/households/{household.id}/invitations/999999")
    assert resp.status_code == 404


async def test_list_invitations_below_organiser_forbidden(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # Bob is a helper: inviting is open to the owner and to organisers, and
    # make_household defaults members to organiser, so the role has to be said out loud
    # or this would pass for the wrong reason.
    household = await make_household(
        name="Flat 3B", members=[alice, bob], roles={bob.id: HouseholdRole.helper}
    )
    client = await auth_client(bob)

    resp = await client.get(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 403


# --- revoke (owner and organisers) --------------------------------------


async def test_revoke_pending_invitation(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    inv = (await client.post(f"/api/v1/households/{household.id}/invitations")).json()
    resp = await client.post(f"/api/v1/households/{household.id}/invitations/{inv['id']}/revoke")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


async def test_revoke_non_pending_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    # Revoked, accepted, and expired are all non-revocable.
    cases = [
        {"status": HouseholdInvitationStatus.revoked},
        {"status": HouseholdInvitationStatus.accepted},
        {"status": HouseholdInvitationStatus.expired},
    ]
    for kwargs in cases:
        token = await _make_invitation(db_session, household, alice, **kwargs)
        iid = await _invitation_id(db_session, token)
        resp = await client.post(f"/api/v1/households/{household.id}/invitations/{iid}/revoke")
        assert resp.status_code == 409, kwargs


async def test_revoke_below_organiser_forbidden(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # Bob is a helper: inviting is open to the owner and to organisers, and
    # make_household defaults members to organiser, so the role has to be said out loud
    # or this would pass for the wrong reason.
    household = await make_household(
        name="Flat 3B", members=[alice, bob], roles={bob.id: HouseholdRole.helper}
    )
    token = await _make_invitation(db_session, household, alice)
    iid = await _invitation_id(db_session, token)
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/households/{household.id}/invitations/{iid}/revoke")
    assert resp.status_code == 403


async def test_revoke_missing_404(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/households/{household.id}/invitations/999999/revoke")
    assert resp.status_code == 404


# --- owner: pending limit ----------------------------------------------


async def test_pending_limit_blocks_creation(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    client = await auth_client(alice)
    path = f"/api/v1/households/{household.id}/invitations"

    for _ in range(5):
        assert (await client.post(path)).status_code == 201
    assert (await client.post(path)).status_code == 409

    # Revoking one frees a slot.
    inv_id = (await client.get(path)).json()[0]["id"]
    assert (await client.post(f"{path}/{inv_id}/revoke")).status_code == 200
    assert (await client.post(path)).status_code == 201


async def test_pending_limit_ignores_terminal_and_expired(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    # Seed many non-counting invites: accepted, revoked, and expired.
    accepted = HouseholdInvitationStatus.accepted
    revoked = HouseholdInvitationStatus.revoked
    expired = HouseholdInvitationStatus.expired
    for _ in range(5):
        await _make_invitation(db_session, household, alice, status=accepted)
        await _make_invitation(db_session, household, alice, status=revoked)
        await _make_invitation(db_session, household, alice, status=expired)
    client = await auth_client(alice)

    # None of those count, so creating a fresh live invite still works.
    resp = await client.post(f"/api/v1/households/{household.id}/invitations")
    assert resp.status_code == 201


# --- public: info -------------------------------------------------------


async def test_invitation_info(
    make_user: MakeUser,
    make_household: MakeHousehold,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com", first_name="Alice", last_name="Adams")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(db_session, household, alice)

    resp = await client.get(f"/api/v1/invitations/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["household_name"] == "Flat 3B"
    assert body["invited_by"]["first_name"] == "Alice"
    assert body["invited_by"]["last_name"] == "Adams"
    # data minimisation: no email leaked
    assert "email" not in body["invited_by"]


async def test_invitation_info_unknown_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/invitations/nope")
    assert resp.status_code == 404


async def test_invitation_info_expired_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(
        db_session, household, alice, status=HouseholdInvitationStatus.expired
    )

    resp = await client.get(f"/api/v1/invitations/{token}")
    assert resp.status_code == 404


async def test_invitation_info_deleted_household_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Gone", members=[alice], deleted_at=datetime.now(UTC))
    token = await _make_invitation(db_session, household, alice)

    resp = await client.get(f"/api/v1/invitations/{token}")
    assert resp.status_code == 404


async def test_revoked_token_not_usable(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(
        db_session, household, alice, status=HouseholdInvitationStatus.revoked
    )

    # A revoked token exposes no info and can't be accepted.
    assert (await client.get(f"/api/v1/invitations/{token}")).status_code == 404
    bob_client = await auth_client(bob)
    assert (await bob_client.post(f"/api/v1/invitations/{token}/accept")).status_code == 404


# --- accept -------------------------------------------------------------


async def test_accept_invitation_joins_and_is_single_use(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(db_session, household, alice)
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 204
    assert await _member_count(db_session, household.id, bob.id) == 1
    # The invite is kept as a record, flipped to accepted.
    assert await _invitation_status(db_session, token) == HouseholdInvitationStatus.accepted

    # Single-use: an accepted token can't be redeemed again.
    again = await client.post(f"/api/v1/invitations/{token}/accept")
    assert again.status_code == 404


async def test_accept_invitation_already_member_409(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(db_session, household, alice)
    client = await auth_client(alice)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 409


async def test_accept_invitation_requires_auth(
    make_user: MakeUser,
    make_household: MakeHousehold,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(db_session, household, alice)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 401


async def test_accept_invitation_expired_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    token = await _make_invitation(
        db_session, household, alice, status=HouseholdInvitationStatus.expired
    )
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 404
    assert await _member_count(db_session, household.id, bob.id) == 0


async def test_accept_invitation_deleted_household_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    household = await make_household(name="Gone", members=[alice], deleted_at=datetime.now(UTC))
    token = await _make_invitation(db_session, household, alice)
    client = await auth_client(bob)

    resp = await client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 404
    assert await _member_count(db_session, household.id, bob.id) == 0


async def test_delete_invitation_foreign_household_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    mine = await make_household(name="Mine", members=[alice])
    theirs = await make_household(name="Theirs", members=[bob])
    await _make_invitation(db_session, theirs, bob)
    foreign_id = await db_session.scalar(
        select(HouseholdInvitation.id).where(HouseholdInvitation.household_id == theirs.id)
    )
    client = await auth_client(alice)

    # alice owns `mine`, not `theirs`; deleting theirs' invite via her path 404s
    # and leaves it intact.
    resp = await client.delete(f"/api/v1/households/{mine.id}/invitations/{foreign_id}")
    assert resp.status_code == 404
    survived = await db_session.scalar(
        select(func.count())
        .select_from(HouseholdInvitation)
        .where(HouseholdInvitation.id == foreign_id)
    )
    assert survived == 1


async def test_delete_invitation_below_organiser_forbidden(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    # Bob is a helper: inviting is open to the owner and to organisers, and
    # make_household defaults members to organiser, so the role has to be said out loud
    # or this would pass for the wrong reason.
    household = await make_household(
        name="Flat 3B", members=[alice, bob], roles={bob.id: HouseholdRole.helper}
    )
    await _make_invitation(db_session, household, alice)
    invitation_id = await db_session.scalar(select(HouseholdInvitation.id))
    client = await auth_client(bob)

    resp = await client.delete(f"/api/v1/households/{household.id}/invitations/{invitation_id}")
    assert resp.status_code == 403
