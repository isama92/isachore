"""Single sign-on endpoints: who is allowed in through the identity provider.

app/core/oidc.py owns the protocol; this owns the policy. Both endpoints are GET and
both answer with a redirect, which is not incidental:

- **GET, so the state cookie survives.** Auth cookies here are `SameSite=Lax`, and a
  Lax cookie is sent on a cross-site top-level *navigation* but not on a cross-site
  POST. A `form_post` response mode would therefore arrive with no state cookie and
  every sign-in would fail the browser-binding check. Being GET also means
  CsrfProtectMiddleware exempts them on method alone, which is what makes the callback
  reachable at all: it is a plain navigation from the provider, with no opportunity to
  set an X-CSRF-Token header. (That exemption is why `isachore_oidc` being absent from
  `_AUTH_COOKIES` does not matter for *these* endpoints; it is absent because it
  authenticates nobody, which is the reason that survives a change of method.)
- **Redirects, not JSON.** The caller is a browser following a redirect chain, not the
  `api` wrapper, so a refusal has to land somewhere a person can read. Every failure
  goes back to the login page with an `sso_error` code that the SPA turns into a
  translated message.

The refusal codes are deliberately coarse. A visitor learns whether *they* need to do
something ("no account here", "your email is not verified") and nothing about anyone
else's account; the diagnostic detail goes to the log and the audit trail. That is also
why the provider's own failures collapse into one `provider` code.
"""

import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.api.deps import RedisDep, SessionDep
from app.api.v1.auth import mint_session, open_session

# `begin` and `complete` are called through the module rather than imported by name, for
# the same reason the endpoints call clock.now(): it leaves
# `monkeypatch.setattr(oidc_core, "complete", ...)` able to reach them, so the policy
# below is testable with no provider anywhere near it. Importing the names would bind
# them at import time and silently defeat every stub in tests/test_oidc.py.
from app.core import oidc as oidc_core
from app.core.app_settings import get_app_settings
from app.core.audit import record_event
from app.core.config import settings
from app.core.oidc import NO_OIDC_DETAIL, OidcError, OidcIdentity, oidc_configured
from app.core.rate_limit import (
    client_ip,
    enforce_oidc_rate_limit,
    enforce_oidc_start_rate_limit,
    record_oidc_failure,
)
from app.core.security import (
    OIDC_STATE_COOKIE_NAME,
    OIDC_STATE_TTL,
    clear_auth_cookie,
    generate_token,
    hash_token,
    set_auth_cookie,
)
from app.core.tokens import purge_expired_oidc_states
from app.models import AuditAction, ConfirmationToken, OidcLoginState, User, UserStatus

logger = logging.getLogger(__name__)

router = APIRouter()

# Codes appended to the login url as ?sso_error=. The SPA maps each to a translated
# message and degrades an unrecognised one to a generic apology, so adding a code here
# is safe ahead of the frontend catching up.
ERROR_NO_ACCOUNT = "no_account"
ERROR_EMAIL_UNVERIFIED = "email_unverified"
ERROR_ACCOUNT_DISABLED = "account_disabled"
ERROR_ALREADY_LINKED = "already_linked"
ERROR_STATE = "state"
ERROR_PROVIDER = "provider"


def _login_redirect(code: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}/login?sso_error={code}",
        status_code=status.HTTP_302_FOUND,
    )


