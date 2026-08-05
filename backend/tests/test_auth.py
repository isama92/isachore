from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_app_settings
from app.core.security import generate_token, hash_token
from app.models import AuditAction, AuditEvent, AuthToken, User, UserStatus

Login = Callable[..., Awaitable[User]]


async def _token_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(AuthToken)) or 0


def _auth_cookie_header(resp: object) -> str:
    # The login response sets two cookies (the session token and the cleared
    # admin token); pick out the auth-token one so Max-Age can be asserted on it
    # rather than on the always-max-age=0 admin cookie.
    for header in resp.headers.get_list("set-cookie"):  # type: ignore[attr-defined]
        if header.startswith("isachore_token="):
            return header
    raise AssertionError("no isachore_token Set-Cookie header on the response")


async def test_login_success(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="alice@example.com", password="password12345")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )

    assert resp.status_code == 200
    body = resp.json()
    # A password-only login (no 2FA) completes in one step; the user rides in the
    # LoginResponse envelope.
    assert body["two_factor_required"] is False
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["id"] == user.id
    assert "password_hash" not in body["user"]
    assert client.cookies.get("isachore_token")
    assert await _token_count(db_session) == 1


async def test_login_remember_sets_persistent_cookie(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # "Remember me" -> a long-lived cookie (30-day Max-Age) and a token whose DB
    # expiry matches, so the session survives a browser restart.
    user = await make_user(email="alice@example.com", password="password12345")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345", "remember": True},
    )

    assert resp.status_code == 200
    assert "max-age=2592000" in _auth_cookie_header(resp).lower()  # 30 days
    token = (
        await db_session.execute(select(AuthToken).where(AuthToken.user_id == user.id))
    ).scalar_one()
    assert token.expires_at > datetime.now(UTC) + timedelta(days=29)


async def test_login_without_remember_sets_session_cookie(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # No "remember me" (the default) -> a session cookie (no Max-Age, dropped on
    # browser close) capped by a short-lived token, so a leaked token can't
    # outlive the browser session by more than a day.
    user = await make_user(email="alice@example.com", password="password12345")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )

    assert resp.status_code == 200
    assert "max-age" not in _auth_cookie_header(resp).lower()
    token = (
        await db_session.execute(select(AuthToken).where(AuthToken.user_id == user.id))
    ).scalar_one()
    now = datetime.now(UTC)
    assert now < token.expires_at < now + timedelta(days=2)


async def test_login_clears_admin_cookie(client: AsyncClient, make_user: Login) -> None:
    await make_user(email="alice@example.com", password="password12345")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )
    set_cookies = " ".join(resp.headers.get_list("set-cookie"))
    assert "isachore_admin_token" in set_cookies


