"""CsrfProtectMiddleware: cookie-authenticated unsafe requests need X-CSRF-Token.

The base `client` fixture sends the header on every request (mirroring the SPA),
so these tests pop it to exercise the check. See app/core/csrf.py.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import _AUTH_COOKIES
from app.core.security import (
    ADMIN_COOKIE_NAME,
    COOKIE_NAME,
    OIDC_STATE_COOKIE_NAME,
    generate_token,
    hash_token,
)
from app.models import AuthToken, User

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

_PROFILE_PATCH = {"first_name": "Renamed", "last_name": "Person"}


async def _bearer_token(session: AsyncSession, user: User) -> str:
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


async def test_cookie_mutation_without_header_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    user = await make_user()
    client = await auth_client(user)
    del client.headers["X-CSRF-Token"]

    resp = await client.patch("/api/v1/profile", json=_PROFILE_PATCH)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing CSRF header"


async def test_cookie_mutation_with_header_allowed(
    make_user: Login, auth_client: AuthClient
) -> None:
    user = await make_user()
    client = await auth_client(user)  # base client already carries X-CSRF-Token

    resp = await client.patch("/api/v1/profile", json=_PROFILE_PATCH)

    assert resp.status_code == 200


async def test_bearer_mutation_without_header_allowed(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # Scope proof: a Bearer-authenticated request carries no cookie, so it is
    # CSRF-immune and must not be gated even without the header.
    user = await make_user()
    raw = await _bearer_token(db_session, user)
    del client.headers["X-CSRF-Token"]
    client.headers["Authorization"] = f"Bearer {raw}"

    resp = await client.patch("/api/v1/profile", json=_PROFILE_PATCH)

    assert resp.status_code == 200


async def test_safe_method_without_header_allowed(
    make_user: Login, auth_client: AuthClient
) -> None:
    user = await make_user()
    client = await auth_client(user)
    del client.headers["X-CSRF-Token"]

    resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 200


async def test_public_login_without_header_allowed(client: AsyncClient, make_user: Login) -> None:
    # No auth cookie is present on a fresh login, so the check does not fire.
    await make_user(email="alice@example.com")
    del client.headers["X-CSRF-Token"]

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password12345"},
    )

    assert resp.status_code == 200


async def test_empty_header_value_rejected(make_user: Login, auth_client: AuthClient) -> None:
    # A present-but-empty header is falsy, so it counts as missing.
    user = await make_user()
    client = await auth_client(user)
    client.headers["X-CSRF-Token"] = ""

    resp = await client.patch("/api/v1/profile", json=_PROFILE_PATCH)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing CSRF header"


async def test_delete_without_header_rejected(make_user: Login, auth_client: AuthClient) -> None:
    # DELETE is gated like every other unsafe method (rejected before the route
    # runs, so no avatar needs to exist).
    user = await make_user()
    client = await auth_client(user)
    del client.headers["X-CSRF-Token"]

    resp = await client.delete("/api/v1/profile/avatar")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing CSRF header"


async def test_multipart_put_without_header_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    # The avatar upload path (PUT multipart) is gated too; the check runs before
    # the body is read, so an empty body still gets the 403.
    user = await make_user()
    client = await auth_client(user)
    del client.headers["X-CSRF-Token"]

    resp = await client.put("/api/v1/profile/avatar")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing CSRF header"


async def test_admin_cookie_alone_triggers_the_gate(client: AsyncClient) -> None:
    # isachore_admin_token counts as an auth cookie, so it gates even without the
    # primary session cookie. The value need not be valid: the CSRF check runs
    # before authentication.
    del client.headers["X-CSRF-Token"]
    client.cookies.set("isachore_admin_token", "whatever")

    resp = await client.post("/api/v1/auth/stop-impersonating")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing CSRF header"


async def test_two_factor_cookie_is_exempt(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # The 2FA challenge cookie is deliberately NOT treated as a session cookie, so
    # a verify-2fa POST carrying only it is not gated by CSRF (it is gated by the
    # secret TOTP code instead). It fails later for a bad code, never with 403.
    user = await make_user()
    raw = await _bearer_token(db_session, user)  # any opaque value in the cookie
    del client.headers["X-CSRF-Token"]
    client.cookies.set("isachore_2fa", raw)

    resp = await client.post("/api/v1/auth/verify-2fa", json={"code": "123456"})

    assert resp.status_code != 403


def test_the_oidc_state_cookie_is_not_treated_as_a_session_cookie() -> None:
    """`isachore_oidc` must stay out of `_AUTH_COOKIES`: it authenticates nobody, so it must
    not turn an anonymous request into one the middleware reads as a session.

    Asserted structurally rather than through a request, which is the exception here and worth
    knowing why. The sibling rule about `isachore_2fa` gets a behavioural test (see above)
    because `verify-2fa` is a POST, so the middleware actually inspects it. Both OIDC endpoints
    are GET, and the middleware only looks at unsafe methods - so adding the cookie to that
    tuple changes no response today and no behavioural test can catch it. The reason the rule
    still holds is that it survives a change of method, and this is what keeps it from being
    quietly undone in the meantime: a closed-set assertion, like
    `test_every_role_is_on_the_ladder`.
    """
    assert OIDC_STATE_COOKIE_NAME not in _AUTH_COOKIES
    # ...and the positive half, so this cannot pass by the tuple being empty or renamed.
    assert _AUTH_COOKIES == (COOKIE_NAME, ADMIN_COOKIE_NAME)
