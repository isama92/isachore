from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.models import User

Login = Callable[..., Awaitable[User]]


async def _login(client: AsyncClient, email: str, password: str, **kwargs: object) -> object:
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, **kwargs
    )


async def test_lockout_after_max_failed_attempts(
    client: AsyncClient, make_user: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")

    for _ in range(3):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401

    # The next attempt is locked out even with the CORRECT password.
    resp = await _login(client, "alice@example.com", "password12345")
    assert resp.status_code == 429
    assert 0 < int(resp.headers["Retry-After"]) <= settings.login_attempt_window
    assert "Too many failed login attempts" in resp.json()["detail"]


async def test_successful_login_resets_email_counter(
    client: AsyncClient, make_user: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")

    for _ in range(2):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    assert (await _login(client, "alice@example.com", "password12345")).status_code == 200

    # After the reset two fresh failures are still under the limit, so a correct
    # login succeeds again; without the reset the counter would already be locked.
    for _ in range(2):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    assert (await _login(client, "alice@example.com", "password12345")).status_code == 200


async def test_different_emails_counted_independently(
    client: AsyncClient, make_user: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")
    await make_user(email="bob@example.com", password="password12345")

    for _ in range(3):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    assert (await _login(client, "alice@example.com", "password12345")).status_code == 429
    # Bob's account is unaffected by Alice's lockout.
    assert (await _login(client, "bob@example.com", "password12345")).status_code == 200


async def test_lockout_key_is_case_insensitive(
    client: AsyncClient, make_user: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")

    for _ in range(3):
        assert (await _login(client, "ALICE@example.com", "wrong-password")).status_code == 401
    # Different casing, same account -> still locked out.
    assert (await _login(client, "alice@example.com", "password12345")).status_code == 429


async def test_ip_lockout_across_distinct_emails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)

    for i in range(3):
        assert (await _login(client, f"nobody{i}@example.com", "wrong")).status_code == 401
    # A fourth attempt from the same IP is IP-locked regardless of the email.
    resp = await _login(client, "someone-else@example.com", "wrong")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_forwarded_for_ignored_by_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    # trust_forwarded_for stays at its default (False).

    for i in range(3):
        resp = await _login(
            client, f"nobody{i}@example.com", "wrong", headers={"X-Forwarded-For": f"10.0.0.{i}"}
        )
        assert resp.status_code == 401
    # Despite distinct forwarded IPs, all counted under the real peer -> locked.
    resp = await _login(
        client, "nobody9@example.com", "wrong", headers={"X-Forwarded-For": "10.0.0.9"}
    )
    assert resp.status_code == 429


async def test_forwarded_for_trusted_separates_counters(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    monkeypatch.setattr(settings, "trust_forwarded_for", True)

    for i in range(3):
        resp = await _login(
            client, f"nobody{i}@example.com", "wrong", headers={"X-Forwarded-For": "10.0.0.1"}
        )
        assert resp.status_code == 401
    locked = await _login(
        client, "nobody9@example.com", "wrong", headers={"X-Forwarded-For": "10.0.0.1"}
    )
    assert locked.status_code == 429
    # A different forwarded IP has its own budget.
    other = await _login(
        client, "nobody8@example.com", "wrong", headers={"X-Forwarded-For": "10.0.0.2"}
    )
    assert other.status_code == 401


async def test_forwarded_for_keys_on_rightmost_hop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The trusted proxy appends the real peer as the right-most hop; the left-most
    # entries are client-controlled and must not be trusted. Requests with a
    # spoofed, varying left-most but the same right-most must share one counter.
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    monkeypatch.setattr(settings, "trust_forwarded_for", True)

    for i in range(3):
        resp = await _login(
            client,
            f"nobody{i}@example.com",
            "wrong",
            headers={"X-Forwarded-For": f"1.2.3.{i}, 9.9.9.9"},
        )
        assert resp.status_code == 401
    # Different spoofed left-most, same real right-most -> still locked.
    resp = await _login(
        client, "nobody9@example.com", "wrong", headers={"X-Forwarded-For": "7.7.7.7, 9.9.9.9"}
    )
    assert resp.status_code == 429


async def test_x_real_ip_takes_precedence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    monkeypatch.setattr(settings, "trust_forwarded_for", True)

    for i in range(3):
        resp = await _login(
            client,
            f"nobody{i}@example.com",
            "wrong",
            headers={"X-Real-IP": "9.9.9.9", "X-Forwarded-For": f"1.2.3.{i}"},
        )
        assert resp.status_code == 401
    # Same X-Real-IP, different (ignored) X-Forwarded-For -> still locked.
    resp = await _login(
        client,
        "nobody9@example.com",
        "wrong",
        headers={"X-Real-IP": "9.9.9.9", "X-Forwarded-For": "8.8.8.8"},
    )
    assert resp.status_code == 429


async def test_locked_out_attempts_do_not_extend_the_lockout(
    client: AsyncClient, make_user: Login, fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")

    for _ in range(3):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401

    key = "login:fail:email:alice@example.com"
    assert await fake_redis.get(key) == "3"
    ttl_before = await fake_redis.ttl(key)

    # Hammering while locked must neither raise the counter nor reset the TTL.
    for _ in range(5):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 429
    assert await fake_redis.get(key) == "3"
    assert await fake_redis.ttl(key) <= ttl_before


async def test_login_fails_open_when_redis_unavailable(
    client: AsyncClient, make_user: Login, fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A Redis outage must degrade to no throttling, not a 500 on every login.
    await make_user(email="alice@example.com", password="password12345")

    async def boom_async(*args: object, **kwargs: object) -> object:
        raise RedisConnectionError("redis down")

    def boom_sync(*args: object, **kwargs: object) -> object:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(fake_redis, "get", boom_async)
    monkeypatch.setattr(fake_redis, "delete", boom_async)
    monkeypatch.setattr(fake_redis, "pipeline", boom_sync)

    # A wrong password still returns 401 (not 500) despite the failed record.
    bad = await _login(client, "alice@example.com", "wrong-password")
    assert bad.status_code == 401
    # And a correct login still succeeds despite the failed enforce/clear.
    good = await _login(client, "alice@example.com", "password12345")
    assert good.status_code == 200


async def test_success_clears_email_counter_but_not_ip_counter(
    client: AsyncClient, make_user: Login, fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_max_attempts", 100)
    monkeypatch.setattr(settings, "login_ip_max_attempts", 100)
    await make_user(email="alice@example.com", password="password12345")

    assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    ip_keys = [key async for key in fake_redis.scan_iter("login:fail:ip:*")]
    assert len(ip_keys) == 1
    ip_count_before = await fake_redis.get(ip_keys[0])

    assert (await _login(client, "alice@example.com", "password12345")).status_code == 200
    assert await fake_redis.get("login:fail:email:alice@example.com") is None
    assert await fake_redis.get(ip_keys[0]) == ip_count_before
