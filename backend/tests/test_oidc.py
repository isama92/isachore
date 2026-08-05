"""Single sign-on: the callback's policy, and ID token verification.

Two halves, and they are tested differently on purpose.

The endpoint tests stub `oidc_core.begin` / `oidc_core.complete`, so what is under test
is the policy - who gets in, who is refused and with which code - without a provider
anywhere near it. That works only because the router calls those two through the module
(see the import comment in api/v1/oidc.py); binding them by name would make every stub
here silently ineffective.

The verification tests do the opposite: they sign real tokens with a real RSA key and run
them through the real `_verify_id_token`, stubbing only the key fetch. Without them every
signature check in this feature would be mocked out, which for the one function standing
between a stranger and a session is not a trade worth making.
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx
import pytest
from httpx import AsyncClient
from joserfc import jwt
from joserfc.jwk import KeySet, OctKey, RSAKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import oidc as oidc_core
from app.core import rate_limit
from app.core.app_settings import get_app_settings
from app.core.config import settings
from app.core.oidc import OidcError, OidcIdentity
from app.core.security import OIDC_STATE_COOKIE_NAME, generate_token, hash_token
from app.models import (
    AuditAction,
    AuditEvent,
    AuthToken,
    ConfirmationToken,
    OidcLoginState,
    User,
    UserStatus,
)

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

ISSUER = "https://idp.example.com/application/o/isachore"


# --- helpers ------------------------------------------------------------


def stub_begin(
    monkeypatch: pytest.MonkeyPatch, *, url: str = "https://idp.example.com/auth"
) -> None:
    """Make `begin` hand back a fixed url, nonce and verifier with no network."""

    async def _begin(*, state: str) -> tuple[str, str, str]:
        return f"{url}?state={state}", "test-nonce", "test-code-verifier"

    monkeypatch.setattr(oidc_core, "begin", _begin)


def stub_complete(
    monkeypatch: pytest.MonkeyPatch,
    *,
    subject: str = "subject-1",
    email: str | None = "member@example.com",
    issuer: str = ISSUER,
    error: str | None = None,
) -> dict:
    """Make `complete` report a given identity, and record what it was called with."""
    seen: dict = {}

    async def _complete(*, code: str, code_verifier: str, nonce: str) -> OidcIdentity:
        seen.update(code=code, code_verifier=code_verifier, nonce=nonce)
        if error is not None:
            raise OidcError(error)
        return OidcIdentity(subject=subject, issuer=issuer, email=email)

    monkeypatch.setattr(oidc_core, "complete", _complete)
    return seen


async def start_flow(client: AsyncClient, *, return_to: str | None = None) -> str:
    """Run GET /start and return the raw state, leaving its cookie on the client."""
    params = {} if return_to is None else {"return_to": return_to}
    resp = await client.get("/api/v1/auth/oidc/start", params=params, follow_redirects=False)
    assert resp.status_code == 302
    return client.cookies[OIDC_STATE_COOKIE_NAME]


async def callback(client: AsyncClient, state: str, *, code: str = "the-code") -> object:
    return await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def sso_error(response) -> str | None:
    """The sso_error code from a redirect back to the login page."""
    location = response.headers["location"]
    if "sso_error=" not in location:
        return None
    return location.split("sso_error=")[1].split("&")[0]


# --- /auth/methods ------------------------------------------------------


async def test_methods_reports_password_only_by_default(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/methods")

    assert resp.status_code == 200
    assert resp.json() == {
        "password_enabled": True,
        "oidc_enabled": False,
        "oidc_provider_name": None,
    }


async def test_methods_reports_the_provider_name(client: AsyncClient, oidc: str) -> None:
    resp = await client.get("/api/v1/auth/methods")

    assert resp.json() == {
        "password_enabled": True,
        "oidc_enabled": True,
        "oidc_provider_name": "Authentik",
    }


async def test_methods_hides_password_under_oidc_only(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "oidc_only", True)

    resp = await client.get("/api/v1/auth/methods")

    assert resp.json()["password_enabled"] is False
    assert resp.json()["oidc_enabled"] is True


async def test_methods_keeps_password_when_oidc_only_has_no_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OIDC_ONLY with nothing configured must not hide the only working way in.

    The startup check refuses that combination outside a dev environment, but dev is
    exempt from every startup check, so the endpoint has to hold the line itself.
    """
    monkeypatch.setattr(settings, "oidc_only", True)

    resp = await client.get("/api/v1/auth/methods")

    assert resp.json() == {
        "password_enabled": True,
        "oidc_enabled": False,
        "oidc_provider_name": None,
    }


# --- OIDC_ONLY and password login ---------------------------------------


