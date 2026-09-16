"""Personal access tokens: the credential, its management surface, and the gate.

The gate is the part worth reading carefully. An access token is deliberately NOT a
second way to be the user: it reaches the 22 operations that publish the `apiToken`
scheme and answers 403 everywhere else. That those 22 and no others carry it is pinned
structurally, from the generated document, by tests/test_openapi_security.py; what is
pinned here is the behaviour on both sides of the line, and the difference between
"a real token, not usable here" (403) and "a string that authenticates nothing" (401).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_tokens import API_TOKEN_PREFIX
from app.core.security import hash_token
from app.models import ApiToken, AuditAction, AuditEvent, AuthToken, Household, User, UserStatus

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]
ApiClient = Callable[[User], Awaitable[AsyncClient]]
MakeApiToken = Callable[[User], Awaitable[str]]
MakeHousehold = Callable[..., Awaitable[Household]]

URL = "/api/v1/profile/api-token"
PASSWORD = "password12345"

# The exact sentence get_current_user raises, so a test cannot pass on somebody else's
# 403. app/api/deps.py is the only place it is written.
TOKEN_REFUSED = (
    "A personal access token cannot be used here. This operation needs a signed-in "
    "session; the ones an access token may call are those listed with the apiToken "
    "scheme in the API reference."
)


async def _token_rows(session: AsyncSession, user_id: int) -> int:
    """Takes an id, not a User. The handler's own rollback on the 409 path expires every
    instance in the shared test session, so reading `user.id` afterwards would attempt IO
    from outside the greenlet rather than count anything."""
    return (
        await session.scalar(
            select(func.count()).select_from(ApiToken).where(ApiToken.user_id == user_id)
        )
    ) or 0


async def _events(session: AsyncSession, action: AuditAction) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
    )
    return list(result.scalars())


# --------------------------------------------------------------------------- GET


async def test_get_reports_no_token_when_none_exists(
    make_user: Login, auth_client: AuthClient
) -> None:
    client = await auth_client(await make_user())

    resp = await client.get(URL)

    assert resp.status_code == 200
    assert resp.json() == {"token": None}


async def test_get_reports_the_token_without_ever_returning_it(
    make_user: Login, auth_client: AuthClient, make_api_token: MakeApiToken
) -> None:
    """The "shown once" promise, asserted at the surface that would break it.

    Weaker than it looks, and worth saying so: nothing server-side holds the plaintext, so
    no one-line edit can make this fail. It guards a LATER change - a column, a schema
    field - rather than the current code, where "shown once" is already unrepresentable.
    """
    user = await make_user()
    raw = await make_api_token(user)
    client = await auth_client(user)

    resp = await client.get(URL)

    assert resp.status_code == 200
    assert resp.json()["token"]["created_at"] is not None
    assert raw not in resp.text
    assert API_TOKEN_PREFIX not in resp.text


async def test_get_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


# -------------------------------------------------------------------------- POST


async def test_post_returns_the_token_once_and_stores_only_its_hash(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(password=PASSWORD)
    client = await auth_client(user)

    resp = await client.post(URL, json={"current_password": PASSWORD})

    assert resp.status_code == 201
    raw = resp.json()["token"]
    assert raw.startswith(API_TOKEN_PREFIX)
    row = await db_session.scalar(select(ApiToken).where(ApiToken.user_id == user.id))
    assert row is not None
    assert row.token_hash != raw
    # Over the WHOLE string, prefix included. Hash the suffix only and this fails,
    # which is the mutation that would otherwise pass every behavioural test here.
    assert row.token_hash == hash_token(raw)


async def test_post_rejects_a_wrong_current_password(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(password=PASSWORD)
    user_id = user.id
    client = await auth_client(user)

    resp = await client.post(URL, json={"current_password": "not-the-password"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Current password is incorrect"
    # Without this the test would also pass on a handler that mints first and checks
    # after, which is the failure the password check exists to prevent.
    assert await _token_rows(db_session, user_id) == 0


async def test_post_rejects_a_missing_current_password(
    make_user: Login, auth_client: AuthClient
) -> None:
    """A 400 rather than a 422, which is what typing current_password as optional buys:
    one refusal shape for "wrong password" and "no password"."""
    client = await auth_client(await make_user(password=PASSWORD))

    resp = await client.post(URL, json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Current password is incorrect"


async def test_post_never_echoes_the_rejected_password(
    make_user: Login, auth_client: AuthClient
) -> None:
    client = await auth_client(await make_user(password=PASSWORD))

    resp = await client.post(URL, json={"current_password": "hunter2-wrong"})

    assert "hunter2-wrong" not in resp.text


async def test_post_refuses_a_second_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    user = await make_user(password=PASSWORD)
    user_id = user.id
    first = await make_api_token(user)
    client = await auth_client(user)

    resp = await client.post(URL, json={"current_password": PASSWORD})

    assert resp.status_code == 409
    assert "Delete it before generating a new one." in resp.json()["detail"]
    assert await _token_rows(db_session, user_id) == 1
    # Without this the 409 could be a destructive no-op that killed the existing token
    # on the way to refusing.
    assert await db_session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(first)))


async def test_post_requires_a_session(client: AsyncClient) -> None:
    assert (await client.post(URL, json={"current_password": PASSWORD})).status_code == 401


async def test_post_refuses_a_personal_access_token(
    make_user: Login, api_client: ApiClient, db_session: AsyncSession
) -> None:
    """A token cannot mint a token. The password must be CORRECT here, or the 400 would
    satisfy nothing about the credential type."""
    user = await make_user(password=PASSWORD)
    user_id = user.id
    client = await api_client(user)

    resp = await client.post(URL, json={"current_password": PASSWORD})

    assert resp.status_code == 403
    assert resp.json()["detail"] == TOKEN_REFUSED
    assert await _token_rows(db_session, user_id) == 1


async def test_post_is_refused_while_impersonating(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    """Impersonation ends; an access token does not. Minting one through an impersonated
    session would turn temporary access to an account into permanent access to it.

    Every other clause is satisfied so only the impersonation can cause the refusal: the
    admin knows the target's password (it is set here), the target holds no token yet, and
    the same request without the parked admin cookie is the happy path above. Delete the
    guard and this answers 201.
    """
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", password=PASSWORD)
    member_id = member.id
    client = await auth_client(admin)
    assert (await client.post(f"/api/v1/admin/users/{member_id}/impersonate")).status_code == 200

    resp = await client.post(URL, json={"current_password": PASSWORD})

    assert resp.status_code == 403
    assert "cannot be generated while impersonating" in resp.json()["detail"]
    assert await _token_rows(db_session, member_id) == 0


# ------------------------------------------------------------------------ DELETE


async def test_delete_revokes_the_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    user_id = user.id
    raw = await make_api_token(user)
    authed = await auth_client(user)

    resp = await authed.delete(URL)

    assert resp.status_code == 204
    assert await _token_rows(db_session, user_id) == 0
    # A row delete is not yet a revocation. This is the half that says so.
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {raw}"
    assert (await client.get("/api/v1/home")).status_code == 401


async def test_delete_without_a_token_is_404(make_user: Login, auth_client: AuthClient) -> None:
    client = await auth_client(await make_user())

    resp = await client.delete(URL)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "You have no access token to delete"


async def test_delete_takes_no_password(
    make_user: Login, auth_client: AuthClient, make_api_token: MakeApiToken
) -> None:
    """Deliberately asymmetric with POST, so the mutation is an addition: require a
    password here and this bare DELETE stops working."""
    user = await make_user(password=PASSWORD)
    await make_api_token(user)
    client = await auth_client(user)

    assert (await client.delete(URL)).status_code == 204


async def test_delete_requires_a_session(client: AsyncClient) -> None:
    assert (await client.delete(URL)).status_code == 401


async def test_delete_refuses_a_personal_access_token(
    make_user: Login, api_client: ApiClient, db_session: AsyncSession
) -> None:
    user = await make_user()
    user_id = user.id
    client = await api_client(user)

    resp = await client.delete(URL)

    assert resp.status_code == 403
    assert resp.json()["detail"] == TOKEN_REFUSED
    assert await _token_rows(db_session, user_id) == 1


# -------------------------------------------------------------------------- gate


async def test_a_token_reaches_the_due_list_as_its_owner(
    make_user: Login,
    make_household: MakeHousehold,
    make_chore: Callable[..., Awaitable[object]],
    api_client: ApiClient,
) -> None:
    """The motivating case. Asserts the payload is the owner's, not merely that the
    request was allowed through."""
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, title="Empty the bins", assignees=[user])
    client = await api_client(user)

    resp = await client.get("/api/v1/home")

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Empty the bins"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/home"),
        ("get", "/api/v1/unscheduled"),
        ("get", "/api/v1/stats"),
        ("get", "/api/v1/logs"),
        ("get", "/api/v1/households"),
        ("get", "/api/v1/tags"),
        ("get", "/api/v1/chores"),
        ("get", "/api/v1/completions"),
        ("get", "/api/v1/completions/filters"),
    ],
)
async def test_a_token_reaches_every_allowlisted_router(
    make_user: Login, make_household: MakeHousehold, api_client: ApiClient, method: str, path: str
) -> None:
    """One read per allowlisted router. What this does NOT cover is that each of the 22
    operations individually carries ApiUser - that is structural, and
    test_openapi_security.py reads it off the generated document instead."""
    user = await make_user()
    await make_household(members=[user])
    client = await api_client(user)

    assert (await getattr(client, method)(path)).status_code == 200


async def test_a_token_may_write_a_tag(
    make_user: Login, make_household: MakeHousehold, api_client: ApiClient
) -> None:
    """The allowlist is not "reads only": chore, tag and completion writes are on it.

    This says nothing about CSRF, though it is an unsafe method: the `client` fixture sends
    `X-CSRF-Token` on every request, so the middleware is satisfied whatever it makes of the
    Authorization header. That property is pinned by test_csrf.py's
    test_api_token_mutation_without_header_allowed, which deletes the header.
    """
    user = await make_user()
    household = await make_household(members=[user])
    client = await api_client(user)

    resp = await client.post(
        "/api/v1/tags", json={"household_id": household.id, "name": "Kitchen", "color": "#3b82f6"}
    )

    assert resp.status_code == 201


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/v1/auth/me", None),
        ("patch", "/api/v1/profile", {"first_name": "Renamed", "last_name": "Person"}),
        ("post", "/api/v1/profile/2fa/setup", {}),
        ("post", "/api/v1/households", {"name": "Somewhere", "timezone": "UTC"}),
    ],
)
async def test_a_token_is_refused_by_a_session_only_route(
    make_user: Login,
    api_client: ApiClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    client = await api_client(await make_user())

    resp = await getattr(client, method)(path, **({"json": body} if body is not None else {}))

    assert resp.status_code == 403
    assert resp.json()["detail"] == TOKEN_REFUSED


async def test_a_token_on_an_admin_route_refuses_the_credential_not_the_role(
    make_user: Login, api_client: ApiClient
) -> None:
    """The user MUST be an administrator. Without that, require_admin's own 403 satisfies
    the status assertion and the test pins nothing at all - which is why the detail is
    asserted too."""
    client = await api_client(await make_user(is_admin=True))

    resp = await client.get("/api/v1/admin/users")

    assert resp.status_code == 403
    assert resp.json()["detail"] == TOKEN_REFUSED


async def test_an_unknown_token_is_401_not_403(make_user: Login, client: AsyncClient) -> None:
    """Route on the prefix alone, without the lookup, and this turns into a 403 that
    tells an attacker their guess had the right shape."""
    await make_user()
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {API_TOKEN_PREFIX}not-a-real-token"

    resp = await client.patch("/api/v1/profile", json={"first_name": "A", "last_name": "B"})

    assert resp.status_code == 401


async def test_a_revoked_token_is_401_not_403(
    make_user: Login, make_api_token: MakeApiToken, client: AsyncClient, db_session: AsyncSession
) -> None:
    """Distinct from the unknown case: "existed and was revoked" and "never existed" are
    the two states a cache or a prefix shortcut would break differently.

    The session-only route is the one that makes the name true. On an allowlisted route a
    403 is unreachable by construction, so asserting 401 there would pin nothing about the
    distinction - it is `PATCH /profile` that can answer either, and answers 401 only
    because the lookup ran and missed.
    """
    user = await make_user()
    raw = await make_api_token(user)
    await db_session.delete(
        await db_session.scalar(select(ApiToken).where(ApiToken.user_id == user.id))
    )
    await db_session.commit()

    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {raw}"

    resp = await client.patch("/api/v1/profile", json={"first_name": "A", "last_name": "B"})
    assert resp.status_code == 401
    assert (await client.get("/api/v1/home")).status_code == 401


async def test_a_session_bearer_still_reaches_an_allowlisted_route(
    make_user: Login, make_household: MakeHousehold, client: AsyncClient, db_session: AsyncSession
) -> None:
    """get_api_user's fallback branch. Nothing else covers it, and losing it would break
    every non-browser client that authenticates with a session token."""
    user = await make_user()
    await make_household(members=[user])
    raw = "session-" + "x" * 20
    db_session.add(
        AuthToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {raw}"

    assert (await client.get("/api/v1/home")).status_code == 200


async def test_a_token_in_the_session_cookie_authenticates_nobody(
    make_user: Login, make_api_token: MakeApiToken, client: AsyncClient
) -> None:
    """Header only, which is what keeps core/csrf.py's reasoning intact.

    Every other clause is satisfied so the 401 can only come from the transport rule: the
    row exists, its owner is active, and /home is an operation that DOES accept access
    tokens. Drop the header-only rule from get_api_user and this answers 200.
    """
    user = await make_user()
    raw = await make_api_token(user)
    client.cookies.set("isachore_token", raw)
    client.headers.pop("Authorization", None)

    assert (await client.get("/api/v1/home")).status_code == 401


# --------------------------------------------------------------------- lifecycle


async def test_a_disabled_user_cannot_use_their_token(
    make_user: Login, api_client: ApiClient, db_session: AsyncSession
) -> None:
    user = await make_user()
    user_id = user.id
    client = await api_client(user)
    user.status = UserStatus.disabled
    await db_session.commit()

    assert (await client.get("/api/v1/home")).status_code == 401
    # The row survives: the status check is the mechanism, not a delete. Assert it, or a
    # future change that deleted instead would pass this test while changing the answer
    # to "what happens when the account is re-enabled".
    assert await _token_rows(db_session, user_id) == 1


async def test_a_self_service_password_change_leaves_the_token_alive(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An omission, so the mechanism has to be live before the absence means anything:
    the OTHER session must actually be revoked, or this would pass on a build where the
    whole wipe is broken."""
    user = await make_user(password=PASSWORD)
    user_id = user.id
    raw = await make_api_token(user)
    other = "other-session-" + "y" * 20
    db_session.add(
        AuthToken(
            token_hash=hash_token(other),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()
    authed = await auth_client(user)

    resp = await authed.patch(
        "/api/v1/profile", json={"current_password": PASSWORD, "new_password": "brand-new-pass"}
    )
    assert resp.status_code == 200

    assert not await db_session.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_token(other))
    )
    assert await _token_rows(db_session, user_id) == 1
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {raw}"
    assert (await client.get("/api/v1/home")).status_code == 200


