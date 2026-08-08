from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_event
from app.models import AuditAction, AuditEvent, User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def _events(session: AsyncSession, action: AuditAction) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
    )
    return list(result.scalars())


async def test_login_success_is_audited(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    user = await make_user(email="alice@example.com", password="password12345")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "password12345"}
    )
    assert resp.status_code == 200

    events = await _events(db_session, AuditAction.login_success)
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert events[0].target_user_id is None
    assert events[0].ip_address == "127.0.0.1"


async def test_login_failure_is_audited_and_persists(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    await make_user(email="alice@example.com", password="password12345")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401

    # Persisted despite the 401; actor unknown, attempted email in detail.
    events = await _events(db_session, AuditAction.login_failed)
    assert len(events) == 1
    assert events[0].actor_user_id is None
    assert events[0].detail == "alice@example.com"


async def test_login_failure_detail_is_lowercased(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "NOBODY@example.com", "password": "x"}
    )
    assert resp.status_code == 401
    events = await _events(db_session, AuditAction.login_failed)
    assert len(events) == 1
    assert events[0].detail == "nobody@example.com"


async def test_logout_is_audited(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(email="alice@example.com")
    client = await auth_client(user)

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    events = await _events(db_session, AuditAction.logout)
    assert len(events) == 1
    assert events[0].actor_user_id == user.id


async def test_impersonation_round_trip_is_audited(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    target = await make_user(email="bob@example.com")
    client = await auth_client(admin)

    start = await client.post(f"/api/v1/admin/users/{target.id}/impersonate")
    assert start.status_code == 200
    starts = await _events(db_session, AuditAction.impersonate_start)
    assert len(starts) == 1
    assert starts[0].actor_user_id == admin.id
    assert starts[0].target_user_id == target.id
    assert starts[0].impersonator_user_id is None

    stop = await client.post("/api/v1/auth/stop-impersonating")
    assert stop.status_code == 200
    stops = await _events(db_session, AuditAction.impersonate_stop)
    assert len(stops) == 1
    assert stops[0].actor_user_id == admin.id
    assert stops[0].target_user_id == target.id


async def test_user_created_and_deactivated_are_audited(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    created = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "Person",
            "password": "password12345",
            "is_admin": False,
        },
    )
    assert created.status_code == 201
    new_id = created.json()["id"]

    create_events = await _events(db_session, AuditAction.user_created)
    assert len(create_events) == 1
    assert create_events[0].actor_user_id == admin.id
    assert create_events[0].target_user_id == new_id
    assert create_events[0].impersonator_user_id is None

    deleted = await client.delete(f"/api/v1/admin/users/{new_id}")
    assert deleted.status_code == 204

    deactivate_events = await _events(db_session, AuditAction.user_deactivated)
    assert len(deactivate_events) == 1
    assert deactivate_events[0].actor_user_id == admin.id
    assert deactivate_events[0].target_user_id == new_id


async def test_update_while_impersonating_records_real_operator(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # Accountability: an action taken while impersonating must trace back to the
    # real operator via impersonator_user_id (ties to the H1 fix).
    admin = await make_user(email="admin@example.com", is_admin=True)
    other_admin = await make_user(email="eve@example.com", is_admin=True)
    victim = await make_user(email="bob@example.com")
    client = await auth_client(admin)

    assert (
        await client.post(f"/api/v1/admin/users/{other_admin.id}/impersonate")
    ).status_code == 200
    resp = await client.patch(f"/api/v1/admin/users/{victim.id}", json={"first_name": "Bobby"})
    assert resp.status_code == 200

    events = await _events(db_session, AuditAction.user_updated)
    assert len(events) == 1
    assert events[0].actor_user_id == other_admin.id  # the impersonated session identity
    assert events[0].impersonator_user_id == admin.id  # the real operator behind it
    assert events[0].target_user_id == victim.id
    assert events[0].detail == "first_name"


async def test_update_both_names_records_both_in_detail(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # Changing both name fields records them both in the audit detail, in order.
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="bob@example.com", first_name="Bob", last_name="Old")
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{member.id}", json={"first_name": "Bobby", "last_name": "New"}
    )
    assert resp.status_code == 200

    events = await _events(db_session, AuditAction.user_updated)
    assert len(events) == 1
    assert events[0].detail == "first_name,last_name"


async def test_failed_mutation_is_not_audited(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    other = await make_user(email="taken@example.com")
    client = await auth_client(admin)

    # Self-demote is blocked (400) before any audit event is recorded.
    resp = await client.patch(f"/api/v1/admin/users/{admin.id}", json={"is_admin": False})
    assert resp.status_code == 400
    assert await _events(db_session, AuditAction.user_updated) == []

    # 404 target: no user_updated row.
    resp = await client.patch("/api/v1/admin/users/999999", json={"first_name": "Ghost"})
    assert resp.status_code == 404
    assert await _events(db_session, AuditAction.user_updated) == []

    # 409 duplicate email on create: no user_created row.
    resp = await client.post(
        "/api/v1/admin/users",
        json={
            "email": other.email,
            "first_name": "Dup",
            "last_name": "Licate",
            "password": "password12345",
            "is_admin": False,
        },
    )
    assert resp.status_code == 409
    assert await _events(db_session, AuditAction.user_created) == []


async def test_password_update_is_audited_without_leaking_value(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    target = await make_user(email="bob@example.com")
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"password": "a-brand-new-password"}
    )
    assert resp.status_code == 200

    events = await _events(db_session, AuditAction.user_updated)
    assert len(events) == 1
    assert events[0].detail == "password"
    assert "a-brand-new-password" not in (events[0].detail or "")


async def test_logout_while_impersonating_records_operator(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    target = await make_user(email="bob@example.com")
    client = await auth_client(admin)

    assert (await client.post(f"/api/v1/admin/users/{target.id}/impersonate")).status_code == 200
    assert (await client.post("/api/v1/auth/logout")).status_code == 204

    events = await _events(db_session, AuditAction.logout)
    assert len(events) == 1
    assert events[0].actor_user_id == target.id  # the impersonated session
    assert events[0].impersonator_user_id == admin.id  # the real operator


async def test_create_and_deactivate_while_impersonating_record_operator(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)
    client = await auth_client(admin)

    assert (await client.post(f"/api/v1/admin/users/{eve.id}/impersonate")).status_code == 200

    created = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "Person",
            "password": "password12345",
            "is_admin": False,
        },
    )
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert (await client.delete(f"/api/v1/admin/users/{new_id}")).status_code == 204

    create_events = await _events(db_session, AuditAction.user_created)
    assert len(create_events) == 1
    assert create_events[0].actor_user_id == eve.id
    assert create_events[0].impersonator_user_id == admin.id

    deactivate_events = await _events(db_session, AuditAction.user_deactivated)
    assert len(deactivate_events) == 1
    assert deactivate_events[0].actor_user_id == eve.id
    assert deactivate_events[0].impersonator_user_id == admin.id