async def test_password_login_is_refused_under_oidc_only(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(email="member@example.com", password="password12345")
    monkeypatch.setattr(settings, "oidc_only", True)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password12345"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Password sign-in is disabled on this server"


async def test_password_login_still_works_when_oidc_only_has_no_provider(
    client: AsyncClient, make_user: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other clause of that condition: the flag alone must not lock anyone out.

    Deliberately does NOT use the `oidc` fixture, which is the whole point - with a
    provider configured this same request is a 403 (the test above), so this is what
    proves the second clause is load-bearing rather than decorative.
    """
    await make_user(email="member@example.com", password="password12345")
    monkeypatch.setattr(settings, "oidc_only", True)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password12345"},
    )

    assert resp.status_code == 200


# --- /start -------------------------------------------------------------


async def test_start_is_404_without_a_provider(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)

    assert resp.status_code == 404


async def test_start_redirects_and_parks_the_flow(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_begin(monkeypatch)

    resp = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)

    assert resp.status_code == 302
    state = client.cookies[OIDC_STATE_COOKIE_NAME]
    # The state travels in the url as well as the cookie; requiring both to match on the
    # way back is the browser binding.
    assert f"state={state}" in resp.headers["location"]

    rows = (await db_session.execute(select(OidcLoginState))).scalars().all()
    assert len(rows) == 1
    # Only the hash is stored, like every other short-lived token in this codebase.
    assert rows[0].state_hash == hash_token(state)
    assert rows[0].state_hash != state
    assert rows[0].nonce == "test-nonce"
    assert rows[0].code_verifier == "test-code-verifier"


async def test_start_keeps_a_relative_return_to(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_begin(monkeypatch)

    await start_flow(client, return_to="/chores?page=2")

    row = (await db_session.execute(select(OidcLoginState))).scalar_one()
    assert row.return_to == "/chores?page=2"


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "/\\evil.example",
        "http://evil.example",
        "chores",
        # Over-long: the column holds 255, and Postgres would refuse the insert with a
        # DataError - a 500 out of an unauthenticated endpoint. Dropped rather than
        # truncated, because a truncated path is a different path.
        "/" + "a" * 300,
    ],
)
async def test_start_drops_a_non_relative_return_to(
    client: AsyncClient,
    db_session: AsyncSession,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
    hostile: str,
) -> None:
    """The open-redirect guard. A signed-in visitor must never be handed to another origin."""
    stub_begin(monkeypatch)

    await start_flow(client, return_to=hostile)

    row = (await db_session.execute(select(OidcLoginState))).scalar_one()
    assert row.return_to is None


async def test_start_reports_an_unreachable_provider(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _begin(*, state: str):
        raise OidcError("provider down")

    monkeypatch.setattr(oidc_core, "begin", _begin)

    resp = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)

    assert resp.status_code == 302
    assert sso_error(resp) == "provider"


# --- /callback: the happy paths -----------------------------------------


async def test_callback_links_by_email_and_opens_a_session(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    seen = stub_complete(monkeypatch, subject="subject-1", email="member@example.com")
    state = await start_flow(client)

    resp = await callback(client, state)

    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/"
    # The session cookie is set, so the SPA's cold boot finds a session on arrival.
    assert client.cookies.get("isachore_token")

    # The flow's own secrets came from the parked row, not the browser.
    assert seen == {
        "code": "the-code",
        "code_verifier": "test-code-verifier",
        "nonce": "test-nonce",
    }

    await db_session.refresh(user)
    assert user.oidc_subject == "subject-1"
    assert user.oidc_issuer == ISSUER
    tokens = (
        (await db_session.execute(select(AuthToken).where(AuthToken.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(tokens) == 1


async def test_callback_honours_a_stored_return_to(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client, return_to="/chores?page=2")

    resp = await callback(client, state)

    assert resp.headers["location"] == "http://localhost:5173/chores?page=2"


async def test_callback_matches_a_linked_subject_after_the_email_changes(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable half of the linking rule.

    Email finds the account the first time only. Once linked, a sign-in matches on the
    provider's subject, so somebody who changes their address at the provider keeps their
    account instead of being told no account exists.
    """
    user = await make_user(email="member@example.com")
    user.oidc_subject = "subject-1"
    user.oidc_issuer = ISSUER
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch, subject="subject-1", email="renamed@example.com")
    state = await start_flow(client)

    resp = await callback(client, state)

    assert resp.status_code == 302
    assert sso_error(resp) is None
    assert client.cookies.get("isachore_token")
    await db_session.refresh(user)
    # The local address is not overwritten from the provider: this app owns it.
    assert user.email == "member@example.com"


async def test_a_subject_from_another_issuer_does_not_match(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issuer half of the identity lookup, isolated.

    `sub` is only promised unique *per issuer*, so this is the cross-provider collision the
    two-column key exists for: an account is linked as (some other issuer, "subject-1"), and
    an identity arrives with the SAME subject from the configured issuer, claiming a
    different person's address.

    Correct behaviour is that the lookup misses, so the callback falls back to matching on
    email and links the *right* account. Drop `User.oidc_issuer == identity.issuer` from
    `_find_linked_user` and it signs in as the wrong person instead.
    """
    other = await make_user(email="other@example.com")
    other.oidc_subject = "subject-1"
    other.oidc_issuer = "https://a-different-idp.example.com/application/o/isachore"
    mine = await make_user(email="member@example.com")
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch, subject="subject-1", email="member@example.com", issuer=ISSUER)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) is None
    me = await client.get("/api/v1/auth/me")
    assert me.json()["email"] == "member@example.com"

    await db_session.refresh(mine)
    await db_session.refresh(other)
    # The colliding subject is now held twice, once per issuer, which the unique constraint
    # permits precisely because it spans the pair.
    assert (mine.oidc_issuer, mine.oidc_subject) == (ISSUER, "subject-1")
    assert other.oidc_subject == "subject-1"


async def test_callback_skips_two_factor(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    totp: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider sign-in does not re-challenge for a local TOTP code.

    The provider owns authentication, including whatever MFA it enforces. Password
    sign-in for this same account still demands the code, which is what makes this a
    policy about SSO rather than a hole in 2FA.
    """
    user = await make_user(email="member@example.com")
    user.totp_enabled = True
    user.totp_secret = "irrelevant-here"
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert resp.status_code == 302
    assert sso_error(resp) is None
    # A real session, not a 2FA challenge.
    assert client.cookies.get("isachore_token")
    assert client.cookies.get("isachore_2fa") is None


async def test_callback_activates_a_user_awaiting_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user(
        email="member@example.com", status=UserStatus.waiting_confirmation, confirmed_at=None
    )
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert resp.status_code == 302
    assert sso_error(resp) is None
    await db_session.refresh(user)
    assert user.status == UserStatus.active
    assert user.confirmed_at is not None


async def test_callback_records_a_successful_sign_in(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    await callback(client, state)

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.login_success)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    # Reused action, SSO distinguished by the detail: audit_events.action is a native
    # Postgres enum, so a new member would need an ALTER TYPE.
    assert events[0].detail == "oidc"


# --- /callback: the refusals --------------------------------------------


async def test_callback_refuses_an_unknown_email(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No self-registration, here as everywhere else."""
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, email="stranger@example.com")
    state = await start_flow(client)

    resp = await callback(client, state)

    assert resp.status_code == 302
    assert sso_error(resp) == "no_account"
    assert client.cookies.get("isachore_token") is None
    # Nothing was created for them.
    assert (await db_session.execute(select(User))).scalars().all() == []


async def test_callback_refuses_when_the_provider_sends_no_email(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts the *reason*, not just the code, because the code alone pins nothing.

    Delete the `if not identity.email:` guard and execution falls through to
    `WHERE email IS NULL`, which matches no row in a NOT NULL column, so the handler answers
    the very same `no_account`. Only the audit detail tells the two apart.
    """
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, email=None)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "no_account"
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.login_failed)
            )
        )
        .scalars()
        .all()
    )
    assert [e.detail for e in events] == ["oidc no email claim"]


async def test_callback_refuses_a_disabled_account(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deactivation is a real soft delete; the provider does not overrule it."""
    await make_user(email="member@example.com", status=UserStatus.disabled)
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "account_disabled"
    assert client.cookies.get("isachore_token") is None


async def test_callback_refuses_an_address_linked_to_another_identity(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account-takeover guard.

    An address already linked to one external identity must not be re-linked to a
    different one just because a provider claims the same email.
    """
    user = await make_user(email="member@example.com")
    user.oidc_subject = "the-original"
    user.oidc_issuer = ISSUER
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch, subject="an-impostor", email="member@example.com")
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "already_linked"
    assert client.cookies.get("isachore_token") is None
    await db_session.refresh(user)
    assert user.oidc_subject == "the-original"