async def test_login_wrong_password(client: AsyncClient, make_user: Login) -> None:
    await make_user(email="alice@example.com", password="password12345")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_unknown_email(client: AsyncClient) -> None:
    # Same message as wrong password so emails can't be enumerated
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password12345"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_inactive_user(client: AsyncClient, make_user: Login) -> None:
    await make_user(email="ghost@example.com", password="password12345", status=UserStatus.disabled)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "password12345"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_waiting_confirmation_user(client: AsyncClient, make_user: Login) -> None:
    # Only active users may authenticate: a user still awaiting confirmation
    # can't log in even with a correct password.
    await make_user(
        email="pending@example.com",
        password="password12345",
        status=UserStatus.waiting_confirmation,
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "pending@example.com", "password": "password12345"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_case_insensitive_email(client: AsyncClient, make_user: Login) -> None:
    # Stored lower-case; a differently-cased login still resolves the account (L3)
    await make_user(email="alice@example.com", password="password12345")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "Alice@Example.com", "password": "password12345"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "alice@example.com"


async def test_login_purges_expired_tokens(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # Expired rows are swept opportunistically at login so the table stays bounded (L1)
    await make_user(email="alice@example.com", password="password12345")
    bob = await make_user(email="bob@example.com")
    expired_hash = hash_token(generate_token())
    valid_hash = hash_token(generate_token())
    db_session.add_all(
        [
            AuthToken(
                token_hash=expired_hash,
                user_id=bob.id,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            ),
            AuthToken(
                token_hash=valid_hash,
                user_id=bob.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )
    assert resp.status_code == 200

    hashes = set((await db_session.execute(select(AuthToken.token_hash))).scalars().all())
    # The expired token is gone; the still-valid one and Alice's fresh token remain
    assert expired_hash not in hashes
    assert valid_hash in hashes
    assert await _token_count(db_session) == 2


async def test_me_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_me_authenticated(
    make_user: Login, auth_client: Callable[[User], Awaitable[AsyncClient]]
) -> None:
    user = await make_user(email="alice@example.com")
    client = await auth_client(user)

    resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["impersonating"] is False


async def test_me_via_bearer_header(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="alice@example.com")
    raw = generate_token()
    db_session.add(
        AuthToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw}"})

    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


async def test_logout(client: AsyncClient, make_user: Login, db_session: AsyncSession) -> None:
    await make_user(email="alice@example.com", password="password12345")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )
    assert await _token_count(db_session) == 1

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    assert await _token_count(db_session) == 0

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401


async def test_logout_with_invalid_token(client: AsyncClient) -> None:
    client.cookies.set("isachore_token", "not-a-real-token")
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204


async def test_stop_impersonating_without_admin_cookie(
    make_user: Login, auth_client: Callable[[User], Awaitable[AsyncClient]]
) -> None:
    user = await make_user(email="alice@example.com")
    client = await auth_client(user)

    resp = await client.post("/api/v1/auth/stop-impersonating")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "No impersonation in progress"


async def test_stop_impersonating_expired_admin_token(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # The parked admin token expired mid-impersonation: rather than a bare 401,
    # both sessions end and the operator is sent to login with a clear message (L5)
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")

    member_raw = generate_token()
    admin_raw = generate_token()
    db_session.add_all(
        [
            AuthToken(
                token_hash=hash_token(member_raw),
                user_id=member.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
            AuthToken(
                token_hash=hash_token(admin_raw),
                user_id=admin.id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
        ]
    )
    await db_session.commit()

    client.cookies.set("isachore_token", member_raw)
    client.cookies.set("isachore_admin_token", admin_raw)

    resp = await client.post("/api/v1/auth/stop-impersonating")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Your admin session has expired. Please log in again."
    # Both cookies are cleared in the response
    set_cookies = " ".join(resp.headers.get_list("set-cookie")).lower()
    assert "isachore_token=" in set_cookies
    assert "isachore_admin_token=" in set_cookies
    assert set_cookies.count("max-age=0") == 2
    # Both underlying tokens are removed so neither leaks
    remaining = set((await db_session.execute(select(AuthToken.token_hash))).scalars().all())
    assert hash_token(member_raw) not in remaining
    assert hash_token(admin_raw) not in remaining
    # The forced stop still closes the audit trail (matches the impersonate_start)
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == AuditAction.impersonate_stop)
    )
    assert event is not None
    assert event.target_user_id == member.id
    assert event.detail == "admin session expired"


async def test_me_reports_whether_the_server_asks_for_confirmation(
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[User]],
    auth_client: Callable[[User], Awaitable[AsyncClient]],
    smtp: list,
) -> None:
    """The Profile page shows its confirmation badge only when the server asks for one, and
    this is where it learns that: the flag is what tells a client how to read the
    `confirmed_at` in the same payload. A null there means nothing on a server that never
    asks, and "not proved" on one that does."""
    user = await make_user(email="member@example.com")
    client = await auth_client(user)

    assert (await client.get("/api/v1/auth/me")).json()["email_confirmation_required"] is False

    app_settings = await get_app_settings(db_session)
    app_settings.require_confirmation = True
    await db_session.commit()

    assert (await client.get("/api/v1/auth/me")).json()["email_confirmation_required"] is True


async def test_the_login_response_carries_the_confirmation_flag_too(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[User]],
    smtp: list,
) -> None:
    # Login sets the client's auth state directly rather than refetching, so a flag missing
    # here would leave the first screen after signing in reading `confirmed_at` wrongly.
    await make_user(email="member@example.com", password="password12345")
    app_settings = await get_app_settings(db_session)
    app_settings.require_confirmation = True
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password12345"},
    )

    assert resp.json()["user"]["email_confirmation_required"] is True
