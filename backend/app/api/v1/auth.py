from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.api.deps import (
    CurrentUser,
    RedisDep,
    SessionDep,
    get_impersonator,
    get_request_token,
    get_user_by_token,
)
from app.core.app_settings import get_app_settings
from app.core.audit import record_event
from app.core.config import settings
from app.core.crypto import crypto_configured
from app.core.households import memberships_for
from app.core.oidc import oidc_configured
from app.core.rate_limit import (
    clear_login_failures,
    clear_two_factor_failures,
    client_ip,
    enforce_login_rate_limit,
    enforce_two_factor_rate_limit,
    record_login_failure,
    record_two_factor_failure,
)
from app.core.security import (
    ADMIN_COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    SESSION_TOKEN_TTL,
    TOKEN_TTL,
    TWO_FACTOR_COOKIE_NAME,
    TWO_FACTOR_TTL,
    clear_auth_cookie,
    generate_token,
    hash_token,
    set_auth_cookie,
    verify_password,
)
from app.core.tokens import purge_expired_tokens, purge_expired_two_factor_challenges
from app.core.two_factor import consume_valid_code
from app.models import AuditAction, AuthToken, TwoFactorChallenge, User, UserStatus
from app.schemas import (
    AuthMethodsRead,
    LoginRequest,
    LoginResponse,
    MeRead,
    TwoFactorVerifyRequest,
    UserRead,
)
from app.schemas.user import MembershipRead

# Refused when a user has 2FA enabled but the server can't decrypt the seed
# (APP_KEY unset/invalid). Fail closed: never let a 2FA account in on password
# alone.
_TWO_FACTOR_UNAVAILABLE_DETAIL = "Two-factor authentication is temporarily unavailable"

# Refused when the deployment has made its identity provider the only way in
# (OIDC_ONLY). Deliberately has no exemption, not even for admins: an is_admin
# carve-out would make the response tell an anonymous caller whether an address
# belongs to an admin, and recovering a broken provider is an operator action
# (set OIDC_ONLY back to false and restart) rather than an in-app one.
_PASSWORD_LOGIN_DISABLED_DETAIL = "Password sign-in is disabled on this server"

# Stand-in label when OIDC_PROVIDER_NAME is set to the empty string. Matches the Settings
# default, so an unset var and a blank one look the same to a client. Mirrored on the
# frontend (`FALLBACK_PROVIDER_NAME` in pages/Login.tsx), which keeps its own copy because a
# client cannot assume which server version it is talking to.
DEFAULT_PROVIDER_NAME = "SSO"

router = APIRouter()


def mint_session(response: Response, token: str, *, remember: bool) -> None:
    """Set the auth cookie for a freshly minted session and drop any parked
    admin cookie. Shared by the single-step login, the 2FA verify step and the
    SSO callback."""
    set_auth_cookie(
        response,
        token,
        # Persistent when remembering, a browser-session cookie otherwise (same
        # source as the DB token TTL).
        max_age=int(TOKEN_TTL.total_seconds()) if remember else None,
    )
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)


async def open_session(
    session: SessionDep,
    user: User,
    *,
    remember: bool,
    ip: str | None,
    detail: str | None = None,
) -> str:
    """Stage a new auth token for `user` and record the successful login, returning
    the raw token.

    The three ways into the app (password, password + 2FA code, SSO callback) differ
    entirely in how they decide *whether* to let someone in and agree completely on
    what happens once they have: same token, same TTL rule, same audit action, same
    opportunistic sweep. That agreement is what lives here.

    Deliberately does NOT commit, and does not touch the response: the caller owns the
    transaction (the 2FA path has a challenge row to delete in the same one) and calls
    `mint_session` after committing, so a failed commit cannot hand out a cookie for a
    session that does not exist.
    """
    # "Remember me" opts into a persistent session (long-lived cookie + token);
    # otherwise it's a browser-session cookie capped by a short token TTL.
    ttl = TOKEN_TTL if remember else SESSION_TOKEN_TTL
    token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await record_event(
        session, action=AuditAction.login_success, actor_id=user.id, ip=ip, detail=detail
    )
    # Opportunistically clean out expired tokens so the table stays bounded (L1)
    await purge_expired_tokens(session)
    return token


