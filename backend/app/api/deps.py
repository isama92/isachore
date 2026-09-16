from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie, HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.api_tokens import api_token_user, is_api_token
from app.core.households import member_household_ids
from app.core.security import ADMIN_COOKIE_NAME, COOKIE_NAME, hash_token
from app.db.redis import get_redis
from app.db.session import get_session
from app.models import AuthToken, Household, HouseholdRole, User, UserStatus

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)
_api_token_exc = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail=(
        "A personal access token cannot be used here. This operation needs a signed-in "
        "session; the ones an access token may call are those listed with the apiToken "
        "scheme in the API reference."
    ),
)

# The four credentials the API accepts, declared as OpenAPI security schemes. They are the
# only way the generator learns a route is gated: FastAPI derives securitySchemes and
# per-operation `security` from SecurityBase dependencies alone, and without them every gated
# operation publishes itself as anonymous, so a client generated from docs/api/openapi.yaml
# sends no credentials at all.
#
# Three of them are transports get_request_token reads. `apiToken` is not: it is a different
# CREDENTIAL that happens to share the bearer header, read by bearer_token and resolved
# against a different table, and the operations carrying it are an allowlist (see
# api/v1/router.py).
#
# All are auto_error=False, which is what makes them inert: they are read for the document,
# never for the decision. Deciding stays in get_request_token, because four routes call it
# outside the dependency system (auth.py, profile.py, admin_users.py) and the
# cookie-before-bearer precedence has to be written down exactly once.
#
# X-CSRF-Token is deliberately NOT one of these. FastAPI emits one `security` entry per
# scheme and OpenAPI reads separate entries as alternatives, so adding it would publish
# "session cookie OR csrf header" - the opposite of what core/csrf.py enforces, which is both
# together. It is described in the API description (main.py) instead, and
# tests/test_openapi_security.py pins this scheme set closed so it cannot drift back in.
session_cookie_scheme = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="sessionCookie",
    auto_error=False,
    description=(
        "The httpOnly session cookie, set by `POST /api/v1/auth/login` or by the single "
        "sign-on callback. A browser sends it automatically; an unsafe method additionally "
        "needs the `X-CSRF-Token` header."
    ),
)
bearer_scheme = HTTPBearer(
    scheme_name="bearerToken",
    auto_error=False,
    description=(
        "The same opaque session token as an `Authorization: Bearer` header, for clients "
        "with no cookie jar. Exempt from the `X-CSRF-Token` requirement."
    ),
)
admin_cookie_scheme = APIKeyCookie(
    name=ADMIN_COOKIE_NAME,
    scheme_name="parkedAdminCookie",
    auto_error=False,
    description=(
        "An impersonating administrator's own session, parked while they act as somebody "
        "else. `POST /api/v1/auth/stop-impersonating` is the only route it *authenticates* "
        "- several others read it to attribute an action to the real operator, and logout "
        "reads it to end both sessions."
    ),
)
api_token_scheme = HTTPBearer(
    scheme_name="apiToken",
    auto_error=False,
    description=(
        "A personal access token, `Authorization: Bearer isac_...`, generated on the Profile "
        "page. One per account, it never expires, and it is accepted only on the operations "
        "that publish this scheme - anywhere else it answers 403. Header only: the same value "
        "in a cookie authenticates nobody, which is also why a request carrying one needs no "
        "`X-CSRF-Token`."
    ),
)


def bearer_token(request: Request) -> str | None:
    """The `Authorization: Bearer` value, ignoring cookies entirely.

    Separate from get_request_token because a personal access token is a HEADER
    credential by construction: the same string in a cookie must authenticate nobody,
    which is what keeps core/csrf.py's reasoning intact.
    """
    scheme, _, param = request.headers.get("Authorization", "").partition(" ")
    return param if scheme.lower() == "bearer" and param else None


