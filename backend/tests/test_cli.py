"""Tests for the management CLI (`app.cli`).

The repo convention is to call the async worker functions directly with the
`fake_redis` / `db_session` / `make_user` fixtures rather than shelling out, and
to assert against Redis the way `test_rate_limit.py` does.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import distinct, func, select

from app.cli import _guard_dev_environment, clear_throttle, init_admin
from app.core.crypto import encrypt
from app.core.rate_limit import clear_login_throttle
from app.core.security import generate_token, hash_token, verify_password
from app.db.seed import SEED_PASSWORD, SEED_TIMEZONE, seed
from app.models import (
    AuditAction,
    AuditEvent,
    AuthToken,
    Chore,
    ChoreOccurrence,
    ConfirmationToken,
    Household,
    OccurrenceStatus,
    TwoFactorRecoveryCode,
    User,
    UserStatus,
    household_members,
)

_INIT_PASSWORD = "init-password12345"


def _email_key(email: str) -> str:
    return f"login:fail:email:{email}"


def _ip_key(ip: str) -> str:
    return f"login:fail:ip:{ip}"


# --- init_admin (bootstrap and lockout recovery, I2) ----------------------


async def test_init_creates_the_first_admin_on_an_empty_db(db_session) -> None:
    await init_admin(db_session, "Owner@Example.com", "Owner", "User", _INIT_PASSWORD)

    user = await db_session.scalar(select(User).where(User.email == "owner@example.com"))
    # The email is lowercased, since the CLI bypasses the Pydantic normalisation.
    assert user is not None
    assert user.is_admin is True
    assert user.status == UserStatus.active
    assert user.confirmed_at is not None
    assert verify_password(_INIT_PASSWORD, user.password_hash)


async def test_init_creates_no_household(
    db_session, make_household: Callable[..., Awaitable[Household]]
) -> None:
    # The bootstrap admin provisions nothing either, so a fresh install starts with
    # an empty Households page and the admin creates their own. In particular a
    # pre-existing household belonging to someone else must NOT be joined: an
    # earlier version picked the lowest-id household, which once households became
    # user-owned meant dropping the new admin into a stranger's chores.
    await make_household(name="Someone else's")

    await init_admin(db_session, "owner@example.com", "Owner", "User", _INIT_PASSWORD)

    user = await db_session.scalar(select(User).where(User.email == "owner@example.com"))
    memberships = await db_session.scalar(
        select(func.count())
        .select_from(household_members)
        .where(household_members.c.user_id == user.id)
    )
    assert memberships == 0
    # The one household is still the pre-existing one, untouched.
    assert await db_session.scalar(select(func.count()).select_from(Household)) == 1


async def test_init_is_a_noop_when_an_active_admin_exists(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    original_hash = admin.password_hash

    await init_admin(db_session, "someone@example.com", "Some", "One", _INIT_PASSWORD)

    # Nothing created, and crucially the sitting admin's password is untouched:
    # this command lives in deploy scripts and must not reset it on every run.
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    await db_session.refresh(admin)
    assert admin.password_hash == original_hash


@pytest.mark.parametrize("status", [UserStatus.disabled, UserStatus.waiting_confirmation])
async def test_init_restores_the_sole_admin_under_its_own_email(
    db_session, make_user: Callable[..., Awaitable[User]], status: UserStatus
) -> None:
    # The finding: a non-active admin row satisfied the old "an admin exists"
    # check, so the documented recovery tool refused to help. Scoping to active
    # admins alone is not enough either, because the clash on the email would
    # then have aborted it.
    admin = await make_user(
        email="admin@example.com", is_admin=True, status=status, confirmed_at=None
    )

    await init_admin(db_session, "admin@example.com", "Admin", "User", _INIT_PASSWORD)

    await db_session.refresh(admin)
    assert admin.status == UserStatus.active
    assert admin.is_admin is True
    assert admin.confirmed_at is not None
    assert verify_password(_INIT_PASSWORD, admin.password_hash)
    # Repaired in place rather than duplicated.
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_init_promotes_a_surviving_non_admin(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    # No admin row at all (both were disabled and purged, say): an ordinary
    # active user named on the command line becomes the way back in.
    member = await make_user(email="member@example.com", is_admin=False)

    await init_admin(db_session, "member@example.com", "Member", "User", _INIT_PASSWORD)

    await db_session.refresh(member)
    assert member.is_admin is True
    assert member.status == UserStatus.active
    assert verify_password(_INIT_PASSWORD, member.password_hash)


async def test_init_does_not_duplicate_household_membership_when_restoring(
    db_session,
    make_user: Callable[..., Awaitable[User]],
    make_household: Callable[..., Awaitable[Household]],
) -> None:
    # The restore path must not create a household: the account already has one,
    # so doing so would leave a stray household behind on every recovery run.
    member = await make_user(email="member@example.com")
    await make_household(name="Existing", members=[member])

    await init_admin(db_session, "member@example.com", "Member", "User", _INIT_PASSWORD)

    rows = await db_session.scalar(
        select(func.count())
        .select_from(household_members)
        .where(household_members.c.user_id == member.id)
    )
    assert rows == 1
    # And no stray household either, which is what the membership count implies
    # but does not actually assert.
    assert await db_session.scalar(select(func.count()).select_from(Household)) == 1


async def test_init_restore_matches_a_mixed_case_email(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    # users.email is a case-sensitive unique index, so a lookup that skipped the
    # lowercasing would miss the row and create a SECOND account instead.
    admin = await make_user(email="admin@example.com", is_admin=True, status=UserStatus.disabled)

    await init_admin(db_session, "ADMIN@Example.COM", "Admin", "User", _INIT_PASSWORD)

    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    await db_session.refresh(admin)
    assert admin.status == UserStatus.active


async def test_init_restore_revokes_sessions_and_confirmation_links(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    # A session parked before the lockout must not come back as an admin session,
    # and a still-live emailed link must not be able to set a password of its own
    # for the account we just restored. This mirrors what update_user does on the
    # same changes.
    user = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    db_session.add(
        AuthToken(
            token_hash=hash_token(generate_token()),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db_session.add(
        ConfirmationToken(
            token_hash=hash_token(generate_token()),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    await init_admin(db_session, "member@example.com", "Member", "User", _INIT_PASSWORD)

    assert await db_session.scalar(select(func.count()).select_from(AuthToken)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ConfirmationToken)) == 0


async def test_init_restore_clears_two_factor_enrolment(
    db_session, make_user: Callable[..., Awaitable[User]], totp: str
) -> None:
    # Without this the recovery is a dead end: the password works but login stops
    # at the TOTP challenge, and reset-2fa needs an admin to call it.
    admin = await make_user(email="admin@example.com", is_admin=True, status=UserStatus.disabled)
    admin.totp_enabled = True
    admin.totp_secret = encrypt("JBSWY3DPEHPK3PXP")
    db_session.add(TwoFactorRecoveryCode(user_id=admin.id, code_hash=hash_token(generate_token())))
    await db_session.commit()

    await init_admin(db_session, "admin@example.com", "Admin", "User", _INIT_PASSWORD)

    await db_session.refresh(admin)
    assert admin.totp_enabled is False
    assert admin.totp_secret is None
    assert await db_session.scalar(select(func.count()).select_from(TwoFactorRecoveryCode)) == 0


async def test_init_restore_reports_every_change_and_audits_it(
    db_session, make_user: Callable[..., Awaitable[User]], capsys: pytest.CaptureFixture[str]
) -> None:
    # The printed list is the operator's only record when this runs from a shell,
    # and README documents that it says exactly what changed.
    user = await make_user(
        email="member@example.com", status=UserStatus.waiting_confirmation, confirmed_at=None
    )

    await init_admin(db_session, "member@example.com", "Member", "User", _INIT_PASSWORD)

    printed = capsys.readouterr().out
    assert "restored admin access for 'member@example.com'" in printed
    for expected in (
        "promoted to admin",
        "status waiting_confirmation -> active",
        "marked confirmed",
        "password reset",
        "sessions and pending confirmation links revoked",
    ):
        assert expected in printed
    # Also recorded in the audit trail, since stdout goes nowhere in a deploy script.
    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.target_user_id == user.id))
    assert event is not None
    assert event.action == AuditAction.user_updated
    assert event.actor_user_id is None  # no logged-in actor, only shell access
    assert "cli init recovery" in event.detail


async def test_init_noop_prints_and_does_not_audit(
    db_session, make_user: Callable[..., Awaitable[User]], capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(email="admin@example.com", is_admin=True)

    await init_admin(db_session, "other@example.com", "Other", "User", _INIT_PASSWORD)

    assert "an active admin already exists" in capsys.readouterr().out
    assert await db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_init_creates_a_second_admin_under_a_fresh_email(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    # The other half of recovery: rather than repairing the disabled account, an
    # operator can bring in a brand new admin. The disabled row is left alone.
    disabled = await make_user(
        email="old-admin@example.com", is_admin=True, status=UserStatus.disabled
    )

    await init_admin(db_session, "new-admin@example.com", "New", "Admin", _INIT_PASSWORD)

    fresh = await db_session.scalar(select(User).where(User.email == "new-admin@example.com"))
    assert fresh is not None
    assert fresh.is_admin is True
    assert fresh.status == UserStatus.active
    await db_session.refresh(disabled)
    assert disabled.status == UserStatus.disabled


async def test_init_ignores_a_disabled_admin_when_another_is_active(
    db_session, make_user: Callable[..., Awaitable[User]]
) -> None:
    # A disabled admin alongside a working one must not trigger recovery.
    disabled = await make_user(
        email="old-admin@example.com", is_admin=True, status=UserStatus.disabled
    )
    active = await make_user(email="admin@example.com", is_admin=True)
    original_hash = active.password_hash
    disabled_hash = disabled.password_hash

    await init_admin(db_session, "old-admin@example.com", "Old", "Admin", _INIT_PASSWORD)

    # Returned before touching anything: the named disabled account is NOT
    # revived just because it was passed on the command line.
    await db_session.refresh(disabled)
    assert disabled.status == UserStatus.disabled
    assert disabled.password_hash == disabled_hash
    await db_session.refresh(active)
    assert active.password_hash == original_hash
    assert await db_session.scalar(select(func.count()).select_from(User)) == 2


# --- clear_login_throttle helper ------------------------------------------


async def test_clear_login_throttle_by_email_clears_only_that_email(fake_redis: Redis) -> None:
    await fake_redis.set(_email_key("alice@example.com"), "3")
    await fake_redis.set(_email_key("bob@example.com"), "1")
    await fake_redis.set(_ip_key("10.0.0.1"), "7")

    removed = await clear_login_throttle(fake_redis, email="alice@example.com")

    assert removed == 1
    assert await fake_redis.get(_email_key("alice@example.com")) is None
    # Other counters (a different email, and the IP) are untouched.
    assert await fake_redis.get(_email_key("bob@example.com")) == "1"
    assert await fake_redis.get(_ip_key("10.0.0.1")) == "7"


async def test_clear_login_throttle_by_email_absent_returns_zero(fake_redis: Redis) -> None:
    removed = await clear_login_throttle(fake_redis, email="nobody@example.com")
    assert removed == 0


async def test_clear_login_throttle_all_clears_email_and_ip(fake_redis: Redis) -> None:
    await fake_redis.set(_email_key("alice@example.com"), "3")
    await fake_redis.set(_email_key("bob@example.com"), "1")
    await fake_redis.set(_ip_key("10.0.0.1"), "7")
    await fake_redis.set(_ip_key("10.0.0.2"), "2")
    # An unrelated key must survive a full clear.
    await fake_redis.set("something:else", "keep")

    removed = await clear_login_throttle(fake_redis)

    assert removed == 4
    assert [key async for key in fake_redis.scan_iter("login:fail:*")] == []
    assert await fake_redis.get("something:else") == "keep"


async def test_clear_login_throttle_all_empty_returns_zero(fake_redis: Redis) -> None:
    removed = await clear_login_throttle(fake_redis)
    assert removed == 0


async def test_clear_login_throttle_by_email_propagates_redis_error(
    fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unlike clear_login_failures (login hot path, fails open), the maintenance
    # helper must surface Redis errors rather than report a clear that didn't happen.
    def boom(*args: object, **kwargs: object) -> None:
        raise RedisError("redis down")

    monkeypatch.setattr(fake_redis, "delete", boom)
    with pytest.raises(RedisError):
        await clear_login_throttle(fake_redis, email="alice@example.com")


async def test_clear_login_throttle_all_propagates_redis_error(
    fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RedisError("redis down")

    monkeypatch.setattr(fake_redis, "scan_iter", boom)
    with pytest.raises(RedisError):
        await clear_login_throttle(fake_redis)


# --- clear_throttle CLI worker --------------------------------------------


async def test_clear_throttle_for_user_clears_only_their_email(
    db_session, fake_redis: Redis, make_user: Callable[..., Awaitable[User]]
) -> None:
    user = await make_user(email="locked@example.com")
    await fake_redis.set(_email_key(user.email), "5")
    await fake_redis.set(_ip_key("10.0.0.1"), "9")

    await clear_throttle(db_session, fake_redis, user.id)

    assert await fake_redis.get(_email_key(user.email)) is None
    # A per-user clear cannot touch an IP counter.
    assert await fake_redis.get(_ip_key("10.0.0.1")) == "9"


async def test_clear_throttle_unknown_user_exits_without_touching_redis(
    db_session, fake_redis: Redis
) -> None:
    await fake_redis.set(_email_key("alice@example.com"), "3")

    with pytest.raises(SystemExit):
        await clear_throttle(db_session, fake_redis, 999999)

    assert await fake_redis.get(_email_key("alice@example.com")) == "3"


async def test_clear_throttle_no_user_id_clears_all(
    db_session, fake_redis: Redis, make_user: Callable[..., Awaitable[User]]
) -> None:
    user = await make_user(email="locked@example.com")
    await fake_redis.set(_email_key(user.email), "5")
    await fake_redis.set(_ip_key("10.0.0.1"), "9")

    await clear_throttle(db_session, fake_redis, None)

    assert [key async for key in fake_redis.scan_iter("login:fail:*")] == []


# --- seed CLI worker ------------------------------------------------------


async def test_seed_creates_expected_dataset(db_session) -> None:
    summary = await seed(db_session)

    assert summary.users == 5
    assert summary.households == 6
    assert await db_session.scalar(select(func.count()).select_from(User)) == 5
    assert await db_session.scalar(select(func.count()).select_from(Household)) == 6

    # The first user is a login-able admin.
    admin = await db_session.scalar(select(User).where(User.email == "admin@example.com"))
    assert admin is not None and admin.is_admin
    assert verify_password(SEED_PASSWORD, admin.password_hash)

    # There is completion history, and no chore has more than one open occurrence.
    done_count = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(ChoreOccurrence.status == OccurrenceStatus.done)
    )
    assert done_count > 0
    dupes = (
        await db_session.execute(
            select(ChoreOccurrence.chore_id)
            .where(ChoreOccurrence.status == OccurrenceStatus.open)
            .group_by(ChoreOccurrence.chore_id)
            .having(func.count() > 1)
        )
    ).all()
    assert dupes == []

    # Every seeded closure carries the zone it was judged in, and no open row does. Without this
    # a reseeded stack has no snapshot anywhere in its history, so moving a seeded household
    # re-scores its lateness exactly as it did before the column existed - which makes the one
    # behaviour the snapshot exists to prevent the one a developer cannot see working locally.
    # A migrated database gets this from the backfill in e4b6c09d15af; this is the seeder's half
    # of "reseeded from scratch behaves like one that was upgraded".
    snapshots = (
        await db_session.execute(
            select(
                ChoreOccurrence.status,
                func.count(),
                func.count(ChoreOccurrence.completed_timezone),
            ).group_by(ChoreOccurrence.status)
        )
    ).all()
    by_status = {status: (rows, stamped) for status, rows, stamped in snapshots}
    done_rows, done_stamped = by_status[OccurrenceStatus.done]
    assert done_stamped == done_rows
    assert by_status[OccurrenceStatus.open][1] == 0
    assert (
        await db_session.scalar(
            select(ChoreOccurrence.completed_timezone).where(
                ChoreOccurrence.status == OccurrenceStatus.done
            )
        )
        == SEED_TIMEZONE
    )

    # A completed unscheduled chore keeps its done row AND stays open: it is repeatable on
    # demand, so it never terminates. It also stores no start date.
    bookshelf = await db_session.scalar(
        select(Chore).where(Chore.title == "Assemble the bookshelf")
    )
    assert bookshelf.start_date is None
    open_for_bookshelf = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(
            ChoreOccurrence.chore_id == bookshelf.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert open_for_bookshelf == 1
    done_for_bookshelf = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(
            ChoreOccurrence.chore_id == bookshelf.id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
    )
    assert done_for_bookshelf == 1

    # An unassigned (shared) chore exists: its open occurrence has no assignee.
    tidy = await db_session.scalar(select(Chore).where(Chore.title == "Tidy the shared shelf"))
    tidy_open = await db_session.scalar(
        select(ChoreOccurrence).where(
            ChoreOccurrence.chore_id == tidy.id, ChoreOccurrence.status == OccurrenceStatus.open
        )
    )
    assert tidy_open is not None and tidy_open.assignee_id is None

    # A rotating chore actually rotated: its history credits more than one person.
    plants = await db_session.scalar(select(Chore).where(Chore.title == "Water the plants"))
    distinct_completers = await db_session.scalar(
        select(func.count(distinct(ChoreOccurrence.completed_by_user_id))).where(
            ChoreOccurrence.chore_id == plants.id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
    )
    assert distinct_completers >= 2


async def test_seed_fresh_is_rerunnable(db_session) -> None:
    await seed(db_session, fresh=True)
    await seed(db_session, fresh=True)  # wipes the first run, no duplicate-email clash
    assert await db_session.scalar(select(func.count()).select_from(User)) == 5


async def test_seed_refuses_on_nonempty_db_without_fresh(db_session) -> None:
    await seed(db_session)
    with pytest.raises(RuntimeError, match="pass --fresh"):
        await seed(db_session)


def test_seed_guard_refuses_non_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.cli.settings.environment", "production")
    with pytest.raises(SystemExit):
        _guard_dev_environment()


def test_seed_guard_allows_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.cli.settings.environment", "dev")
    _guard_dev_environment()  # no raise
