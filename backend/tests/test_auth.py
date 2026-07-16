from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models import AuditAction, AuditEvent, AuthToken, User

Login = Callable[..., Awaitable[User]]


async def _token_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(AuthToken)) or 0


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
    assert body["email"] == "alice@example.com"
    assert body["id"] == user.id
    assert "password_hash" not in body
    assert client.cookies.get("isachore_token")
    assert await _token_count(db_session) == 1


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
    await make_user(email="ghost@example.com", password="password12345", is_active=False)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "password12345"},
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
    assert resp.json()["email"] == "alice@example.com"


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
