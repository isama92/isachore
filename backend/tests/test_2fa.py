from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.security import generate_token, hash_token
from app.models import AuthToken, TwoFactorChallenge, TwoFactorRecoveryCode, User

Login = Callable[..., Awaitable[User]]
Auth = Callable[[User], Awaitable[AsyncClient]]

LOGIN = "/api/v1/auth/login"
VERIFY = "/api/v1/auth/verify-2fa"
SETUP = "/api/v1/profile/2fa/setup"
CONFIRM = "/api/v1/profile/2fa/confirm"
DISABLE = "/api/v1/profile/2fa/disable"
REGEN = "/api/v1/profile/2fa/recovery-codes"
ME = "/api/v1/auth/me"

PASSWORD = "password12345"


def _reset(user_id: int) -> str:
    return f"/api/v1/admin/users/{user_id}/reset-2fa"


async def _enroll(session: AsyncSession, user: User, *, recovery: tuple[str, ...] = ()) -> str:
    """Directly enrol a user in 2FA (encrypted secret + enabled + optional
    recovery codes). Returns the plaintext TOTP secret. Requires the `totp`
    fixture so encrypt() has a key."""
    secret = pyotp.random_base32()
    user.totp_secret = encrypt(secret)
    user.totp_enabled = True
    for code in recovery:
        session.add(TwoFactorRecoveryCode(user_id=user.id, code_hash=hash_token(code)))
    await session.commit()
    await session.refresh(user)
    return secret


def _now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


async def _recovery_count(session: AsyncSession, user_id: int, *, unused: bool = False) -> int:
    query = (
        select(func.count())
        .select_from(TwoFactorRecoveryCode)
        .where(TwoFactorRecoveryCode.user_id == user_id)
    )
    if unused:
        query = query.where(TwoFactorRecoveryCode.used_at.is_(None))
    return await session.scalar(query) or 0


# --- setup / confirm (enable) --------------------------------------------------


