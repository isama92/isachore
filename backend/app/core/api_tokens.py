"""Minting, reading and revoking a user's personal access token.

In `core/` rather than beside the routes because four callers need it: the
`/profile/api-token` endpoints, the admin revoke endpoint, `app/cli.py`'s admin
recovery, and `api/deps.py`, which resolves the credential on every request.
Putting the lookup in a router would make `deps.py` import one.

Function names here are deliberately disjoint from `api/v1/api_tokens.py`'s:
`tests/test_openapi_refusals.py` merges `core/*.py` and `api/v1/*.py` into one
symbol table, so a shared name shadows.
"""

import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.security import API_TOKEN_PREFIX, hash_token
from app.models import ApiToken, User, UserStatus
from app.schemas import ApiTokenRead, ApiTokenStatusRead


def new_api_token() -> str:
    """A fresh personal access token. Handed to the user once; only its hash is stored."""
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def is_api_token(token: str) -> bool:
    """Whether a presented credential is a personal access token rather than a session one.

    Exact, not a guess: generate_token refuses to mint a session token with this prefix, so
    a true answer means the caller presented something only new_api_token can produce. It
    still says nothing about whether that something is valid.
    """
    return token.startswith(API_TOKEN_PREFIX)


async def api_token_user(session: AsyncSession, token: str) -> User | None:
    """Resolve a raw personal access token to its active user, or None.

    Deliberately separate from `deps.get_user_by_token` rather than folded into it:
    that one is also called against the parked admin cookie, so a shared lookup would
    let an access token pasted into `isachore_admin_token` become an impersonation
    credential. Two functions make that unrepresentable.

    No expiry clause, because there is no expires_at. The account status check is the
    whole of the lifecycle: deactivating a user makes their token inert without
    deleting the row.
    """
    result = await session.execute(
        select(ApiToken)
        .options(joinedload(ApiToken.user))
        .where(ApiToken.token_hash == hash_token(token))
    )
    api_token = result.scalar_one_or_none()
    if api_token is None or api_token.user.status != UserStatus.active:
        return None
    return api_token.user


async def load_api_token(session: AsyncSession, user_id: int) -> ApiToken | None:
    """The user's access token row, or None. Never carries the token itself: only the
    hash is stored, so the plaintext exists nowhere after creation answers."""
    result = await session.execute(select(ApiToken).where(ApiToken.user_id == user_id))
    return result.scalar_one_or_none()


async def api_token_status(session: AsyncSession, user_id: int) -> ApiTokenStatusRead:
    """What an owner or an administrator may learn about a token: that it exists, and when.

    One function for both, so the two answers cannot drift. They are the same question asked
    by different people, and the admin view is exactly where a divergence would go unnoticed.
    """
    api_token = await load_api_token(session, user_id)
    return ApiTokenStatusRead(
        token=ApiTokenRead.model_validate(api_token) if api_token is not None else None
    )


async def revoke_api_token(session: AsyncSession, user_id: int) -> bool:
    """Delete the user's access token, reporting whether there was one.

    Does not commit, so a caller that revokes as part of a larger change gets one
    atomic outcome. The boolean is what lets the delete endpoint answer 404 without a
    second query.
    """
    result = await session.execute(delete(ApiToken).where(ApiToken.user_id == user_id))
    return bool(result.rowcount)