async def test_the_same_subject_from_the_configured_issuer_re_links(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolates the `!= identity.subject` half of the already-linked guard.

    An account linked to an OLD issuer under the same subject value is matched by email, and
    the incoming subject equals the stored one - so the guard must NOT fire and the row must
    be re-pointed at the configured issuer. This is the repoint-the-provider case CLAUDE.md
    says re-links; make the guard unconditional and it refuses instead.
    """
    user = await make_user(email="member@example.com")
    user.oidc_subject = "subject-1"
    user.oidc_issuer = "https://the-old-idp.example.com/application/o/isachore"
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch, subject="subject-1", email="member@example.com", issuer=ISSUER)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) is None
    await db_session.refresh(user)
    assert user.oidc_issuer == ISSUER


async def test_activating_an_account_revokes_its_confirmation_link(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activating through SSO must kill the outstanding emailed link, as every other path
    that activates or re-secures an account does.

    `POST /confirm/{token}` has no status guard: it sets a password and signs in. So an
    account activated here while its link is still live can be taken over for up to the
    token's TTL by whoever holds that email - an old address, a shared inbox, a mail archive,
    which is exactly the situation that makes SSO activation useful in the first place.
    """
    user = await make_user(
        email="member@example.com", status=UserStatus.waiting_confirmation, confirmed_at=None
    )
    raw = generate_token()
    db_session.add(
        ConfirmationToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)
    assert sso_error(await callback(client, state)) is None

    await db_session.refresh(user)
    assert user.status == UserStatus.active
    left = (await db_session.execute(select(ConfirmationToken))).scalars().all()
    assert left == []
    # ...and the link really is dead, not merely orphaned.
    used = await client.post(f"/api/v1/confirm/{raw}", json={"password": "a-new-password"})
    assert used.status_code == 404


async def test_an_active_account_keeps_its_pending_link(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revocation belongs to the activation branch and only to it.

    An already-active account holding a confirmation token (an admin re-sent one, say) must
    keep it: signing in through the provider is not a reason to invalidate a link somebody
    was about to use. Give the token to an active user, so lifting the delete out of the
    `waiting_confirmation` branch is what this test catches.
    """
    user = await make_user(email="member@example.com")
    db_session.add(
        ConfirmationToken(
            token_hash=hash_token(generate_token()),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    assert sso_error(await callback(client, state)) is None

    await db_session.refresh(user)
    assert user.status == UserStatus.active
    survivors = (await db_session.execute(select(ConfirmationToken))).scalars().all()
    assert len(survivors) == 1


async def test_callback_refuses_a_failed_verification(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, error="id_token did not verify")
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "provider"
    assert client.cookies.get("isachore_token") is None


async def test_callback_refuses_a_provider_error(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_begin(monkeypatch)
    state = await start_flow(client)

    resp = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )

    assert sso_error(resp) == "provider"


# --- /callback: state handling ------------------------------------------


async def test_callback_refuses_without_a_state_cookie(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Login CSRF: an attacker's own flow, fed to a victim's browser.

    Every other clause is satisfied here - a real parked row, a real code, a resolvable
    account - so the only thing refusing is the missing cookie.
    """
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)
    client.cookies.delete(OIDC_STATE_COOKIE_NAME)

    resp = await callback(client, state)

    assert sso_error(resp) == "state"
    assert client.cookies.get("isachore_token") is None


async def test_callback_refuses_a_state_that_is_not_this_browsers(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Login CSRF, and the ONLY test that isolates the cookie-versus-parameter comparison.

    Every other clause is satisfied deliberately: the state handed to the callback belongs
    to a real, live, unexpired row, and the browser does carry a state cookie - just a
    different flow's. So the `not cookie` clause and the row lookup both pass, and the
    comparison is the only thing left that can refuse.

    Without it, an attacker starts a flow, keeps its state, and feeds the victim that
    callback url; the victim's browser (mid-flow of its own) completes it and lands in the
    attacker's session.
    """
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)

    attacker_state = await start_flow(client)
    # A second flow overwrites the cookie, leaving the first row live but unclaimable.
    victim_state = await start_flow(client)
    assert attacker_state != victim_state
    assert client.cookies[OIDC_STATE_COOKIE_NAME] == victim_state

    resp = await callback(client, attacker_state)

    assert sso_error(resp) == "state"
    assert client.cookies.get("isachore_token") is None


async def test_callback_refuses_a_flow_with_no_code(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolates the `not code` clause: a real live flow, a matching cookie, no `code`.

    Its neighbour (`test_callback_refuses_a_provider_error`) satisfies the earlier `if error:`
    branch instead, so without this one the clause could be deleted and `complete(code=None)`
    would be called with the suite still green.
    """
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    called: dict = {}

    async def _complete(**kwargs: object) -> OidcIdentity:
        called["yes"] = True
        raise AssertionError("complete must not be reached without a code")

    monkeypatch.setattr(oidc_core, "complete", _complete)
    state = await start_flow(client)

    resp = await client.get(
        "/api/v1/auth/oidc/callback", params={"state": state}, follow_redirects=False
    )

    assert sso_error(resp) == "state"
    assert called == {}


async def test_callback_refuses_a_state_matching_no_row(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: a parameter that equals the cookie but resolves to nothing.

    Set both sides to the same unknown value, so the comparison passes and only the row
    lookup can refuse.
    """
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    client.cookies.set(OIDC_STATE_COOKIE_NAME, "never-issued")

    resp = await callback(client, "never-issued")

    assert sso_error(resp) == "state"
    assert client.cookies.get("isachore_token") is None


async def test_callback_cannot_be_replayed(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is deleted on use, so a captured callback url is worth nothing twice."""
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    first = await callback(client, state)
    assert sso_error(first) is None

    # Put the state cookie back, so the only thing missing is the consumed row.
    client.cookies.set(OIDC_STATE_COOKIE_NAME, state)
    second = await callback(client, state)

    assert sso_error(second) == "state"


async def test_callback_refuses_an_expired_flow(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    row = (await db_session.execute(select(OidcLoginState))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    resp = await callback(client, state)

    assert sso_error(resp) == "state"


async def test_callback_is_404_without_a_provider(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "x", "state": "y"},
        follow_redirects=False,
    )

    assert resp.status_code == 404


# --- throttling ---------------------------------------------------------


async def test_the_callback_is_throttled_per_ip(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_ip_max_attempts", 2)
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, email="stranger@example.com")

    for _ in range(2):
        state = await start_flow(client)
        assert sso_error(await callback(client, state)) == "no_account"

    state = await start_flow(client)
    resp = await callback(client, state)

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_starting_a_flow_is_throttled_per_ip(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/start` is unauthenticated and writes a row per call, so it needs its own bound.

    Its counter is separate from the callback's on purpose: this one counts every start,
    successes included, so its ceiling has to sit far above anything a shared office NAT
    produces - which is also why the ceiling is monkeypatched here rather than reached.
    """
    monkeypatch.setattr(rate_limit, "_OIDC_START_MAX_ATTEMPTS", 2)
    stub_begin(monkeypatch)

    for _ in range(2):
        resp = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)
        assert resp.status_code == 302

    refused = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)

    assert refused.status_code == 429
    assert "Retry-After" in refused.headers
    # And the refusal wrote nothing, which is the point of bounding it.
    rows = (await db_session.execute(select(OidcLoginState))).scalars().all()
    assert len(rows) == 2


async def test_the_start_throttle_is_separate_from_the_callback_throttle(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed callbacks must not spend a legitimate user's budget for starting flows.

    Reuse the callback's counter here and a handful of refusals (a misconfigured provider,
    say) would stop the same person from retrying at all.
    """
    monkeypatch.setattr(settings, "login_ip_max_attempts", 1)
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, email="stranger@example.com")

    state = await start_flow(client)
    assert sso_error(await callback(client, state)) == "no_account"

    # The callback's own counter is now spent...
    exhausted = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert exhausted.status_code == 429
    # ...while starting a fresh flow still works.
    assert (await client.get("/api/v1/auth/oidc/start", follow_redirects=False)).status_code == 302


async def test_a_failed_callback_records_the_attempt(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, email="stranger@example.com")
    state = await start_flow(client)

    await callback(client, state)

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.login_failed)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].actor_user_id is None
    assert events[0].detail == "oidc no account stranger@example.com"


# --- ID token verification, against real signatures ---------------------


@pytest.fixture
def signing_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "kid-1"}, private=True)


@pytest.fixture
def metadata() -> dict:
    return {
        "issuer": ISSUER,
        "jwks_uri": f"{ISSUER}/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def make_id_token(key: RSAKey, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": "isachore-client",
        "exp": now + 300,
        "iat": now,
        "nonce": "the-nonce",
        "email": "member@example.com",
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": key.kid}, claims, key)


def stub_key_set(monkeypatch: pytest.MonkeyPatch, *keys: RSAKey) -> None:
    key_set = KeySet.import_key_set({"keys": [k.as_dict(private=False) for k in keys]})

    async def _key_set(metadata: dict, *, force: bool = False) -> KeySet:
        return key_set

    monkeypatch.setattr(oidc_core, "_key_set", _key_set)


async def test_a_valid_id_token_verifies(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_key_set(monkeypatch, signing_key)

    claims = await oidc_core._verify_id_token(
        make_id_token(signing_key), nonce="the-nonce", metadata=metadata
    )

    assert claims["sub"] == "subject-1"
    assert claims["email"] == "member@example.com"


async def test_a_tampered_id_token_is_rejected(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_key_set(monkeypatch, signing_key)
    header, payload, signature = make_id_token(signing_key).split(".")
    forged = f"{header}.{payload}.{signature[:-4]}AAAA"

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(forged, nonce="the-nonce", metadata=metadata)


async def test_a_token_signed_by_a_stranger_is_rejected(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone else's key, same claims. This is the check that stops a forged identity."""
    impostor = RSAKey.generate_key(2048, parameters={"kid": "kid-1"}, private=True)
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(
            make_id_token(impostor), nonce="the-nonce", metadata=metadata
        )


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"iss": "https://evil.example"}, "issuer"),
        ({"aud": "another-client"}, "audience"),
        ({"exp": int(time.time()) - 3600}, "expiry"),
    ],
)
async def test_bad_claims_are_rejected(
    oidc: str,
    signing_key: RSAKey,
    metadata: dict,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict,
    why: str,
) -> None:
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(
            make_id_token(signing_key, **overrides), nonce="the-nonce", metadata=metadata
        )


async def test_a_mismatched_nonce_is_rejected(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked by hand, because joserfc's claims registry has no nonce rule: it is an
    OIDC claim, not a JWT one. It is what makes replaying a captured id_token into a
    fresh flow useless."""
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(
            make_id_token(signing_key), nonce="a-different-nonce", metadata=metadata
        )


# The warning comes from this test forging the token, not from any production path: joserfc
# warns rather than refusing when asked to sign with `none`, which is the whole reason the
# allowlist below has to exist.
@pytest.mark.filterwarnings("ignore:JWS algorithm .none. is deprecated")
async def test_an_unsigned_token_is_rejected_even_if_the_provider_advertises_none(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The algorithm allowlist.

    `id_token_signing_alg_values_supported` is provider-controlled data, and joserfc will
    happily decode an `alg=none` token (warning rather than refusing), so passing that list
    through unfiltered would let a hostile or compromised discovery document switch off the
    one check standing between a stranger and a session. Intersecting with our own list is
    what stops it.
    """
    stub_key_set(monkeypatch, signing_key)
    hostile = {**metadata, "id_token_signing_alg_values_supported": ["none"]}
    now = int(time.time())
    unsigned = jwt.encode(
        {"alg": "none"},
        {
            "iss": ISSUER,
            "sub": "an-impostor",
            "aud": "isachore-client",
            "exp": now + 300,
            "iat": now,
            "nonce": "the-nonce",
            "email": "member@example.com",
        },
        # joserfc needs a key object even for `none`; the value is unused in the signature.
        signing_key,
        algorithms=["none"],
    )

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(unsigned, nonce="the-nonce", metadata=hostile)


async def test_a_symmetric_signature_is_rejected_even_if_advertised(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Algorithm confusion: an HS256 token, which verifies with a *shared secret* rather
    than a published key, offered to a client that holds a client secret.

    Two layers refuse it and the test does not care which: the allowlist keeps HS256 out of
    the algorithms we pass to joserfc, and joserfc would itself refuse an `oct` algorithm
    against an RSA key set. What matters is that a genuinely HS256-signed token cannot open a
    session however loudly the provider's metadata recommends it.
    """
    stub_key_set(monkeypatch, signing_key)
    hostile = {**metadata, "id_token_signing_alg_values_supported": ["HS256"]}
    now = int(time.time())
    forged = jwt.encode(
        {"alg": "HS256"},
        {
            "iss": ISSUER,
            "sub": "an-impostor",
            "aud": "isachore-client",
            "exp": now + 300,
            "iat": now,
            "nonce": "the-nonce",
            "email": "member@example.com",
        },
        OctKey.import_key("not-a-real-secret"),
    )

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(forged, nonce="the-nonce", metadata=hostile)


async def test_a_multi_audience_token_needs_azp_naming_us(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OIDC Core 3.1.3.7 goes beyond JWT's `aud` rule.

    The claims registry is satisfied by our client id appearing anywhere in the list, so
    without the `azp` check a token minted for another client that merely lists us as a
    second audience would pass.
    """
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(
            make_id_token(signing_key, aud=["another-client", "isachore-client"]),
            nonce="the-nonce",
            metadata=metadata,
        )

    # ...and it is accepted once azp names us, so the rule is about azp and not about the
    # list having more than one entry.
    claims = await oidc_core._verify_id_token(
        make_id_token(
            signing_key, aud=["another-client", "isachore-client"], azp="isachore-client"
        ),
        nonce="the-nonce",
        metadata=metadata,
    )
    assert claims["sub"] == "subject-1"


@pytest.mark.parametrize(
    "audience",
    [
        # Single audience naming us, so the `aud` rule alone is satisfied and only the azp
        # rule can refuse: a token minted for another client that names us as its sole
        # audience while its azp says who it was really for.
        "isachore-client",
        ["isachore-client"],
        # And with several audiences, where the azp is present but wrong.
        ["another-client", "isachore-client"],
    ],
)
async def test_an_azp_naming_another_client_is_rejected(
    oidc: str,
    signing_key: RSAKey,
    metadata: dict,
    monkeypatch: pytest.MonkeyPatch,
    audience: object,
) -> None:
    """OIDC says `azp` SHOULD be verified whenever it is present, not only when `aud` has
    several entries - and the claims registry is satisfied by our id appearing anywhere."""
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError, match="azp"):
        await oidc_core._verify_id_token(
            make_id_token(signing_key, aud=audience, azp="another-client"),
            nonce="the-nonce",
            metadata=metadata,
        )


async def test_an_azp_naming_us_is_accepted(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_key_set(monkeypatch, signing_key)

    claims = await oidc_core._verify_id_token(
        make_id_token(signing_key, azp="isachore-client"), nonce="the-nonce", metadata=metadata
    )
    assert claims["sub"] == "subject-1"


async def test_a_single_audience_token_needs_no_azp(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case every mainstream provider actually sends."""
    stub_key_set(monkeypatch, signing_key)

    claims = await oidc_core._verify_id_token(
        make_id_token(signing_key, aud=["isachore-client"]), nonce="the-nonce", metadata=metadata
    )
    assert claims["sub"] == "subject-1"


async def test_an_unknown_key_id_refetches_the_key_set(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Key rotation. Without the forced re-fetch, every sign-in breaks the moment the
    provider rotates its signing key and stays broken until the cache expires."""
    stale = RSAKey.generate_key(2048, parameters={"kid": "old-kid"}, private=True)
    calls: list[bool] = []

    async def _key_set(metadata: dict, *, force: bool = False) -> KeySet:
        calls.append(force)
        keys = [signing_key] if force else [stale]
        return KeySet.import_key_set({"keys": [k.as_dict(private=False) for k in keys]})

    monkeypatch.setattr(oidc_core, "_key_set", _key_set)

    claims = await oidc_core._verify_id_token(
        make_id_token(signing_key), nonce="the-nonce", metadata=metadata
    )

    assert claims["sub"] == "subject-1"
    # Once optimistically, then once more forcing a fresh fetch.
    assert calls == [False, True]


# --- oidc_configured / redirect_uri ------------------------------------


def test_oidc_is_not_configured_by_default() -> None:
    assert oidc_core.oidc_configured() is False


def test_oidc_is_configured_with_all_three(oidc: str) -> None:
    assert oidc_core.oidc_configured() is True


@pytest.mark.parametrize("missing", ["oidc_issuer", "oidc_client_id", "oidc_client_secret"])
def test_any_missing_credential_means_not_configured(
    oidc: str, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setattr(settings, missing, None)

    assert oidc_core.oidc_configured() is False


def test_the_provider_name_is_not_part_of_being_configured(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cosmetic, like totp_issuer: a deploy that forgot the label should still work."""
    monkeypatch.setattr(settings, "oidc_provider_name", "")

    assert oidc_core.oidc_configured() is True


def test_the_redirect_uri_is_derived_from_the_app_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_base_url", "https://chores.example.com/")

    assert oidc_core.redirect_uri() == "https://chores.example.com/api/v1/auth/oidc/callback"


# --- the provider-facing half -------------------------------------------
#
# discover(), _key_set(), _fetch_userinfo() and build_identity() carry security checks of
# their own - the issuer must match what we configured, a userinfo body must describe the
# same subject as the token - and none of it is reachable through the endpoint tests, which
# stub `complete` wholesale. These drive it directly, stubbing only the HTTP layer.


class _FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> object:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient inside core/oidc.py, keyed by url substring."""

    # Class-level on purpose: core/oidc.py constructs its own client, so the routes have to
    # reach it through the class rather than through an instance the test could hold.
    routes: ClassVar[dict[str, object]] = {}
    seen: ClassVar[list[str]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        type(self).seen.append(url)
        for fragment, payload in type(self).routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload)
        raise AssertionError(f"no fake route for {url}")


class _HttpxShim:
    """Real httpx for everything except `AsyncClient`.

    Delegating rather than listing the attributes the module happens to use today: the except
    clauses in core/oidc.py name exception classes off this same module, so a hand-written
    namespace goes stale the moment one is added - as `httpx.InvalidURL` did, turning every
    JWKS test into an AttributeError instead of the refusal it was asserting.
    """

    AsyncClient = _FakeAsyncClient

    def __getattr__(self, name: str) -> object:
        return getattr(httpx, name)


def stub_http(monkeypatch: pytest.MonkeyPatch, routes: dict[str, object]) -> type[_FakeAsyncClient]:
    """Patch the `httpx` name in core/oidc.py's namespace, not the httpx module itself:
    patching the module would swap the AsyncClient the test client is built on too."""
    _FakeAsyncClient.routes = routes
    _FakeAsyncClient.seen = []
    monkeypatch.setattr(oidc_core, "httpx", _HttpxShim())
    return _FakeAsyncClient


DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "userinfo_endpoint": f"{ISSUER}/userinfo",
    "jwks_uri": f"{ISSUER}/jwks",
    "id_token_signing_alg_values_supported": ["RS256"],
}


async def test_discover_returns_and_caches_the_metadata(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = stub_http(monkeypatch, {"openid-configuration": DISCOVERY})

    first = await oidc_core.discover()
    second = await oidc_core.discover()

    assert first["token_endpoint"] == f"{ISSUER}/token"
    assert second is first
    # Cached, so the provider is not on the critical path of every sign-in twice over.
    assert len(fake.seen) == 1


async def test_discover_refuses_a_provider_that_calls_itself_something_else(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check that ties OIDC_ISSUER to the `iss` the provider actually signs.

    Without it a misconfigured url is not caught here but downstream, as an opaque claim
    rejection on every sign-in, with nothing pointing at the url as the cause.
    """
    stub_http(monkeypatch, {"openid-configuration": {**DISCOVERY, "issuer": "https://elsewhere"}})

    with pytest.raises(OidcError, match="different issuer"):
        await oidc_core.discover()


async def test_discover_ignores_a_trailing_slash_on_either_side(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Authentik's issuer conventionally ends in one and operators paste it either way, so
    # being strict here would reject a correct configuration over punctuation.
    monkeypatch.setattr(settings, "oidc_issuer", f"{ISSUER}/")
    stub_http(monkeypatch, {"openid-configuration": DISCOVERY})

    metadata = await oidc_core.discover()

    assert metadata["issuer"] == ISSUER


@pytest.mark.parametrize("payload", [[], "a string", 5, None])
async def test_discover_refuses_metadata_that_is_not_an_object(
    oidc: str, monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    """A captive portal or an error page rendered as JSON answers 200 with a non-object.
    Every `.get(...)` downstream would raise AttributeError, i.e. a 500 out of /start."""
    stub_http(monkeypatch, {"openid-configuration": payload})

    with pytest.raises(OidcError):
        await oidc_core.discover()


@pytest.mark.parametrize(
    "raised",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        # InvalidURL is deliberately NOT an httpx.HTTPError, so it has to be named in the
        # except tuple separately. httpx raises it for a url that is too long, carries a
        # control character, has an invalid port or a bad IDNA host - all reachable from a
        # mistyped OIDC_ISSUER, which would otherwise 500 the sign-in entry point.
        httpx.InvalidURL("URL too long"),
    ],
)
async def test_discover_reports_an_unreachable_provider(
    oidc: str, monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    stub_http(monkeypatch, {"openid-configuration": raised})

    with pytest.raises(OidcError, match="could not fetch"):
        await oidc_core.discover()


@pytest.mark.parametrize(
    "raised", [httpx.ConnectError("refused"), httpx.InvalidURL("Invalid non-printable ASCII")]
)
async def test_an_unreachable_jwks_is_a_refusal_not_a_crash(
    oidc: str, monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    # Same InvalidURL gap on this side: a discovery document is provider-controlled, so its
    # `jwks_uri` can be any string at all.
    stub_http(monkeypatch, {"jwks": raised})

    with pytest.raises(OidcError, match="could not fetch signing keys"):
        await oidc_core._key_set(DISCOVERY)


@pytest.mark.parametrize("payload", [[], {"nope": 1}, "junk", {"keys": "not-a-list"}])
async def test_a_malformed_jwks_is_a_refusal_not_a_crash(
    oidc: str, monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    """import_key_set raises TypeError for an array or scalar and KeyError for an object with
    no "keys" - which is what a provider answering `{"error": ...}` with status 200 sends.
    Neither is a JoseError, so both would escape as a 500 if they were not caught."""
    stub_http(monkeypatch, {"jwks": payload})

    with pytest.raises(OidcError, match="could not fetch signing keys"):
        await oidc_core._key_set(DISCOVERY)


async def test_a_jwks_with_no_uri_is_a_refusal(oidc: str) -> None:
    with pytest.raises(OidcError, match="no jwks_uri"):
        await oidc_core._key_set({"issuer": ISSUER})


# --- userinfo -----------------------------------------------------------


class _FakeAuthedClient:
    def __init__(self, payload: object, *, raises: Exception | None = None) -> None:
        self._payload = payload
        self._raises = raises

    async def get(self, url: str) -> _FakeResponse:
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._payload)


async def test_userinfo_is_read_when_it_matches_the_token(oidc: str) -> None:
    client = _FakeAuthedClient({"sub": "subject-1", "email": "from-userinfo@example.com"})

    info = await oidc_core._fetch_userinfo(client, DISCOVERY, "subject-1")

    assert info["email"] == "from-userinfo@example.com"


async def test_userinfo_describing_another_subject_is_refused(oidc: str) -> None:
    """OIDC requires the two to agree. This is the one userinfo failure that must NOT be
    swallowed: a body describing a different account than the token we just verified would
    otherwise have its email merged in and pick the wrong local account to link."""
    client = _FakeAuthedClient({"sub": "somebody-else", "email": "victim@example.com"})

    with pytest.raises(OidcError, match="different subject"):
        await oidc_core._fetch_userinfo(client, DISCOVERY, "subject-1")


async def test_userinfo_with_no_subject_is_ignored_rather_than_trusted(oidc: str) -> None:
    # Defaulting the absent `sub` to the expected one would make the mismatch check pass on
    # exactly the bodies it exists to reject.
    client = _FakeAuthedClient({"email": "unattributed@example.com"})

    assert await oidc_core._fetch_userinfo(client, DISCOVERY, "subject-1") == {}


@pytest.mark.parametrize("payload", [[], "junk", 7])
async def test_userinfo_that_is_not_an_object_is_ignored(oidc: str, payload: object) -> None:
    client = _FakeAuthedClient(payload)

    assert await oidc_core._fetch_userinfo(client, DISCOVERY, "subject-1") == {}


async def test_a_broken_userinfo_endpoint_does_not_fail_the_sign_in(oidc: str) -> None:
    """Best-effort by design: the id_token already carries a verified identity, so a provider
    with no reachable userinfo must still be able to sign people in. Includes authlib's own
    OAuthError family, which fires from inside `get` when it validates the access token."""
    client = _FakeAuthedClient(None, raises=RuntimeError("authlib says no"))

    assert await oidc_core._fetch_userinfo(client, DISCOVERY, "subject-1") == {}


async def test_no_userinfo_endpoint_is_not_an_error(oidc: str) -> None:
    client = _FakeAuthedClient({"sub": "subject-1"})

    assert await oidc_core._fetch_userinfo(client, {"issuer": ISSUER}, "subject-1") == {}


# --- build_identity -----------------------------------------------------


def test_userinfo_wins_over_the_id_token(oidc: str) -> None:
    """The precedence that picks the account a first sign-in links to.

    Providers that keep the id_token minimal send email only from userinfo, so preferring the
    token would break them outright. It does mean an unsigned body overrides a signed claim,
    which is sound only because _fetch_userinfo refuses any body whose `sub` disagrees.
    """
    identity = oidc_core.build_identity(
        {"sub": "subject-1", "email": "stale@example.com"},
        {"sub": "subject-1", "email": "current@example.com"},
        issuer=ISSUER,
    )

    assert identity.email == "current@example.com"


def test_the_id_token_fills_the_gaps_userinfo_leaves(oidc: str) -> None:
    identity = oidc_core.build_identity(
        {"sub": "subject-1", "email": "from-token@example.com"},
        {"sub": "subject-1"},
        issuer=ISSUER,
    )

    assert identity.email == "from-token@example.com"


def test_an_address_is_normalised_the_way_the_column_stores_it(oidc: str) -> None:
    # Local addresses are stored lower-cased, so a provider sending mixed case must still
    # find the account rather than reporting "no account".
    identity = oidc_core.build_identity(
        {"sub": "subject-1", "email": "  Jo@Example.COM  "}, {}, issuer=ISSUER
    )

    assert identity.email == "jo@example.com"


def test_a_missing_email_is_none_rather_than_empty(oidc: str) -> None:
    identity = oidc_core.build_identity({"sub": "subject-1"}, {}, issuer=ISSUER)

    assert identity.email is None


# --- begin() and complete(), with the OAuth2 client stubbed ---------------


class _FakeOAuthClient:
    """Stands in for authlib's AsyncOAuth2Client. Only the three things core/oidc.py uses."""

    def __init__(
        self,
        *,
        token: dict | None = None,
        userinfo: object = None,
        fetch_raises: Exception | None = None,
    ) -> None:
        self._token = token or {}
        self._userinfo = userinfo
        self._fetch_raises = fetch_raises
        self.fetch_kwargs: dict = {}

    async def __aenter__(self) -> "_FakeOAuthClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def create_authorization_url(self, url: str, **kwargs: object) -> tuple[str, str]:
        query = "&".join(f"{k}={v}" for k, v in kwargs.items() if k != "code_verifier")
        # Mirrors authlib: the verifier is never in the url, its S256 challenge is.
        return f"{url}?{query}&code_challenge=derived&code_challenge_method=S256", str(
            kwargs.get("state", "")
        )

    async def fetch_token(self, url: str, **kwargs: object) -> dict:
        self.fetch_kwargs = dict(kwargs)
        if self._fetch_raises is not None:
            raise self._fetch_raises
        return self._token

    async def get(self, url: str) -> _FakeResponse:
        return _FakeResponse(self._userinfo)


def stub_oauth_client(monkeypatch: pytest.MonkeyPatch, client: _FakeOAuthClient) -> None:
    monkeypatch.setattr(oidc_core, "_client", lambda **kwargs: client)


async def test_begin_asks_for_pkce_and_carries_the_state_and_nonce(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PKCE is what binds the callback's `code` to the browser that started the flow, so it
    being actually requested (rather than merely configured) is worth asserting."""
    stub_http(monkeypatch, {"openid-configuration": DISCOVERY})
    stub_oauth_client(monkeypatch, _FakeOAuthClient())

    url, nonce, code_verifier = await oidc_core.begin(state="the-state")

    assert url.startswith(f"{ISSUER}/authorize?")
    assert "code_challenge_method=S256" in url
    assert "state=the-state" in url
    assert f"nonce={nonce}" in url
    # The verifier stays server-side; only its challenge travels.
    assert code_verifier not in url
    # 43 unreserved characters is exactly the PKCE minimum length.
    assert len(code_verifier) >= 43


async def test_begin_refuses_a_provider_with_no_authorization_endpoint(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, {"openid-configuration": {"issuer": ISSUER, "jwks_uri": "x"}})

    with pytest.raises(OidcError, match="no authorization_endpoint"):
        await oidc_core.begin(state="s")


async def test_complete_returns_the_identity(
    oidc: str, signing_key: RSAKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, {"openid-configuration": DISCOVERY})
    stub_key_set(monkeypatch, signing_key)
    client = _FakeOAuthClient(
        token={"id_token": make_id_token(signing_key), "access_token": "at"},
        userinfo={"sub": "subject-1", "email": "from-userinfo@example.com"},
    )
    stub_oauth_client(monkeypatch, client)

    identity = await oidc_core.complete(
        code="the-code", code_verifier="the-verifier", nonce="the-nonce"
    )

    assert identity.subject == "subject-1"
    assert identity.issuer == ISSUER
    assert identity.email == "from-userinfo@example.com"
    # The verifier and the redirect uri both go to the token endpoint, which is what makes
    # the exchange unusable to anyone who has only the code.
    assert client.fetch_kwargs["code"] == "the-code"
    assert client.fetch_kwargs["code_verifier"] == "the-verifier"
    assert client.fetch_kwargs["grant_type"] == "authorization_code"
    assert client.fetch_kwargs["redirect_uri"] == oidc_core.redirect_uri()


async def test_complete_refuses_a_token_response_with_no_id_token(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain OAuth2 provider (or an OIDC one asked without the openid scope) answers with an
    access token and nothing else. There is no verified identity in that, so it cannot pass."""
    stub_http(monkeypatch, {"openid-configuration": DISCOVERY})
    stub_oauth_client(monkeypatch, _FakeOAuthClient(token={"access_token": "at"}))

    with pytest.raises(OidcError, match="no id_token"):
        await oidc_core.complete(code="c", code_verifier="v", nonce="n")


async def test_complete_turns_a_rejected_code_into_an_oidc_error(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """authlib raises its own OAuthError family for a rejected code and httpx errors for a
    provider that is down; the router has one `except OidcError`, so both must arrive as one."""
    stub_http(monkeypatch, {"openid-configuration": DISCOVERY})
    stub_oauth_client(monkeypatch, _FakeOAuthClient(fetch_raises=RuntimeError("invalid_grant")))

    with pytest.raises(OidcError, match="token exchange failed"):
        await oidc_core.complete(code="c", code_verifier="v", nonce="n")


async def test_complete_refuses_a_provider_with_no_token_endpoint(
    oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, {"openid-configuration": {"issuer": ISSUER, "jwks_uri": "x"}})

    with pytest.raises(OidcError, match="no token_endpoint"):
        await oidc_core.complete(code="c", code_verifier="v", nonce="n")


async def test_an_unconfigured_provider_cannot_start_a_flow() -> None:
    # No `oidc` fixture: the autouse reset leaves the whole group unset.
    with pytest.raises(OidcError, match=oidc_core.NO_OIDC_DETAIL):
        await oidc_core.discover()


async def test_a_signed_payload_that_is_not_an_object_is_refused(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JWT payload only conventionally holds a JSON object.

    joserfc verifies the signature over whatever bytes were signed and hands back `.claims`
    as a list, string, number or None if that is what is inside - and every read after the
    decode assumes a mapping. Without the type check that is an AttributeError, which is not
    a JoseError, so it escapes as a 500 rather than the "provider" refusal this module
    promises for every failure.
    """
    from joserfc import jws

    stub_key_set(monkeypatch, signing_key)
    non_object = jws.serialize_compact(
        {"alg": "RS256", "kid": signing_key.kid}, b"null", signing_key
    )

    with pytest.raises(OidcError):
        await oidc_core._verify_id_token(non_object, nonce="the-nonce", metadata=metadata)


@pytest.mark.parametrize("advertised", [5, {"RS256": True}, "RS256", None])
async def test_a_non_list_algorithm_advertisement_does_not_crash(
    oidc: str,
    signing_key: RSAKey,
    metadata: dict,
    monkeypatch: pytest.MonkeyPatch,
    advertised: object,
) -> None:
    """`id_token_signing_alg_values_supported` is provider data and need not be a list. A
    scalar would make the intersection comprehension raise TypeError; a string or dict
    survives only by accident (iterating yields characters or keys, which intersect with
    nothing), so the guard is what makes all four land on the RS256 fallback deliberately."""
    stub_key_set(monkeypatch, signing_key)
    odd = {**metadata, "id_token_signing_alg_values_supported": advertised}

    claims = await oidc_core._verify_id_token(
        make_id_token(signing_key), nonce="the-nonce", metadata=odd
    )

    assert claims["sub"] == "subject-1"


# --- the provider name is never blank on the wire ------------------------


async def test_methods_falls_back_when_the_provider_name_is_blank(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`OIDC_PROVIDER_NAME=` in a .env arrives as "" - reachable, since the name is cosmetic
    and deliberately outside oidc_configured(). A client handed a blank label must choose
    between rendering "Sign in with " and rendering nothing, and under OIDC_ONLY the second
    is a login page with no way in at all. So the invariant lives here: enabled implies a
    usable name."""
    monkeypatch.setattr(settings, "oidc_provider_name", "")

    resp = await client.get("/api/v1/auth/methods")

    assert resp.json()["oidc_enabled"] is True
    assert resp.json()["oidc_provider_name"] == "SSO"


async def test_methods_trims_the_provider_name(
    client: AsyncClient, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "oidc_provider_name", "  Authentik  ")

    resp = await client.get("/api/v1/auth/methods")

    assert resp.json()["oidc_provider_name"] == "Authentik"


async def test_an_over_long_subject_is_refused_rather_than_truncated(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both columns hold 255. Truncating would make it a *different* identity, which could
    collide with somebody else's; letting it through would be a DataError 500 on the commit."""
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, subject="s" * 300)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "provider"
    assert client.cookies.get("isachore_token") is None


async def test_the_key_set_is_cached_and_a_forced_fetch_bypasses_it(
    oidc: str, signing_key: RSAKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives the REAL _key_set, which the rotation test above cannot.

    That test replaces `_key_set` with a fake honouring `force`, so it says nothing about the
    real one: deleting `and not force` there would leave the whole suite green while breaking
    the self-heal the retry loop exists for - every sign-in failing for up to an hour after a
    provider rotates its signing key. This is the test that notices.
    """
    jwks = {"keys": [signing_key.as_dict(private=False)]}
    fake = stub_http(monkeypatch, {"jwks": jwks})

    first = await oidc_core._key_set(DISCOVERY)
    second = await oidc_core._key_set(DISCOVERY)
    assert len(fake.seen) == 1, "the second call should have been served from the cache"
    assert second is first

    forced = await oidc_core._key_set(DISCOVERY, force=True)
    assert len(fake.seen) == 2, "force=True must bypass the cache"
    assert forced is not first


async def test_the_metadata_cache_is_per_issuer(oidc: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyed by issuer rather than held in a bare global, so repointing OIDC_ISSUER cannot be
    served a document fetched for the previous one - which is also what keeps one test's
    provider out of the next test's."""
    other = "https://second-idp.example.com/application/o/isachore"
    fake = stub_http(
        monkeypatch,
        {"openid-configuration": DISCOVERY},
    )
    await oidc_core.discover()
    assert len(fake.seen) == 1

    monkeypatch.setattr(settings, "oidc_issuer", other)
    stub_http(monkeypatch, {"openid-configuration": {**DISCOVERY, "issuer": other}})

    metadata = await oidc_core.discover()

    assert metadata["issuer"] == other


async def test_expired_flows_are_swept_when_a_new_one_starts(
    client: AsyncClient, db_session: AsyncSession, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every abandoned sign-on leaves a row and abandoning is one click, so the sweep is what
    keeps the table from growing on failed attempts rather than successful ones. Nothing
    cascades into it (no user_id), so this is the only thing that clears it."""
    stub_begin(monkeypatch)
    await start_flow(client)
    stale = (await db_session.execute(select(OidcLoginState))).scalar_one()
    stale.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    await start_flow(client)

    rows = (await db_session.execute(select(OidcLoginState))).scalars().all()
    assert len(rows) == 1, "the expired row should have been swept by the new flow"
    assert rows[0].expires_at > datetime.now(UTC)


async def test_an_over_long_issuer_is_refused_too(
    client: AsyncClient, make_user: Login, oidc: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the length guard. Reachable only through operator config, but the
    # column is the same width and the failure would be the same DataError 500.
    await make_user(email="member@example.com")
    stub_begin(monkeypatch)
    stub_complete(monkeypatch, issuer="https://i.example.com/" + "x" * 300)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) == "provider"
    assert client.cookies.get("isachore_token") is None


# --- diagnostics on a token that will not verify -------------------------


def test_describe_token_names_how_it_was_signed(signing_key: RSAKey) -> None:
    described = oidc_core.describe_token(make_id_token(signing_key))

    assert "3 segments" in described
    assert "alg=RS256" in described
    assert f"kid={signing_key.kid}" in described


def test_describe_token_never_includes_the_payload(signing_key: RSAKey) -> None:
    """The header describes how the token was made and is public by construction. The payload
    is the identity - `sub`, `email` - and is exactly what must not reach a log that ships
    off-box under someone else's retention."""
    token = make_id_token(signing_key, email="private@example.com", sub="secret-subject")

    described = oidc_core.describe_token(token)

    assert "private@example.com" not in described
    assert "secret-subject" not in described
    # ...nor the signature, the one part an attacker would want.
    assert token.split(".")[2] not in described


@pytest.mark.filterwarnings("ignore:JWS algorithm .none. is deprecated")
def test_describe_token_names_an_unsigned_token(signing_key: RSAKey) -> None:
    from joserfc import jws

    unsigned = jws.serialize_compact(
        {"alg": "none"}, b'{"sub":"x"}', signing_key, algorithms=["none"]
    )

    assert "alg=none" in oidc_core.describe_token(unsigned)


def test_describe_token_spots_an_encrypted_token() -> None:
    """Five segments plus an `enc` header is a JWE, which is what an Encryption Key set on the
    provider produces. We do not decrypt, so an operator needs to read that off the log rather
    than guess why a working provider suddenly emits garbage."""
    described = oidc_core.describe_token("aaa.bbb.ccc.ddd.eee")

    assert "5 segments" in described


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("", "1 segments"),
        ("only-one-part", "1 segments"),
        ("!!!not-base64!!!.body.sig", "unreadable header"),
        # Valid base64url, but the header is not a JSON object.
        ("WyJhIl0.body.sig", "header is not an object"),
    ],
)
def test_describe_token_survives_junk(token: str, expected: str) -> None:
    # It runs on the failure path, so it must never raise and mask the real error.
    assert expected in oidc_core.describe_token(token)


def test_describe_keys_lists_the_key_ids(signing_key: RSAKey) -> None:
    key_set = KeySet.import_key_set({"keys": [signing_key.as_dict(private=False)]})

    assert oidc_core.describe_keys(key_set) == signing_key.kid


def test_describe_keys_says_so_when_there_are_no_keys() -> None:
    """Note an empty JWKS never reaches this: `KeySet.import_key_set({"keys": []})` raises
    MissingKeyError, which `_key_set` already reports as "could not fetch signing keys". So the
    empty branch is for a KeySet built some other way, and the distinct wording is what tells
    those two situations apart in a log."""
    assert oidc_core.describe_keys(KeySet([])) == "none published"


async def test_a_verification_failure_says_what_it_saw(
    oidc: str, signing_key: RSAKey, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: the OidcError the router logs has to carry enough to act on.

    Before this, a real deployment produced `id_token did not verify: DecodeError` and nothing
    else - which does not distinguish an unsigned token from an encrypted one from a key we do
    not hold, and each needs a different change on the provider.
    """
    impostor = RSAKey.generate_key(2048, parameters={"kid": "not-ours"}, private=True)
    stub_key_set(monkeypatch, signing_key)

    with pytest.raises(OidcError) as caught:
        await oidc_core._verify_id_token(
            make_id_token(impostor), nonce="the-nonce", metadata=metadata
        )

    message = str(caught.value)
    assert "kid=not-ours" in message
    assert f"provider keys: {signing_key.kid}" in message
    assert "algorithms tried: RS256" in message


# --- verification is isachore's own question -----------------------------


@pytest.mark.parametrize("claims", [{}, {"email_verified": False}, {"email_verified": "no"}])
async def test_the_providers_view_of_the_address_does_not_gate_the_sign_in(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    smtp: list,
    monkeypatch: pytest.MonkeyPatch,
    claims: dict,
) -> None:
    """Whether an address is verified is answered by `users.confirmed_at`, not by the
    provider, and that holds with confirmation switched on - the setting that used to be half
    of this decision.

    Parametrised over absent, false and stringified because providers differ: Authentik's
    default scope mapping omits the claim entirely, which is what makes gating on it a poor
    idea rather than merely a strict one.
    """
    user = await make_user(email="member@example.com")
    app_settings = await get_app_settings(db_session)
    app_settings.require_confirmation = True
    await db_session.commit()

    async def _complete(**kwargs: object) -> OidcIdentity:
        return OidcIdentity(subject="subject-1", issuer=ISSUER, email="member@example.com")

    stub_begin(monkeypatch)
    monkeypatch.setattr(oidc_core, "complete", _complete)
    state = await start_flow(client)

    resp = await callback(client, state)

    assert sso_error(resp) is None
    assert client.cookies.get("isachore_token")
    await db_session.refresh(user)
    assert user.oidc_subject == "subject-1"


async def test_an_unconfirmed_account_can_still_sign_in_through_the_provider(
    client: AsyncClient,
    db_session: AsyncSession,
    make_user: Login,
    oidc: str,
    smtp: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`confirmed_at` records whether the address was proved; it does not gate signing in.

    An active account that never confirmed is exactly the state the Profile badge exists to
    show, so it has to be reachable rather than refused at the door.
    """
    user = await make_user(email="member@example.com")
    # Nulled after the fact: `make_user` substitutes now() for an active user, so passing
    # confirmed_at=None is indistinguishable from omitting it and cannot express this edge.
    user.confirmed_at = None
    app_settings = await get_app_settings(db_session)
    app_settings.require_confirmation = True
    await db_session.commit()

    stub_begin(monkeypatch)
    stub_complete(monkeypatch)
    state = await start_flow(client)

    assert sso_error(await callback(client, state)) is None
    await db_session.refresh(user)
    assert user.confirmed_at is None
