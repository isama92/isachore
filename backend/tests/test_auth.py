from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models import AuthToken, User

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