def _safe_return_to(raw: str | None) -> str | None:
    """A site-relative path we are willing to send a browser to after sign-in, or None.

    The open-redirect guard. Everything except a path starting with a single "/" is
    discarded rather than corrected, because there is no reading of "https://evil" or
    "//evil" that we want to honour and a signed-in visitor landing on an attacker's
    page is exactly what this endpoint would otherwise be a convenient laundry for.
    Backslashes go too: some browsers normalise "/\\evil.example" into a protocol
    relative url, so it is a "//" in disguise.

    Over-long paths are dropped rather than truncated. The column holds 255, and a truncated
    path is a *different* path: sending somebody to a silently mangled url is worse than
    sending them to the home page, which is where a None lands them.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return None
    if len(raw) > 255:
        return None
    return raw


async def _refuse(
    session: SessionDep,
    redis: RedisDep,
    *,
    code: str,
    ip: str | None,
    reason: str,
    email: str | None = None,
) -> RedirectResponse:
    """Record a failed sign-on and send the browser back to the login page.

    The audit action is the ordinary `login_failed` rather than an SSO-specific one:
    `audit_events.action` is a native Postgres enum, so a new value needs an ALTER TYPE,
    and app/cli.py already sets the precedent of reusing an existing action with the
    specifics in `detail`. "oidc" leads the detail so the SSO attempts stay greppable
    apart from password ones.
    """
    await record_oidc_failure(redis, ip=ip)
    detail = f"oidc {reason}" + (f" {email}" if email else "")
    await record_event(session, action=AuditAction.login_failed, ip=ip, detail=detail[:255])
    await session.commit()
    response = _login_redirect(code)
    # The flow is over either way, so the browser should not keep offering its state.
    clear_auth_cookie(response, OIDC_STATE_COOKIE_NAME)
    return response


@router.get("/start")
async def start(
    session: SessionDep, redis: RedisDep, request: Request, return_to: str | None = None
) -> RedirectResponse:
    """Begin a sign-on: park the flow's secrets and send the browser to the provider."""
    # Its own counter, not the callback's: this one counts every start rather than every
    # failure, so its ceiling has to sit well above whatever a shared office NAT produces.
    await enforce_oidc_start_rate_limit(redis, ip=client_ip(request))

    if not oidc_configured():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_OIDC_DETAIL)

    # One value, three jobs: the OAuth2 `state` parameter, the cookie that binds the
    # flow to this browser, and (hashed) the key of the row holding the nonce and PKCE
    # verifier. Requiring the parameter and the cookie to match on the way back is what
    # stops an attacker starting a flow and feeding a victim its callback url, which
    # would otherwise sign the victim into the attacker's account.
    state = generate_token()
    try:
        url, nonce, code_verifier = await oidc_core.begin(state=state)
    except OidcError:
        # An unreachable or misconfigured provider. Logged inside core/oidc.py; there is
        # no session to protect yet, so this is the one place a plain redirect with no
        # audit entry is right - nobody has attempted to authenticate as anyone.
        logger.warning("SSO start failed: could not reach the provider")
        return _login_redirect(ERROR_PROVIDER)

    session.add(
        OidcLoginState(
            state_hash=hash_token(state),
            nonce=nonce,
            code_verifier=code_verifier,
            return_to=_safe_return_to(return_to),
            expires_at=datetime.now(UTC) + OIDC_STATE_TTL,
        )
    )
    # Opportunistic sweep, as login does for auth tokens. This table needs it more than
    # most: every abandoned sign-on leaves a row, and abandoning is a click away.
    await purge_expired_oidc_states(session)
    await session.commit()

    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(
        response,
        state,
        name=OIDC_STATE_COOKIE_NAME,
        max_age=int(OIDC_STATE_TTL.total_seconds()),
    )
    return response


