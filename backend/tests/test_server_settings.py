from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.models import User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


# --- read ---------------------------------------------------------------


async def test_read_settings_defaults(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/settings")

    assert resp.status_code == 200
    assert resp.json() == {"require_confirmation": False, "smtp_configured": False}


async def test_read_settings_reports_smtp_configured(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/settings")
    assert resp.json()["smtp_configured"] is True


async def test_read_settings_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 403


async def test_read_settings_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 401


# --- update -------------------------------------------------------------


async def test_enable_confirmation_without_smtp_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/settings", json={"require_confirmation": True})
    assert resp.status_code == 400
    assert "SMTP" in resp.json()["detail"]


async def test_enable_confirmation_with_smtp(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/settings", json={"require_confirmation": True})
    assert resp.status_code == 200
    assert resp.json()["require_confirmation"] is True

    # Persisted across requests.
    again = await client.get("/api/v1/settings")
    assert again.json()["require_confirmation"] is True


async def test_disable_confirmation_allowed_without_smtp(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/settings", json={"require_confirmation": False})
    assert resp.status_code == 200
    assert resp.json()["require_confirmation"] is False


async def test_update_settings_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.patch("/api/v1/settings", json={"require_confirmation": True})
    assert resp.status_code == 403


# --- test email ---------------------------------------------------------


async def test_test_email_without_smtp_rejected(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.post("/api/v1/settings/test-email")
    assert resp.status_code == 400


async def test_test_email_sends_to_admin(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post("/api/v1/settings/test-email")

    assert resp.status_code == 204
    assert len(smtp) == 1
    assert smtp[0]["To"] == "admin@example.com"


async def test_test_email_send_failure_returns_502(
    make_user: Login, auth_client: AuthClient, smtp: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    async def _boom(*args, **kwargs):
        raise OSError("smtp down")

    # Override the recorder the smtp fixture installed.
    monkeypatch.setattr("aiosmtplib.send", _boom)

    resp = await client.post("/api/v1/settings/test-email")
    assert resp.status_code == 502


async def test_test_email_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.post("/api/v1/settings/test-email")
    assert resp.status_code == 403