# --------------------------------------------------------------------- audit


async def test_creating_a_token_is_audited(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(password=PASSWORD)
    client = await auth_client(user)

    assert (await client.post(URL, json={"current_password": PASSWORD})).status_code == 201

    events = await _events(db_session, AuditAction.api_token_created)
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert events[0].target_user_id == user.id
    assert events[0].ip_address == "127.0.0.1"
    # The only field on an audit row a token could end up in.
    assert events[0].detail is None


async def test_a_refused_second_token_is_not_audited(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    """record_event writes its log line the moment it is called, so a handler that
    committed after recording would announce a creation the constraint then refused."""
    user = await make_user(password=PASSWORD)
    await make_api_token(user)
    client = await auth_client(user)

    assert (await client.post(URL, json={"current_password": PASSWORD})).status_code == 409

    assert await _events(db_session, AuditAction.api_token_created) == []


async def test_revoking_a_token_is_audited(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    await make_api_token(user)
    client = await auth_client(user)

    assert (await client.delete(URL)).status_code == 204

    events = await _events(db_session, AuditAction.api_token_revoked)
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert events[0].target_user_id == user.id
    assert events[0].detail is None


# --------------------------------------------------------------- administrators


async def test_an_admin_sees_whether_a_user_holds_a_token_but_never_the_token(
    make_user: Login, auth_client: AuthClient, make_api_token: MakeApiToken
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    raw = await make_api_token(member)
    client = await auth_client(admin)

    resp = await client.get(f"/api/v1/admin/users/{member.id}/api-token")

    assert resp.status_code == 200
    assert resp.json()["token"]["created_at"] is not None
    assert raw not in resp.text


async def test_an_admin_sees_null_for_a_user_with_no_token(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.get(f"/api/v1/admin/users/{member.id}/api-token")

    assert resp.status_code == 200
    assert resp.json() == {"token": None}


async def test_an_admin_revokes_a_users_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Offboarding an integration without disabling the person."""
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    raw = await make_api_token(member)
    authed = await auth_client(admin)

    resp = await authed.delete(f"/api/v1/admin/users/{member.id}/api-token")

    assert resp.status_code == 204
    assert await _token_rows(db_session, member_id) == 0
    events = await _events(db_session, AuditAction.api_token_revoked)
    assert len(events) == 1
    assert events[0].actor_user_id == admin.id
    assert events[0].target_user_id == member.id

    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {raw}"
    assert (await client.get("/api/v1/home")).status_code == 401
    # The account itself is untouched: this revokes a credential, not a person.
    assert member.status == UserStatus.active


async def test_revoking_a_token_a_user_does_not_have_is_404(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.delete(f"/api/v1/admin/users/{member.id}/api-token")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "This user has no access token"


async def test_a_non_admin_cannot_read_or_revoke_somebody_elses_token(
    make_user: Login, auth_client: AuthClient, make_api_token: MakeApiToken
) -> None:
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    await make_api_token(other)
    client = await auth_client(member)

    assert (await client.get(f"/api/v1/admin/users/{other.id}/api-token")).status_code == 403
    assert (await client.delete(f"/api/v1/admin/users/{other.id}/api-token")).status_code == 403


async def test_an_admin_password_reset_revokes_the_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    """The deliberate exception to the token living in a table of its own. An
    administrator resetting somebody's password is the "this account may be compromised"
    lever, and a never-expiring credential surviving it would be a stale way in.

    Contrast test_a_self_service_password_change_leaves_the_token_alive above: the same
    field, changed by its owner, keeps it.
    """
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    await make_api_token(member)
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{member.id}", json={"password": "a-fresh-password"}
    )

    assert resp.status_code == 200
    assert await _token_rows(db_session, member_id) == 0


async def test_an_admin_password_reset_audits_the_revocation(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    """A revocation that happens as a side effect still files its own event, or the trail
    cannot answer "when was this token revoked" for the paths that matter most."""
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    admin_id, member_id = admin.id, member.id
    await make_api_token(member)
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{member_id}", json={"password": "a-fresh-password"}
    )

    assert resp.status_code == 200
    events = await _events(db_session, AuditAction.api_token_revoked)
    assert len(events) == 1
    assert events[0].actor_user_id == admin_id
    assert events[0].target_user_id == member_id


async def test_a_reset_for_a_user_with_no_token_files_no_revocation(
    make_user: Login,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Only on a real delete. Without this the trail fills with revocations of tokens that
    # never existed, and the event stops meaning anything.
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{member_id}", json={"password": "a-fresh-password"}
    )

    assert resp.status_code == 200
    assert await _events(db_session, AuditAction.api_token_revoked) == []


async def test_deactivating_a_user_revokes_the_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    await make_api_token(member)
    client = await auth_client(admin)

    assert (await client.delete(f"/api/v1/admin/users/{member.id}")).status_code == 204

    assert await _token_rows(db_session, member_id) == 0


async def test_resetting_two_factor_leaves_the_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    """A lost authenticator is not a compromise, so reset_two_factor revokes no credential
    for signing in - not sessions, not the access token.

    An omission, so the mutation is an addition: one `await _revoke_tokens(...)` line in that
    handler and this fails. The 2FA state is asserted too, or the test would also pass on a
    build where the reset silently did nothing at all.
    """
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    member.totp_secret = "ciphertext"
    member.totp_enabled = True
    await db_session.commit()
    await make_api_token(member)
    client = await auth_client(admin)

    resp = await client.post(f"/api/v1/admin/users/{member_id}/reset-2fa")

    assert resp.status_code == 200
    assert resp.json()["two_factor_enabled"] is False
    assert await _token_rows(db_session, member_id) == 1


async def test_an_admin_editing_something_other_than_a_password_leaves_the_token(
    make_user: Login,
    auth_client: AuthClient,
    make_api_token: MakeApiToken,
    db_session: AsyncSession,
) -> None:
    """_revoke_tokens is called on a password change, not on every admin edit. Without
    this, the two tests above would also pass on a build that revoked on any PATCH."""
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    member_id = member.id
    await make_api_token(member)
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/admin/users/{member.id}", json={"first_name": "Renamed"})

    assert resp.status_code == 200
    assert await _token_rows(db_session, member_id) == 1
