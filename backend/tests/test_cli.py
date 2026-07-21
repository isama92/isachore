"""Tests for the management CLI (`app.cli`).

The repo convention is to call the async worker functions directly with the
`fake_redis` / `db_session` / `make_user` fixtures rather than shelling out, and
to assert against Redis the way `test_rate_limit.py` does.
"""

from collections.abc import Awaitable, Callable

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import distinct, func, select

from app.cli import _guard_dev_environment, clear_throttle
from app.core.rate_limit import clear_login_throttle
from app.core.security import verify_password
from app.db.seed import SEED_PASSWORD, seed
from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, User


def _email_key(email: str) -> str:
    return f"login:fail:email:{email}"


def _ip_key(ip: str) -> str:
    return f"login:fail:ip:{ip}"


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

    # A completed one-off keeps its done row but has no open occurrence (gone from Home).
    bookshelf = await db_session.scalar(
        select(Chore).where(Chore.title == "Assemble the bookshelf")
    )
    open_for_bookshelf = await db_session.scalar(
        select(func.count())
        .select_from(ChoreOccurrence)
        .where(
            ChoreOccurrence.chore_id == bookshelf.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert open_for_bookshelf == 0

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