async def _me_read(session: SessionDep, user: User, *, impersonating: bool = False) -> MeRead:
    """The signed-in user as every endpoint that hands one back reports them: with their
    household memberships, and whether this server asks for email confirmation.

    Login, the second 2FA step and /auth/me all go through this so a client can never hold
    a session whose roles are missing. The sidebar decides what to show from `memberships`,
    so a login response without them would render the minimal nav until the next reload -
    and it is the login path, not the reload, that most users see first. The confirmation
    flag rides along for the same reason in miniature: Profile reads it against the
    `confirmed_at` in this same payload, so arriving separately would let the two disagree."""
    memberships = [
        MembershipRead(household_id=m.household_id, role=m.role, owned=m.owned)
        for m in await memberships_for(session, user.id)
    ]
    # One primary-key lookup on a single-row table, per call. `session.get` consults the
    # identity map first, but nothing else on these three paths loads that row, so in
    # practice it is a SELECT rather than a hit - cheap, but not free.
    app_settings = await get_app_settings(session)
    return MeRead.model_validate(user).model_copy(
        update={
            "impersonating": impersonating,
            "memberships": memberships,
            "email_confirmation_required": app_settings.require_confirmation,
        }
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    response: Response,
) -> LoginResponse:
    # Gated on the provider actually being usable, not on the flag alone: OIDC_ONLY
    # with no configured provider is a total lockout, and while the startup check
    # refuses to boot on that combination outside a dev environment, dev is exempt
    # from every startup check. Without this second clause a developer who set the
    # flag and nothing else would lock themselves out of their own stack with no
    # error explaining why.
    if settings.oidc_only and oidc_configured():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_PASSWORD_LOGIN_DISABLED_DETAIL
        )

    ip = client_ip(request)
    # payload.email is already lower-cased by the schema (L3); keep the explicit
    # .lower() so the throttle key stays case-insensitive regardless.
    email = payload.email.lower()
    await enforce_login_rate_limit(redis, email=email, ip=ip)

    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    password_ok = verify_password(
        payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok or user.status != UserStatus.active:
        await record_login_failure(redis, email=email, ip=ip)
        # Persist the failed attempt (actor unknown; the attempted email goes in
        # detail) even though the request itself fails with 401.
        await record_event(session, action=AuditAction.login_failed, ip=ip, detail=email)
        await session.commit()
        # One message for every failure mode so emails can't be enumerated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    if user.totp_enabled:
        # Password is correct, but the account is protected: don't mint a session
        # yet. Fail closed if the seed can't be decrypted (no session on a bare
        # password), otherwise park a short-lived challenge and ask for the code.
        if not crypto_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_TWO_FACTOR_UNAVAILABLE_DETAIL,
            )
        challenge_token = generate_token()
        session.add(
            TwoFactorChallenge(
                token_hash=hash_token(challenge_token),
                user_id=user.id,
                remember=payload.remember,
                expires_at=datetime.now(UTC) + TWO_FACTOR_TTL,
            )
        )
        await purge_expired_two_factor_challenges(session)
        await session.commit()
        # Deliberately do NOT clear the login failure counter here: the login
        # isn't complete until the code is verified, and clearing now would let
        # someone who only has the password reset the throttle at will.
        set_auth_cookie(
            response,
            challenge_token,
            name=TWO_FACTOR_COOKIE_NAME,
            max_age=int(TWO_FACTOR_TTL.total_seconds()),
        )
        return LoginResponse(two_factor_required=True)

    token = await open_session(session, user, remember=payload.remember, ip=ip)
    await session.commit()

    await clear_login_failures(redis, email=email)
    mint_session(response, token, remember=payload.remember)
    return LoginResponse(user=await _me_read(session, user))


