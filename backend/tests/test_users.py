from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models import AuthToken, User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def _token_count(session: AsyncSession, user_id: int) -> int:
    query = select(func.count()).select_from(AuthToken).where(AuthToken.user_id == user_id)
    return await session.scalar(query) or 0


async def _issue_token(session: AsyncSession, user: User) -> str:
    raw = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await session.commit()
    return raw


# --- list ---------------------------------------------------------------


async def test_list_users_as_admin(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users")

    assert resp.status_code == 200
    body = resp.json()
    # Ordered by id, i.e. creation order (admin first, then member)
    assert [u["email"] for u in body] == ["admin@example.com", "member@example.com"]
    assert [u["id"] for u in body] == sorted(u["id"] for u in body)


async def test_list_users_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin only"


async def test_list_users_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


# --- create -------------------------------------------------------------


async def test_create_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "newbie@example.com",
            "name": "New Member",
            "password": "password12345",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newbie@example.com"
    assert body["is_admin"] is False
    assert body["is_active"] is True
    assert "password_hash" not in body

    # password stored hashed -> the new credentials actually work
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbie@example.com", "password": "password12345"},
    )
    assert login.status_code == 200


async def test_create_user_duplicate_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="taken@example.com")
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "taken@example.com", "name": "Dup", "password": "password12345"},
    )
    assert resp.status_code == 409


async def test_create_user_invalid_payload(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "not-an-email", "name": "", "password": "short"},
    )
    assert resp.status_code == 422


async def test_create_user_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.post(
        "/api/v1/users",
        json={"email": "x@example.com", "name": "X", "password": "password12345"},
    )
    assert resp.status_code == 403


# --- update -------------------------------------------------------------


async def test_update_user_name_and_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", name="Old Name")
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/users/{member.id}",
        json={"name": "New Name", "email": "renamed@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["email"] == "renamed@example.com"


async def test_update_user_email_conflict(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"email": other.email})
    assert resp.status_code == 409


async def test_update_own_unchanged_email_allowed(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"email": "admin@example.com", "name": "Renamed Admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Admin"


async def test_update_self_demote_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"is_admin": False})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"


async def test_update_self_deactivate_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"is_active": False})
    assert resp.status_code == 400


async def test_update_password_revokes_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    assert await _token_count(db_session, member.id) == 1
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"password": "newpassword123"})

    assert resp.status_code == 200
    assert await _token_count(db_session, member.id) == 0


async def test_update_deactivate_revokes_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"is_active": False})

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert await _token_count(db_session, member.id) == 0


async def test_update_missing_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch("/api/v1/users/999999", json={"name": "Nope"})
    assert resp.status_code == 404


# --- impersonation ------------------------------------------------------


async def test_impersonation_round_trip(client: AsyncClient, make_user: Login) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    member = await make_user(email="member@example.com")

    # Drive the whole state machine through one client so the cookie jar carries
    # every Set-Cookie the way a browser would.
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )

    imp = await client.post(f"/api/v1/users/{member.id}/impersonate")
    assert imp.status_code == 200
    assert imp.json()["email"] == "member@example.com"

    me = await client.get("/api/v1/auth/me")
    assert me.json()["email"] == "member@example.com"
    assert me.json()["impersonating"] is True

    stop = await client.post("/api/v1/auth/stop-impersonating")
    assert stop.status_code == 200
    assert stop.json()["email"] == "admin@example.com"

    me_again = await client.get("/api/v1/auth/me")
    assert me_again.json()["email"] == "admin@example.com"
    assert me_again.json()["impersonating"] is False


async def test_impersonate_self_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.post(f"/api/v1/users/{admin.id}/impersonate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You are already this user"


async def test_impersonate_inactive_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", is_active=False)
    client = await auth_client(admin)
    resp = await client.post(f"/api/v1/users/{member.id}/impersonate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot log in as an inactive user"


async def test_impersonate_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com")
    client = await auth_client(member)
    resp = await client.post(f"/api/v1/users/{target.id}/impersonate")
    assert resp.status_code == 403


# --- impersonation self-guard (H1) --------------------------------------
# The "cannot demote/deactivate yourself" guard must protect the real operator
# behind the parked admin cookie, not just the impersonated session identity.
# Otherwise an admin who impersonates a second admin could strip or deactivate
# their own real account by proxy.


async def test_impersonating_admin_cannot_demote_real_operator(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # Acting as Eve, demoting the operator's own real account must be refused
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"is_admin": False})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"
    await db_session.refresh(admin)
    assert admin.is_admin is True


async def test_impersonating_admin_cannot_deactivate_real_operator(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    resp = await client.delete(f"/api/v1/users/{admin.id}")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot deactivate yourself"
    await db_session.refresh(admin)
    assert admin.is_active is True


async def test_impersonating_admin_cannot_demote_current_session(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # The impersonated session identity is still guarded (the "as well as the
    # current one" half of the fix)
    resp = await client.patch(f"/api/v1/users/{eve.id}", json={"is_admin": False})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"
    await db_session.refresh(eve)
    assert eve.is_admin is True


async def test_impersonating_admin_can_demote_other_admin(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)
    carol = await make_user(email="carol@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # A third admin who is neither the operator nor the impersonated session can
    # still be managed: the guard is scoped to the self-ids, not all admins
    resp = await client.patch(f"/api/v1/users/{carol.id}", json={"is_admin": False})

    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False
    await db_session.refresh(carol)
    assert carol.is_admin is False


# --- delete (soft) ------------------------------------------------------


async def test_delete_user_soft(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    client = await auth_client(admin)

    resp = await client.delete(f"/api/v1/users/{member.id}")

    assert resp.status_code == 204
    assert await _token_count(db_session, member.id) == 0
    # Row still present, just deactivated (soft delete)
    refreshed = await db_session.get(User, member.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.is_active is False


async def test_delete_self_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.delete(f"/api/v1/users/{admin.id}")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot deactivate yourself"


async def test_delete_missing_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.delete("/api/v1/users/999999")
    assert resp.status_code == 404


async def test_delete_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com")
    client = await auth_client(member)
    resp = await client.delete(f"/api/v1/users/{target.id}")
    assert resp.status_code == 403