def get_request_token(request: Request) -> str | None:
    """Raw auth token from the session cookie or an Authorization: Bearer header.

    It returns a personal access token too, and must keep doing so: get_current_user
    below can only tell "a real access token, used where it is not accepted" from
    "a string that authenticates nothing" if it sees the value. Filtering the prefix
    out here instead would turn the first into a 401 and, because logout reads this
    function directly, would change what an access token does there as well.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token
    return bearer_token(request)


async def get_user_by_token(session: AsyncSession, token: str) -> User | None:
    """Resolve a raw SESSION token to its active user, or None if invalid/expired/inactive.

    Sessions only. get_impersonator calls this against the parked admin cookie, so an
    access token resolved here would become an impersonation credential the moment
    somebody pasted one into isachore_admin_token. core/api_tokens.py owns that lookup.
    """
    result = await session.execute(
        select(AuthToken)
        .options(joinedload(AuthToken.user))
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.expires_at > datetime.now(UTC),
        )
    )
    auth_token = result.scalar_one_or_none()
    if auth_token is None or auth_token.user.status != UserStatus.active:
        return None
    return auth_token.user


async def get_current_user(
    request: Request,
    session: SessionDep,
    _cookie: Annotated[str | None, Security(session_cookie_scheme)] = None,
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
) -> User:
    # _cookie and _bearer are documentation, not input: they put the two schemes into this
    # route's dependency tree, which is the whole mechanism behind the `security` block on
    # every gated operation. Both are auto_error=False, so neither can refuse anything, and
    # the read below stays the only one that decides.
    token = get_request_token(request)
    if token is not None and is_api_token(token):
        # A real credential in the wrong place is 403, not 401: presenting different
        # credentials of the same kind is not the fix, so saying "not authenticated"
        # would send the caller round a loop. A string that merely looks like one falls
        # through to the 401 below.
        #
        # The equality asks "did this arrive in the header?", because a token in a cookie
        # authenticates nobody anywhere. It holds when the header was the only source, and
        # also when cookie and header carry the SAME string - which is fine, since 403 and
        # 401 both refuse. It fails, giving the 401, when a cookie holds some other
        # isac_ value, because get_request_token prefers the cookie.
        if bearer_token(request) == token and await api_token_user(session, token):
            raise _api_token_exc
        raise _credentials_exc
    user = await get_user_by_token(session, token) if token else None
    if user is None:
        raise _credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_api_user(
    request: Request,
    session: SessionDep,
    _cookie: Annotated[str | None, Security(session_cookie_scheme)] = None,
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    _api_token: Annotated[HTTPAuthorizationCredentials | None, Security(api_token_scheme)] = None,
) -> User:
    """A session OR a personal access token, for the operations an access token may call.

    All three Security parameters are load-bearing documentation and none may be dropped:
    they are what puts three schemes on each of these operations, and an operation that
    lost the two session ones would publish itself as reachable by access token alone
    while still accepting a session. tests/test_openapi_security.py pins all three.

    The access-token branch reads the HEADER only, so a token in the session cookie
    authenticates nobody here either - and note that this branch therefore prefers the header
    where get_current_user prefers the cookie. A request carrying a session cookie for one
    account and an access token for another is that asymmetry made visible: it acts as the
    token's owner here and as the cookie's owner everywhere else. Harmless (no CORS, and a
    cross-site request cannot set Authorization), but it is why the two are not the same rule.

    Everything that is NOT an access token - both session transports, their
    cookie-before-bearer precedence, the 401 - is get_current_user's, unduplicated.
    """
    token = bearer_token(request)
    if token is not None and is_api_token(token):
        user = await api_token_user(session, token)
        if user is None:
            raise _credentials_exc
        return user
    return await get_current_user(request, session)


ApiUser = Annotated[User, Depends(get_api_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def get_impersonator(request: Request, session: SessionDep) -> User | None:
    """The real admin behind an impersonation session (from the parked admin
    cookie), or None when not impersonating."""
    admin_token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not admin_token:
        return None
    admin = await get_user_by_token(session, admin_token)
    return admin if admin is not None and admin.is_admin else None


Impersonator = Annotated[User | None, Depends(get_impersonator)]


async def get_current_household(
    user: CurrentUser, session: SessionDep, min_role: HouseholdRole | None = None
) -> Household:
    """The current user's active household, lowest id first, as a fallback for
    callers that take no explicit household_id.

    Being a member of none is a normal state (nothing provisions a household), so
    the 404 below is a routine answer rather than an anomaly, and callers with a UI
    are expected to check first. Excludes soft-deleted households so the fallback
    stays consistent with get_member_household and the /households list (which both
    hide deleted ones). `min_role` narrows it to the households where the caller's role
    grants that much, so the fallback cannot hand back one they may not act in.

    Call this directly, never through `Depends`: `min_role` is a plain scalar with a default,
    so FastAPI would resolve it as a query parameter and publish a permission helper's floor
    as client input. It only ever narrows, so that would fail closed rather than escalate, but
    there is no reason to offer it. There used to be a `CurrentHousehold` annotated alias here
    for exactly that; it had no callers and was removed."""
    result = await session.execute(
        select(Household)
        .where(Household.id.in_(member_household_ids(user.id, min_role)))
        .order_by(Household.id)
        .limit(1)
    )
    household = result.scalar_one_or_none()
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "You are not a member of any household"
                if min_role is None
                else f"You are not a household {min_role} anywhere"
            ),
        )
    return household
