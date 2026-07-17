"""Tests for the management CLI (`app.cli`).

The repo convention is to call the async worker functions directly with the
`fake_redis` / `db_session` / `make_user` fixtures rather than shelling out, and
to assert against Redis the way `test_rate_limit.py` does.
"""

from collections.abc import Awaitable, Callable

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cli import clear_throttle
from app.core.rate_limit import clear_login_throttle
from app.models import User


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
