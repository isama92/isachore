from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models import ConfirmationToken, User, UserStatus

Login = Callable[..., Awaitable[User]]


async def _make_confirmation(
    session: AsyncSession, user: User, ttl: timedelta = timedelta(days=1)
) -> str:
    raw = generate_token()
    session.add(
        ConfirmationToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.commit()
    return raw


async def _confirmation_count(session: AsyncSession, user_id: int) -> int:
    query = (
        select(func.count())
        .select_from(ConfirmationToken)
        .where(ConfirmationToken.user_id == user_id)
    )
    return await session.scalar(query) or 0


# --- GET (link info) ----------------------------------------------------


async def test_confirmation_info_valid(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(
        email="newbie@example.com",
        first_name="New",
        last_name="Bie",
        status=UserStatus.waiting_confirmation,
    )
    raw = await _make_confirmation(db_session, user)

    resp = await client.get(f"/api/v1/confirm/{raw}")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"email": "newbie@example.com", "first_name": "New", "last_name": "Bie"}


async def test_confirmation_info_invalid_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/confirm/not-a-real-token")
    assert resp.status_code == 404


async def test_confirmation_info_expired_token(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="newbie@example.com", status=UserStatus.waiting_confirmation)
    raw = await _make_confirmation(db_session, user, ttl=timedelta(days=-1))

    resp = await client.get(f"/api/v1/confirm/{raw}")
    assert resp.status_code == 404


# --- POST (set password) ------------------------------------------------


async def test_confirm_sets_password_activates_and_logs_in(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="newbie@example.com", status=UserStatus.waiting_confirmation)
    raw = await _make_confirmation(db_session, user)

    resp = await client.post(f"/api/v1/confirm/{raw}", json={"password": "brandnewpass123"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["confirmed_at"] is not None

    # Auto-login: the session cookie is set, so /me resolves the user.
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "newbie@example.com"

    # Token consumed.
    assert await _confirmation_count(db_session, user.id) == 0


async def test_confirm_new_password_can_log_in(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="newbie@example.com", status=UserStatus.waiting_confirmation)
    raw = await _make_confirmation(db_session, user)
    await client.post(f"/api/v1/confirm/{raw}", json={"password": "brandnewpass123"})
    await client.post("/api/v1/auth/logout")

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbie@example.com", "password": "brandnewpass123"},
    )
    assert login.status_code == 200


async def test_confirm_password_too_short(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="newbie@example.com", status=UserStatus.waiting_confirmation)
    raw = await _make_confirmation(db_session, user)

    resp = await client.post(f"/api/v1/confirm/{raw}", json={"password": "short"})
    assert resp.status_code == 422


async def test_confirm_invalid_token(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/confirm/bogus", json={"password": "brandnewpass123"})
    assert resp.status_code == 404


async def test_confirm_token_is_single_use(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="newbie@example.com", status=UserStatus.waiting_confirmation)
    raw = await _make_confirmation(db_session, user)

    first = await client.post(f"/api/v1/confirm/{raw}", json={"password": "brandnewpass123"})
    assert first.status_code == 200
    second = await client.post(f"/api/v1/confirm/{raw}", json={"password": "anotherpass123"})
    assert second.status_code == 404
