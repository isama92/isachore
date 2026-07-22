"""Transport-level request body cap (BodySizeLimitMiddleware).

The middleware guards every route; these tests drive it through the profile
endpoints. The tighter handler-level avatar cap (avatar_max_bytes) keeps its
own tests in test_profile.py.
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models import User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def test_declared_oversize_rejected_up_front(
    make_user: Login, auth_client: AuthClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A body with an honest Content-Length past the cap gets a 413 before any
    of it is read (the junk payload would 400 as an invalid image if it ever
    reached the handler, so the 413 detail pins the middleware as the source)."""
    monkeypatch.setattr(settings, "max_request_bytes", 100)
    user = await make_user()
    client = await auth_client(user)
    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("big.png", b"x" * 200, "image/png")}
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "Request body is too large"


async def test_chunked_oversize_cut_off_mid_stream(
    make_user: Login, auth_client: AuthClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting Content-Length (chunked transfer) must not bypass the cap: the
    stream is cut off as soon as the running total passes it."""
    monkeypatch.setattr(settings, "max_request_bytes", 100)
    user = await make_user()
    client = await auth_client(user)

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * 50

    res = await client.patch(
        "/api/v1/profile",
        content=chunks(),
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "Request body is too large"


async def test_body_exactly_at_cap_passes(
    make_user: Login, auth_client: AuthClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b'{"first_name": "Cap"}'
    monkeypatch.setattr(settings, "max_request_bytes", len(payload))
    user = await make_user()
    client = await auth_client(user)
    res = await client.patch(
        "/api/v1/profile", content=payload, headers={"content-type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Cap"


async def test_oversize_rejected_before_auth(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap sits outside routing and auth, so an anonymous oversized request
    is refused with 413 (not 401) without costing the app anything."""
    monkeypatch.setattr(settings, "max_request_bytes", 100)
    res = await client.patch(
        "/api/v1/profile",
        content=b"x" * 200,
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 413