async def test_a_newline_in_detail_cannot_forge_a_log_record(
    db_session: AsyncSession, caplog
) -> None:
    """The audit log is one record per line, so a CR or LF in `detail` could otherwise append
    a second, plausible-looking record - `audit action=login_success actor=1 ...`.

    Most callers pass something the app produced or pydantic validated. Not all: the SSO
    callback's `?error=` is a raw query parameter on an unauthenticated endpoint, and an email
    claim is whatever the identity provider was told. So this is a property of the formatter.
    """
    forged = "x\naudit action=login_success actor=1 target=None impersonator=None ip=1.2.3.4"

    with caplog.at_level("INFO", logger="app.audit"):
        await record_event(db_session, action=AuditAction.login_failed, detail=forged)

    line = next(r.getMessage() for r in caplog.records if r.name == "app.audit")
    assert "\n" not in line
    assert "\\x0a" in line
    # The row keeps the original: a DB column is not line-oriented, so nothing is forgeable
    # there, and truncating what an operator can query would be the worse trade.
    stored = await _events(db_session, AuditAction.login_failed)
    assert stored[0].detail == forged


async def test_ordinary_detail_is_logged_unchanged(db_session: AsyncSession, caplog) -> None:
    # The scrub must not mangle the everyday case, which is an email address or a field list.
    with caplog.at_level("INFO", logger="app.audit"):
        await record_event(
            db_session, action=AuditAction.user_updated, detail="first_name, last_name"
        )

    line = next(r.getMessage() for r in caplog.records if r.name == "app.audit")
    assert "detail=first_name, last_name" in line