@router.post("/verify-2fa", response_model=MeRead)
async def verify_two_factor(
    payload: TwoFactorVerifyRequest,
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    response: Response,
) -> MeRead:
    """Second step of a two-step login: verify the TOTP (or recovery) code
    against the challenge parked by /login, then mint the real session."""
    challenge_token = request.cookies.get(TWO_FACTOR_COOKIE_NAME)
    if not challenge_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No two-factor challenge in progress"
        )
    result = await session.execute(
        select(TwoFactorChallenge)
        .options(joinedload(TwoFactorChallenge.user))
        .where(
            TwoFactorChallenge.token_hash == hash_token(challenge_token),
            TwoFactorChallenge.expires_at > datetime.now(UTC),
        )
    )
    challenge = result.scalar_one_or_none()
    if challenge is None:
        # Unknown or expired: drop the stale cookie and send them back to login.
        clear_auth_cookie(response, TWO_FACTOR_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your two-factor challenge has expired. Please log in again.",
        )

    user = challenge.user
    ip = client_ip(request)
    # The account could have been disabled between the two steps.
    if user.status != UserStatus.active or user.totp_secret is None or not crypto_configured():
        clear_auth_cookie(response, TWO_FACTOR_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your two-factor challenge has expired. Please log in again.",
        )

    await enforce_two_factor_rate_limit(redis, user_id=user.id, ip=ip)
    if not await consume_valid_code(session, user, payload.code):
        await record_two_factor_failure(redis, user_id=user.id, ip=ip)
        await record_event(session, action=AuditAction.two_factor_failed, actor_id=user.id, ip=ip)
        await session.commit()
        # The challenge is intentionally left intact so a typo doesn't force a
        # fresh password entry; the throttle + short TTL bound the guessing.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code"
        )

    token = await open_session(session, user, remember=challenge.remember, ip=ip)
    await session.delete(challenge)
    await session.commit()

    await clear_login_failures(redis, email=user.email)
    await clear_two_factor_failures(redis, user_id=user.id)
    mint_session(response, token, remember=challenge.remember)
    clear_auth_cookie(response, TWO_FACTOR_COOKIE_NAME)
    return await _me_read(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, response: Response) -> None:
    # Ends both the current session and, when impersonating, the admin one
    token = get_request_token(request)
    actor = await get_user_by_token(session, token) if token else None
    # If impersonating, the real operator ends the session; record them too.
    impersonator = await get_impersonator(request, session)
    hashes = []
    if token:
        hashes.append(hash_token(token))
    if admin_token := request.cookies.get(ADMIN_COOKIE_NAME):
        hashes.append(hash_token(admin_token))
    if hashes:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash.in_(hashes)))
    await record_event(
        session,
        action=AuditAction.logout,
        actor_id=actor.id if actor else None,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    clear_auth_cookie(response)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)


@router.get("/methods", response_model=AuthMethodsRead)
async def auth_methods() -> AuthMethodsRead:
    """Which ways in the login page should offer. Public: the page that asks has nobody
    signed in yet, by definition.

    `password_enabled` reads the same condition as the 403 in `login` above, so the two
    cannot disagree - the form is never hidden while the endpoint works, nor offered
    while it refuses.
    """
    enabled = oidc_configured()
    return AuthMethodsRead(
        password_enabled=not (settings.oidc_only and enabled),
        oidc_enabled=enabled,
        # Never blank while enabled. `OIDC_PROVIDER_NAME=` in a .env arrives as "" - a
        # reachable config, since the name is cosmetic and deliberately not part of
        # oidc_configured() - and a client with a blank label has to choose between
        # rendering "Sign in with " and rendering nothing. Under OIDC_ONLY the second is a
        # login page with no way in at all, so the invariant is established here instead:
        # enabled implies a usable name.
        oidc_provider_name=(settings.oidc_provider_name.strip() or DEFAULT_PROVIDER_NAME)
        if enabled
        else None,
    )


@router.get("/me", response_model=MeRead)
async def me(request: Request, user: CurrentUser, session: SessionDep) -> MeRead:
    impersonating = await get_impersonator(request, session) is not None
    return await _me_read(session, user, impersonating=impersonating)


@router.post("/stop-impersonating", response_model=UserRead)
async def stop_impersonating(
    request: Request, session: SessionDep, response: Response
) -> User | Response:
    admin_token = request.cookies.get(ADMIN_COOKIE_NAME)
    if admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No impersonation in progress"
        )

    admin = await get_user_by_token(session, admin_token)
    current = get_request_token(request)
    if admin is None or not admin.is_admin:
        # The parked admin token has expired or is no longer valid. Rather than
        # strand the operator in the impersonated session (whose own cookie is
        # still live) with a bare, misleading 401, end both sessions and send
        # them back to login with a clear message (L5). A returned Response, not
        # a raised HTTPException, carries the cookie-clearing headers.
        target = await get_user_by_token(session, current) if current else None
        hashes = [hash_token(t) for t in {admin_token, current} if t]
        await session.execute(delete(AuthToken).where(AuthToken.token_hash.in_(hashes)))
        # Keep the audit trail closed: the impersonate_start would otherwise have
        # no matching stop. The operator's session expired, so the actor is
        # unknown; the impersonated target is still resolvable from its cookie.
        await record_event(
            session,
            action=AuditAction.impersonate_stop,
            target_id=target.id if target else None,
            ip=client_ip(request),
            detail="admin session expired",
        )
        await session.commit()
        expired = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Your admin session has expired. Please log in again."},
        )
        clear_auth_cookie(expired)
        clear_auth_cookie(expired, ADMIN_COOKIE_NAME)
        return expired

    # Drop the impersonated session and restore the admin one
    target = await get_user_by_token(session, current) if current else None
    if current and current != admin_token:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(current)))
    await record_event(
        session,
        action=AuditAction.impersonate_stop,
        actor_id=admin.id,
        target_id=target.id if target else None,
        ip=client_ip(request),
    )
    await session.commit()

    set_auth_cookie(response, admin_token)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)
    return admin
