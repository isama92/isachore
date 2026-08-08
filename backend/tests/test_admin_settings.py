from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.models import User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


# --- read ---------------------------------------------------------------


async def test_read_settings_defaults(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/settings")

    assert resp.status_code == 200
    assert resp.json() == {
        "require_confirmation": False,
        "smtp_configured": False,
        "smtp_host": None,
        "smtp_port": 587,
        "smtp_from": None,
        "oidc_configured": False,
        "oidc_provider_name": "SSO",
        "oidc_issuer": None,
        "oidc_client_id": None,
        # Derived from app_base_url, so it is reported even with no provider set: it is
        # the value an operator registers with the provider *before* filling the rest in.
        "oidc_redirect_uri": "http://localhost:5173/api/v1/auth/oidc/callback",
        "oidc_only": False,
    }


async def test_read_settings_reports_smtp_configured(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/settings")
    body = resp.json()
    assert body["smtp_configured"] is True
    assert body["smtp_host"] == "mailpit"
    assert body["smtp_port"] == 587
    assert body["smtp_from"] == "isachore <no-reply@example.com>"


async def test_read_settings_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 403


async def test_read_settings_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 401


# --- update -------------------------------------------------------------


async def test_enable_confirmation_without_smtp_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/admin/settings", json={"require_confirmation": True})
    assert resp.status_code == 400
    assert "SMTP" in resp.json()["detail"]


async def test_enable_confirmation_with_smtp(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/admin/settings", json={"require_confirmation": True})
    assert resp.status_code == 200
    assert resp.json()["require_confirmation"] is True

    # Persisted across requests.
    again = await client.get("/api/v1/admin/settings")
    assert again.json()["require_confirmation"] is True


async def test_disable_confirmation_allowed_without_smtp(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch("/api/v1/admin/settings", json={"require_confirmation": False})
    assert resp.status_code == 200
    assert resp.json()["require_confirmation"] is False


async def test_update_settings_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.patch("/api/v1/admin/settings", json={"require_confirmation": True})
    assert resp.status_code == 403


# --- test email ---------------------------------------------------------


async def test_test_email_without_smtp_rejected(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.post("/api/v1/admin/settings/test-email")
    assert resp.status_code == 400


async def test_test_email_sends_to_admin(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post("/api/v1/admin/settings/test-email")

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

    resp = await client.post("/api/v1/admin/settings/test-email")
    assert resp.status_code == 502


async def test_test_email_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.post("/api/v1/admin/settings/test-email")
    assert resp.status_code == 403


# --- test email cooldown -------------------------------------------------


async def test_test_email_cooldown_blocks_second_send(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    first = await client.post("/api/v1/admin/settings/test-email")
    assert first.status_code == 204

    # A second send inside the window is refused before another mail goes out.
    second = await client.post("/api/v1/admin/settings/test-email")
    assert second.status_code == 429
    assert 0 < int(second.headers["Retry-After"]) <= settings.test_email_cooldown
    assert len(smtp) == 1


async def test_test_email_cooldown_is_per_admin(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin_a = await make_user(email="admin-a@example.com", is_admin=True)
    admin_b = await make_user(email="admin-b@example.com", is_admin=True)

    client = await auth_client(admin_a)
    assert (await client.post("/api/v1/admin/settings/test-email")).status_code == 204

    # A different admin has their own cooldown, so their first send still works.
    client = await auth_client(admin_b)
    assert (await client.post("/api/v1/admin/settings/test-email")).status_code == 204
    assert len(smtp) == 2


async def test_test_email_cooldown_fails_open_when_redis_unavailable(
    make_user: Login,
    auth_client: AuthClient,
    smtp: list,
    fake_redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A Redis outage must not disable the diagnostic button: the cooldown skips
    # and back-to-back sends both go through.
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    async def boom(*args: object, **kwargs: object) -> object:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(fake_redis, "set", boom)

    assert (await client.post("/api/v1/admin/settings/test-email")).status_code == 204
    assert (await client.post("/api/v1/admin/settings/test-email")).status_code == 204
    assert len(smtp) == 2


async def test_read_settings_normalises_a_blank_provider_name(
    make_user: Login, auth_client: AuthClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The label an operator reads here must be the label users see on the button.

    `OIDC_PROVIDER_NAME=` is reachable (the name is cosmetic and deliberately outside
    oidc_configured()), and /auth/methods substitutes the default for it, so without the same
    normalisation this page shows an empty cell while the login page reads "Sign in with SSO".
    """
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.example.com/o/isachore/")
    monkeypatch.setattr(settings, "oidc_client_id", "isachore")
    monkeypatch.setattr(settings, "oidc_client_secret", "not-a-real-secret")
    monkeypatch.setattr(settings, "oidc_provider_name", "  ")
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/settings")

    assert resp.json()["oidc_configured"] is True
    assert resp.json()["oidc_provider_name"] == "SSO"


async def test_read_settings_never_exposes_the_client_secret(
    make_user: Login, auth_client: AuthClient, oidc: str
) -> None:
    # Same rule as smtp_password: a derived boolean and the non-secret values, never the
    # credential. Asserted against the whole body rather than a field, so adding a field that
    # happens to carry it fails here too.
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/admin/settings")

    assert "shh-client-secret" not in resp.text
    assert "client_secret" not in resp.text