async def test_setup_then_confirm_enables_and_returns_recovery_codes(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    auth_client: Auth,
    totp: str,
) -> None:
    user = await make_user()
    ac = await auth_client(user)

    setup = await ac.post(SETUP)
    assert setup.status_code == 200
    body = setup.json()
    secret = body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr"].startswith("data:image/png;base64,")

    # The seed is encrypted at rest: the stored column is not the plaintext, but
    # decrypts back to it.
    await db_session.refresh(user)
    assert user.totp_secret != secret
    assert decrypt(user.totp_secret) == secret
    assert user.totp_enabled is False  # not active until confirmed

    confirm = await ac.post(CONFIRM, json={"code": _now(secret)})
    assert confirm.status_code == 200
    codes = confirm.json()["recovery_codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10  # all distinct

    await db_session.refresh(user)
    assert user.totp_enabled is True
    assert await _recovery_count(db_session, user.id) == 10

    me = await ac.get(ME)
    assert me.json()["two_factor_enabled"] is True


async def test_confirm_rejects_wrong_code(
    client: AsyncClient, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    ac = await auth_client(user)
    await ac.post(SETUP)
    resp = await ac.post(CONFIRM, json={"code": "000000"})
    assert resp.status_code == 400
    assert (await ac.get(ME)).json()["two_factor_enabled"] is False


async def test_confirm_without_setup_is_400(
    client: AsyncClient, make_user: Login, auth_client: Auth, totp: str
) -> None:
    ac = await auth_client(await make_user())
    resp = await ac.post(CONFIRM, json={"code": "123456"})
    assert resp.status_code == 400
    assert "setup" in resp.json()["detail"].lower()


async def test_confirm_conflicts_when_already_enabled(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)
    ac = await auth_client(user)
    resp = await ac.post(CONFIRM, json={"code": "123456"})
    assert resp.status_code == 409


async def test_empty_code_is_422(
    client: AsyncClient, make_user: Login, auth_client: Auth, totp: str
) -> None:
    # min_length=1 on the code field: an empty code is a validation error.
    ac = await auth_client(await make_user())
    resp = await ac.post(CONFIRM, json={"code": ""})
    assert resp.status_code == 422


async def test_setup_conflicts_when_already_enabled(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)
    ac = await auth_client(user)
    resp = await ac.post(SETUP)
    assert resp.status_code == 409


async def test_setup_fails_closed_without_app_key(
    client: AsyncClient, make_user: Login, auth_client: Auth
) -> None:
    # No `totp` fixture -> APP_KEY unset -> 503, never a half-configured enrolment.
    ac = await auth_client(await make_user())
    resp = await ac.post(SETUP)
    assert resp.status_code == 503


async def test_2fa_endpoints_require_auth(client: AsyncClient, totp: str) -> None:
    for path in (SETUP, CONFIRM, DISABLE, REGEN):
        resp = await client.post(path, json={"code": "123456"})
        assert resp.status_code == 401, path


# --- two-step login ------------------------------------------------------------


async def test_login_with_2fa_requires_code_not_a_session(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)

    resp = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json() == {"two_factor_required": True, "user": None}
    # A challenge cookie is set, but NOT a session cookie...
    assert "isachore_2fa" in resp.cookies
    assert "isachore_token" not in resp.cookies
    # ...so the user is not authenticated yet.
    assert (await client.get(ME)).status_code == 401


async def test_verify_with_totp_completes_login(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, totp: str
) -> None:
    user = await make_user()
    secret = await _enroll(db_session, user)
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    resp = await client.post(VERIFY, json={"code": _now(secret)})
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email
    assert "isachore_token" in resp.cookies
    assert (await client.get(ME)).status_code == 200
    # The challenge is consumed on success.
    assert await db_session.scalar(select(func.count()).select_from(TwoFactorChallenge)) == 0


async def test_verify_with_recovery_code_is_single_use(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user, recovery=("BACKUPCODE01",))
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    first = await client.post(VERIFY, json={"code": "BACKUPCODE01"})
    assert first.status_code == 200
    assert await _recovery_count(db_session, user.id, unused=True) == 0

    # A fresh login + the same (now used) recovery code must be rejected.
    client.cookies.clear()
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    second = await client.post(VERIFY, json={"code": "BACKUPCODE01"})
    assert second.status_code == 401


async def test_verify_wrong_code_keeps_challenge(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, totp: str
) -> None:
    user = await make_user()
    secret = await _enroll(db_session, user)
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    bad = await client.post(VERIFY, json={"code": "000000"})
    assert bad.status_code == 401
    # A typo must not burn the challenge: the correct code still works.
    good = await client.post(VERIFY, json={"code": _now(secret)})
    assert good.status_code == 200


async def test_verify_without_challenge_is_401(client: AsyncClient, totp: str) -> None:
    resp = await client.post(VERIFY, json={"code": "123456"})
    assert resp.status_code == 401


async def test_verify_expired_challenge_is_401(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)
    raw = generate_token()
    db_session.add(
        TwoFactorChallenge(
            token_hash=hash_token(raw),
            user_id=user.id,
            remember=False,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    client.cookies.set("isachore_2fa", raw)
    resp = await client.post(VERIFY, json={"code": "123456"})
    assert resp.status_code == 401


async def test_login_without_2fa_returns_user(client: AsyncClient, make_user: Login) -> None:
    user = await make_user()
    resp = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["two_factor_required"] is False
    assert body["user"]["email"] == user.email
    assert body["user"]["two_factor_enabled"] is False
    # The encrypted seed must never be serialised to a client.
    assert "totp_secret" not in body["user"]
    assert "isachore_token" in resp.cookies
    assert (await client.get(ME)).status_code == 200


async def test_login_fails_closed_when_app_key_missing(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    totp: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    await _enroll(db_session, user)  # needs the key to encrypt the seed
    # Now simulate the key going missing at login time: a 2FA account must be
    # refused, never let in on the password alone.
    monkeypatch.setattr(settings, "app_key", None)
    resp = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 503
    assert "isachore_token" not in resp.cookies


# --- verify throttling ---------------------------------------------------------


async def test_verify_is_throttled(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    totp: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "two_factor_max_attempts", 3)
    user = await make_user()
    await _enroll(db_session, user)
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    for _ in range(3):
        assert (await client.post(VERIFY, json={"code": "000000"})).status_code == 401
    locked = await client.post(VERIFY, json={"code": "000000"})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


async def test_verify_fails_open_when_redis_down(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: Redis,
    make_user: Login,
    totp: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    secret = await _enroll(db_session, user)
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RedisError("down")

    # The throttle read and the success-path clears all touch Redis; none of them
    # should turn a cache outage into a failed login.
    monkeypatch.setattr(fake_redis, "get", _boom)
    monkeypatch.setattr(fake_redis, "delete", _boom)
    resp = await client.post(VERIFY, json={"code": _now(secret)})
    assert resp.status_code == 200


# --- disable / regenerate ------------------------------------------------------


async def test_disable_with_totp_turns_off(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    secret = await _enroll(db_session, user, recovery=("KEEPCODE0001",))
    ac = await auth_client(user)
    resp = await ac.post(DISABLE, json={"code": _now(secret)})
    assert resp.status_code == 200
    assert resp.json()["two_factor_enabled"] is False
    await db_session.refresh(user)
    assert user.totp_secret is None
    assert user.totp_enabled is False
    assert await _recovery_count(db_session, user.id) == 0


async def test_disable_with_recovery_code(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user, recovery=("RECOVERYAAA1",))
    ac = await auth_client(user)
    resp = await ac.post(DISABLE, json={"code": "RECOVERYAAA1"})
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.totp_enabled is False


async def test_disable_wrong_code_is_400(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)
    ac = await auth_client(user)
    resp = await ac.post(DISABLE, json={"code": "000000"})
    assert resp.status_code == 400
    await db_session.refresh(user)
    assert user.totp_enabled is True


async def test_disable_when_not_enabled_is_400(
    client: AsyncClient, make_user: Login, auth_client: Auth, totp: str
) -> None:
    ac = await auth_client(await make_user())
    resp = await ac.post(DISABLE, json={"code": "123456"})
    assert resp.status_code == 400


async def test_regenerate_recovery_codes(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    secret = await _enroll(db_session, user, recovery=("OLDCODE00001", "OLDCODE00002"))
    ac = await auth_client(user)
    resp = await ac.post(REGEN, json={"code": _now(secret)})
    assert resp.status_code == 200
    new_codes = resp.json()["recovery_codes"]
    assert len(new_codes) == 10
    # The old codes are gone: exactly the 10 fresh ones remain.
    assert await _recovery_count(db_session, user.id) == 10
    stored = set((await db_session.execute(select(TwoFactorRecoveryCode.code_hash))).scalars())
    assert stored == {hash_token(c) for c in new_codes}


async def test_regenerate_requires_enabled(
    client: AsyncClient, make_user: Login, auth_client: Auth, totp: str
) -> None:
    ac = await auth_client(await make_user())
    resp = await ac.post(REGEN, json={"code": "123456"})
    assert resp.status_code == 400


async def test_regenerate_wrong_code_is_400(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    user = await make_user()
    await _enroll(db_session, user)
    ac = await auth_client(user)
    resp = await ac.post(REGEN, json={"code": "000000"})
    assert resp.status_code == 400


async def test_recovery_code_survives_key_rotation(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    totp: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    await _enroll(db_session, user, recovery=("SURVIVOR0001",))
    # Rotate APP_KEY: the encrypted seed can no longer be decrypted...
    monkeypatch.setattr(settings, "app_key", Fernet.generate_key().decode())
    await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    # ...so a TOTP fails cleanly (401, not a 500 from the decrypt error)...
    assert (await client.post(VERIFY, json={"code": "000000"})).status_code == 401
    # ...but the independently-hashed recovery code still lets the user in.
    assert (await client.post(VERIFY, json={"code": "SURVIVOR0001"})).status_code == 200


# --- admin reset ---------------------------------------------------------------


async def test_admin_reset_2fa_clears_enrolment(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    target = await make_user(email="target@example.com")
    await _enroll(db_session, target, recovery=("TARGETCODE01",))
    admin = await make_user(email="admin@example.com", is_admin=True)
    ac = await auth_client(admin)

    resp = await ac.post(_reset(target.id))
    assert resp.status_code == 200
    assert resp.json()["two_factor_enabled"] is False
    await db_session.refresh(target)
    assert target.totp_secret is None
    assert target.totp_enabled is False
    assert await _recovery_count(db_session, target.id) == 0


async def test_reset_2fa_requires_admin(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com")
    await _enroll(db_session, target)
    ac = await auth_client(member)
    resp = await ac.post(_reset(target.id))
    assert resp.status_code == 403


async def test_reset_2fa_unknown_user_is_404(
    client: AsyncClient, make_user: Login, auth_client: Auth
) -> None:
    ac = await auth_client(await make_user(is_admin=True))
    resp = await ac.post(_reset(999999))
    assert resp.status_code == 404


async def test_reset_2fa_keeps_existing_sessions(
    client: AsyncClient, db_session: AsyncSession, make_user: Login, auth_client: Auth, totp: str
) -> None:
    target = await make_user(email="target@example.com")
    await _enroll(db_session, target)
    # Give the target a live session token.
    db_session.add(
        AuthToken(
            token_hash=hash_token(generate_token()),
            user_id=target.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    ac = await auth_client(await make_user(email="admin@example.com", is_admin=True))
    await ac.post(_reset(target.id))

    # Reset is about future logins, so the target's session token is untouched.
    remaining = await db_session.scalar(
        select(func.count()).select_from(AuthToken).where(AuthToken.user_id == target.id)
    )
    assert remaining == 1