async def _consume_state(
    session: SessionDep, request: Request, state: str | None
) -> tuple[str, str, str | None] | None:
    """Claim the flow's state row, returning its `(nonce, code_verifier, return_to)`, or
    None if it does not check out.

    Three separate checks, and each stops something different:

    - The **cookie must equal the query parameter**. That is the browser binding, and it is
      what defeats login CSRF: without it an attacker starts their own flow and feeds the
      victim its callback url, landing the victim in the attacker's session. `compare_digest`
      because the caller controls the parameter while the cookie is httpOnly, so a
      short-circuiting comparison is the one thing here that leaks anything about a value
      they cannot otherwise read.
    - The **hash must resolve to a live row**, which is what the two cookies of two
      concurrent flows cannot fake.
    - The row is **claimed by a single DELETE ... RETURNING**, which makes a flow single-use
      so a callback url captured from a history or a proxy log is worthless. One statement
      rather than a SELECT then a delete, because the gap between those two is a race: two
      callbacks carrying one state would both pass the SELECT, and the loser's delete would
      match zero rows and raise `StaleDataError` - an unhandled 500 where a clean refusal
      belongs. A double-click on a slow callback, or a prefetcher, is enough to reach it.
      With `DELETE ... RETURNING` exactly one of them gets a row and the other gets none,
      which is already the refusal path.

    The commit is deliberately *here* rather than left to the caller. The caller's next move
    is `oidc_core.complete()`, which makes up to five calls to the provider: holding the
    transaction across that would park a pooled connection for the whole time a degraded
    provider takes to answer, so a slow IdP would exhaust the pool and take the rest of the
    API down with it rather than only sign-in.

    Returns the values rather than an ORM object for the same reason: the row no longer
    exists, so there is nothing to read attributes off.
    """
    cookie = request.cookies.get(OIDC_STATE_COOKIE_NAME)
    if not state or not cookie or not secrets.compare_digest(state, cookie):
        return None
    result = await session.execute(
        delete(OidcLoginState)
        .where(
            OidcLoginState.state_hash == hash_token(state),
            OidcLoginState.expires_at > datetime.now(UTC),
        )
        .returning(
            OidcLoginState.nonce,
            OidcLoginState.code_verifier,
            OidcLoginState.return_to,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    await session.commit()
    return (row.nonce, row.code_verifier, row.return_to)


async def _find_linked_user(session: SessionDep, identity: OidcIdentity) -> User | None:
    result = await session.execute(
        select(User).where(
            User.oidc_issuer == identity.issuer,
            User.oidc_subject == identity.subject,
        )
    )
    return result.scalar_one_or_none()


@router.get("/callback")
async def callback(
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish a sign-on: verify what the provider said, then decide who that is here."""
    ip = client_ip(request)
    await enforce_oidc_rate_limit(redis, ip=ip)

    if not oidc_configured():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_OIDC_DETAIL)

    # The provider can refuse on its own (the user cancelled, the client is unknown), in
    # which case there is no code to exchange. Its `error` is not echoed to the browser:
    # it is provider vocabulary, not ours.
    if error:
        # %r, because this is a raw query parameter on an unauthenticated endpoint: a bare
        # %s would let a CR or LF in it forge a second log record. record_event scrubs the
        # copy that reaches the audit line; this is the other place the same string is logged.
        logger.info("SSO callback: provider returned error=%r", error)
        return await _refuse(session, redis, code=ERROR_PROVIDER, ip=ip, reason=f"provider {error}")

    claimed = await _consume_state(session, request, state)
    if claimed is None or not code:
        return await _refuse(session, redis, code=ERROR_STATE, ip=ip, reason="bad state")
    nonce, code_verifier, return_to = claimed

    try:
        identity = await oidc_core.complete(code=code, code_verifier=code_verifier, nonce=nonce)
    except OidcError as exc:
        logger.warning("SSO callback rejected: %s", exc)
        return await _refuse(session, redis, code=ERROR_PROVIDER, ip=ip, reason="verify failed")

    # Both go into varchar(255) columns further down, so an over-long value would surface as a
    # DataError on the commit - a 500 out of the callback where a refusal belongs. Refused
    # rather than truncated, because a truncated subject is a *different* identity and could
    # collide with somebody else's.
    if len(identity.subject) > 255 or len(identity.issuer) > 255:
        logger.warning("SSO refused: the provider's subject or issuer exceeds 255 characters")
        return await _refuse(session, redis, code=ERROR_PROVIDER, ip=ip, reason="identity too long")

    user = await _find_linked_user(session, identity)

    if user is None:
        # A first sign-on: match the provider's email to a local account. This is the
        # only moment email is trusted for identity, so it is the moment the
        # email_verified rule has to hold.
        if not identity.email:
            return await _refuse(
                session, redis, code=ERROR_NO_ACCOUNT, ip=ip, reason="no email claim"
            )

        # Only enforced when the server itself says it cares about verified addresses.
        # With "require email confirmation" off, accounts are created active without
        # anyone proving an address, so demanding proof here would make SSO stricter
        # than every other way into the same account - and would refuse providers that
        # simply omit the claim, for a server that never wanted it.
        app_settings = await get_app_settings(session)
        if app_settings.require_confirmation and not identity.email_verified:
            return await _refuse(
                session,
                redis,
                code=ERROR_EMAIL_UNVERIFIED,
                ip=ip,
                reason="email unverified",
                email=identity.email,
            )

        result = await session.execute(select(User).where(User.email == identity.email))
        user = result.scalar_one_or_none()
        if user is None:
            # No self-registration, here as everywhere else: admins create accounts. A
            # provider that authenticates the whole company does not get to populate
            # this app with everyone in it.
            return await _refuse(
                session,
                redis,
                code=ERROR_NO_ACCOUNT,
                ip=ip,
                reason="no account",
                email=identity.email,
            )
        if user.oidc_subject is not None and user.oidc_subject != identity.subject:
            # The address matches an account already linked to a *different* external
            # identity. Re-linking on the strength of an email would be an account
            # takeover primitive, so this refuses and leaves the existing link alone.
            logger.warning("SSO refused: %s is already linked to another identity", identity.email)
            return await _refuse(
                session,
                redis,
                code=ERROR_ALREADY_LINKED,
                ip=ip,
                reason="already linked",
                email=identity.email,
            )

    if user.status == UserStatus.disabled:
        # Deactivation is a real soft delete. The provider does not get to overrule it.
        return await _refuse(
            session, redis, code=ERROR_ACCOUNT_DISABLED, ip=ip, reason="disabled", email=user.email
        )

    if user.status == UserStatus.waiting_confirmation:
        # An admin created them and the confirmation email never landed, or they never
        # clicked it. Signing in through the provider proves the same thing that link
        # was there to prove - that the address reaches them - so it finishes the job
        # rather than leaving them stuck behind an SMTP relay they cannot fix.
        user.status = UserStatus.active
        user.confirmed_at = datetime.now(UTC)
        # ...and the outstanding link has to go with it, which every other path that
        # activates or re-secures an account already does (confirm_account,
        # update_user's deactivation, cli's _restore_admin). Without this the account is
        # now live AND still carries a token that `POST /confirm/{token}` will honour with
        # no status guard, letting whoever holds that email - an old address, a shared
        # inbox, a mail archive, which is precisely the case above - set a password on it
        # and sign in. The 24-hour TTL bounds the window; it does not close it.
        await session.execute(delete(ConfirmationToken).where(ConfirmationToken.user_id == user.id))

    # Persist the link, so every later sign-in matches on the durable subject and keeps
    # working when the address changes at the provider.
    user.oidc_issuer = identity.issuer
    user.oidc_subject = identity.subject

    # NOTE: totp_enabled is deliberately not consulted. This reads like an omission and
    # is a decision: the provider owns authentication, including whatever MFA it
    # enforces, so re-challenging for a local TOTP code here would ask the same person
    # to prove themselves twice with no gain. Local two-step verification still applies
    # in full to password sign-in, which is the only place it is offered.
    token = await open_session(session, user, remember=True, ip=ip, detail="oidc")
    await session.commit()

    target = _safe_return_to(return_to) or "/"
    redirect = RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}{target}", status_code=status.HTTP_302_FOUND
    )
    # Remembered unconditionally: there is no checkbox in this flow, and what is being
    # remembered is really the provider session behind it.
    mint_session(redirect, token, remember=True)
    clear_auth_cookie(redirect, OIDC_STATE_COOKIE_NAME)
    return redirect
