"""The invitation-expiry sweep, the expiry-time rounding, and the scheduler
wiring that runs the sweep hourly."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.invitations import (
    mark_expired_invitations,
    round_up_to_hour,
    run_expire_invitations,
)
from app.core.scheduler import create_scheduler
from app.core.security import generate_token
from app.models import Household, HouseholdInvitation, HouseholdInvitationStatus, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]


async def _add_invitation(
    session: AsyncSession,
    household: Household,
    inviter: User,
    *,
    status: HouseholdInvitationStatus = HouseholdInvitationStatus.pending,
    ttl: timedelta = timedelta(hours=24),
) -> str:
    token = generate_token()
    session.add(
        HouseholdInvitation(
            token=token,
            household_id=household.id,
            invited_by=inviter.id,
            status=status,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.commit()
    return token


async def _status(session: AsyncSession, token: str) -> str | None:
    return await session.scalar(
        select(HouseholdInvitation.status).where(HouseholdInvitation.token == token)
    )


# --- round_up_to_hour ---------------------------------------------------


def test_round_up_to_hour_rounds_partial_hour_up() -> None:
    got = round_up_to_hour(datetime(2026, 7, 19, 13, 15, 27, tzinfo=UTC))
    assert got == datetime(2026, 7, 19, 14, 0, 0, tzinfo=UTC)


def test_round_up_to_hour_leaves_exact_hour_untouched() -> None:
    exact = datetime(2026, 7, 19, 14, 0, 0, tzinfo=UTC)
    assert round_up_to_hour(exact) == exact


def test_round_up_to_hour_rounds_up_on_stray_microsecond() -> None:
    got = round_up_to_hour(datetime(2026, 7, 19, 14, 0, 0, 1, tzinfo=UTC))
    assert got == datetime(2026, 7, 19, 15, 0, 0, tzinfo=UTC)


# --- mark_expired_invitations -------------------------------------------


async def test_sweep_flips_only_stale_pending(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    stale = await _add_invitation(db_session, household, alice, ttl=timedelta(hours=-1))
    live = await _add_invitation(db_session, household, alice, ttl=timedelta(hours=24))
    accepted = await _add_invitation(
        db_session,
        household,
        alice,
        status=HouseholdInvitationStatus.accepted,
        ttl=timedelta(hours=-1),
    )
    revoked = await _add_invitation(
        db_session,
        household,
        alice,
        status=HouseholdInvitationStatus.revoked,
        ttl=timedelta(hours=-1),
    )

    count = await mark_expired_invitations(db_session)

    assert count == 1
    assert await _status(db_session, stale) == HouseholdInvitationStatus.expired
    assert await _status(db_session, live) == HouseholdInvitationStatus.pending
    assert await _status(db_session, accepted) == HouseholdInvitationStatus.accepted
    assert await _status(db_session, revoked) == HouseholdInvitationStatus.revoked


async def test_sweep_is_idempotent(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await _add_invitation(db_session, household, alice, ttl=timedelta(hours=-1))

    assert await mark_expired_invitations(db_session) == 1
    # Nothing pending-and-stale remains, so a second pass is a no-op.
    assert await mark_expired_invitations(db_session) == 0


async def test_sweep_no_stale_returns_zero(
    make_user: MakeUser, make_household: MakeHousehold, db_session: AsyncSession
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(name="Flat 3B", members=[alice])
    await _add_invitation(db_session, household, alice, ttl=timedelta(hours=24))

    assert await mark_expired_invitations(db_session) == 0


# --- scheduler wiring ---------------------------------------------------


def test_scheduler_registers_hourly_expire_job() -> None:
    scheduler = create_scheduler()
    job = scheduler.get_job("expire-invitations")
    assert job is not None
    assert job.func is run_expire_invitations
    # Fires at the top of every hour (minute 0, second 0).
    assert str(job.trigger) == "cron[minute='0', second='0']"
