import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, or_, select

from app.api.deps import AdminUser, Impersonator, SessionDep, get_request_token
from app.core.app_settings import get_app_settings
from app.core.audit import record_event
from app.core.email import NO_SMTP_DETAIL, send_confirmation_email, smtp_configured
from app.core.households import add_to_default_household
from app.core.rate_limit import client_ip
from app.core.security import (
    ADMIN_COOKIE_NAME,
    CONFIRMATION_TOKEN_TTL,
    TOKEN_TTL,
    generate_token,
    hash_password,
    hash_token,
    set_auth_cookie,
)
from app.models import AuditAction, AuthToken, ConfirmationToken, User, UserStatus
from app.schemas import Page, UserCreate, UserRead, UserUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_user_or_404(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _ensure_email_free(
    session: SessionDep, email: str, exclude_id: int | None = None
) -> None:
    query = select(User.id).where(User.email == email)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    if (await session.execute(query)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )


async def _revoke_tokens(session: SessionDep, user_id: int) -> None:
    await session.execute(delete(AuthToken).where(AuthToken.user_id == user_id))


async def _revoke_confirmation_tokens(session: SessionDep, user_id: int) -> None:
    """Delete a user's confirmation tokens. Called when they are disabled so a
    still-valid emailed link can't flip a suspended account back to active."""
    await session.execute(delete(ConfirmationToken).where(ConfirmationToken.user_id == user_id))


async def _issue_confirmation_token(session: SessionDep, user_id: int) -> str:
    """Replace any existing confirmation tokens for the user with a fresh one so
    only the latest emailed link works, and return the raw token to email."""
    await session.execute(delete(ConfirmationToken).where(ConfirmationToken.user_id == user_id))
    raw = generate_token()
    session.add(
        ConfirmationToken(
            token_hash=hash_token(raw),
            user_id=user_id,
            expires_at=datetime.now(UTC) + CONFIRMATION_TOKEN_TTL,
        )
    )
    return raw


def _protected_self_ids(admin: User, impersonator: User | None) -> set[int]:
    """Ids that may never demote/deactivate themselves. During impersonation
    that means the impersonated session AND the real operator behind the parked
    admin cookie, so the self-guard can't be bypassed by proxy."""
    return {admin.id} if impersonator is None else {admin.id, impersonator.id}


# Whitelisted sort keys (deliberately never role/status) and directions for the
# users list, plus the role filter values. Literals both document the closed set
# and make an unknown value a 422 at the query-param layer.
UserSortBy = Literal["id", "name", "email", "created_at"]
SortDir = Literal["asc", "desc"]
RoleFilter = Literal["admins", "members"]

# The column(s) each sort key maps to; "name" spans both name fields.
_SORT_COLUMNS = {
    "id": (User.id,),
    "name": (User.first_name, User.last_name),
    "email": (User.email,),
    "created_at": (User.created_at,),
}


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search term is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=Page[UserRead])
async def list_users(
    _: AdminUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: UserSortBy = "created_at",
    sort_dir: SortDir = "desc",
    name: Annotated[str | None, Query(max_length=255)] = None,
    email: Annotated[str | None, Query(max_length=255)] = None,
    # Named status_filter (not status) so it doesn't shadow the imported fastapi
    # `status` module; the query-string key stays `status` via the alias.
    status_filter: Annotated[UserStatus | None, Query(alias="status")] = None,
    role: RoleFilter | None = None,
) -> Page[UserRead]:
    # Filters combine with AND; name searches first OR last name. Absent/empty
    # filters are simply not applied (the frontend sends nothing for "All").
    filters = []
    if name and name.strip():
        pattern = f"%{_escape_like(name.strip())}%"
        filters.append(or_(User.first_name.ilike(pattern), User.last_name.ilike(pattern)))
    if email and email.strip():
        filters.append(User.email.ilike(f"%{_escape_like(email.strip())}%"))
    if status_filter is not None:
        filters.append(User.status == status_filter)
    if role == "admins":
        filters.append(User.is_admin.is_(True))
    elif role == "members":
        filters.append(User.is_admin.is_(False))

    count_query = select(func.count()).select_from(User)
    list_query = select(User)
    if filters:
        count_query = count_query.where(*filters)
        list_query = list_query.where(*filters)

    total = await session.scalar(count_query) or 0

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in _SORT_COLUMNS[sort_by]]
    # Deterministic tiebreaker so paging is stable when the sort key ties.
    order_by.append(User.id.desc() if descending else User.id.asc())

    result = await session.execute(
        list_query.order_by(*order_by).limit(page_size).offset((page - 1) * page_size)
    )
    return Page[UserRead](
        items=[UserRead.model_validate(user) for user in result.scalars()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, _: AdminUser, session: SessionDep) -> User:
    return await _get_user_or_404(session, user_id)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    await _ensure_email_free(session, payload.email)
    app_settings = await get_app_settings(session)

    confirm_token: str | None = None
    if app_settings.require_confirmation:
        # Defensive: enabling the setting already requires SMTP, but re-check so
        # a later env change can't leave users stranded with no way to confirm.
        if not smtp_configured():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_SMTP_DETAIL)
        # The user sets their own password via the emailed link, so any password
        # in the payload is ignored; store an unusable random placeholder to
        # satisfy the NOT NULL column and keep login impossible until confirmed.
        user = User(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password_hash=hash_password(generate_token()),
            is_admin=payload.is_admin,
            status=UserStatus.waiting_confirmation,
        )
    else:
        if not payload.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A password is required when confirmation is disabled",
            )
        user = User(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password_hash=hash_password(payload.password),
            is_admin=payload.is_admin,
            status=UserStatus.active,
            confirmed_at=datetime.now(UTC),
        )

    session.add(user)
    await session.flush()
    await add_to_default_household(session, user.id)
    if app_settings.require_confirmation:
        confirm_token = await _issue_confirmation_token(session, user.id)
    await record_event(
        session,
        action=AuditAction.user_created,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)

    # Best-effort: the account exists either way, and the admin can resend if the
    # email fails, so a transient SMTP error shouldn't fail the whole request.
    if confirm_token is not None:
        try:
            await send_confirmation_email(user, confirm_token)
        except Exception:
            logger.exception("Failed to send confirmation email to user %s", user.id)
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    user = await _get_user_or_404(session, user_id)

    demoting = payload.is_admin is False
    # Any move away from active (disabled or waiting_confirmation) counts as
    # deactivating for the self-guard and for token revocation.
    deactivating = payload.status is not None and payload.status != UserStatus.active
    if user.id in _protected_self_ids(admin, impersonator) and (demoting or deactivating):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot demote or deactivate yourself",
        )

    # Moving someone to waiting_confirmation is pointless without a way to email
    # them the link, so refuse it when SMTP isn't configured (like create/resend).
    if (
        payload.status == UserStatus.waiting_confirmation
        and user.status != UserStatus.waiting_confirmation
        and not smtp_configured()
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_SMTP_DETAIL)

    # Record the fields that actually changed (never the values, so a password
    # reset is audited without leaking the password).
    changed: list[str] = []
    to_waiting = False
    to_disabled = False
    if payload.email is not None and payload.email != user.email:
        await _ensure_email_free(session, payload.email, exclude_id=user.id)
        user.email = payload.email
        changed.append("email")
    if payload.first_name is not None and payload.first_name != user.first_name:
        user.first_name = payload.first_name
        changed.append("first_name")
    if payload.last_name is not None and payload.last_name != user.last_name:
        user.last_name = payload.last_name
        changed.append("last_name")
    if payload.is_admin is not None and payload.is_admin != user.is_admin:
        user.is_admin = payload.is_admin
        changed.append("is_admin")
    if payload.status is not None and payload.status != user.status:
        # Applied as-is (no coercion): an admin may force a never-confirmed user
        # active, which the UI surfaces as a warning. Moving a user to
        # waiting_confirmation triggers a fresh confirmation email below.
        to_waiting = payload.status == UserStatus.waiting_confirmation
        to_disabled = payload.status == UserStatus.disabled
        user.status = payload.status
        changed.append("status")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changed.append("password")

    confirm_token: str | None = None
    if to_waiting and smtp_configured():
        confirm_token = await _issue_confirmation_token(session, user.id)

    # Force re-login when credentials or access change
    if payload.password is not None or deactivating:
        await _revoke_tokens(session, user.id)
    # A disabled account must not be re-openable via a still-live emailed link.
    if to_disabled:
        await _revoke_confirmation_tokens(session, user.id)

    await record_event(
        session,
        action=AuditAction.user_updated,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
        detail=",".join(changed) or None,
    )
    await session.commit()
    await session.refresh(user)

    if confirm_token is not None:
        try:
            await send_confirmation_email(user, confirm_token)
        except Exception:
            logger.exception("Failed to send confirmation email to user %s", user.id)
    return user


@router.post("/{user_id}/impersonate", response_model=UserRead)
async def impersonate_user(
    user_id: int,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
    response: Response,
) -> User:
    user = await _get_user_or_404(session, user_id)
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You are already this user"
        )
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot log in as an inactive user"
        )

    current = get_request_token(request)
    parked_admin = request.cookies.get(ADMIN_COOKIE_NAME)

    token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + TOKEN_TTL,
        )
    )
    # Nested impersonation: the outermost admin stays parked in the admin cookie,
    # so the current (intermediate) session is about to lose its only cookie
    # reference. Revoke it rather than leave it valid for the full TTL (L2).
    if parked_admin and current and current != parked_admin:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(current)))
    # impersonator is set only for a nested impersonation; it records the
    # outermost operator so the chain traces back to a real admin.
    await record_event(
        session,
        action=AuditAction.impersonate_start,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()

    # Keep the outermost admin session for the return trip (don't overwrite it
    # when an impersonated admin impersonates someone else)
    if not parked_admin and current:
        set_auth_cookie(response, current, ADMIN_COOKIE_NAME)
    set_auth_cookie(response, token)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> None:
    user = await _get_user_or_404(session, user_id)
    if user.id in _protected_self_ids(admin, impersonator):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself"
        )
    user.status = UserStatus.disabled
    await _revoke_tokens(session, user.id)
    # Kill any outstanding confirmation link so a disabled account can't be
    # re-activated by whoever holds it.
    await _revoke_confirmation_tokens(session, user.id)
    await record_event(
        session,
        action=AuditAction.user_deactivated,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()


@router.post("/{user_id}/resend-confirmation", status_code=status.HTTP_204_NO_CONTENT)
async def resend_confirmation(
    user_id: int,
    _: AdminUser,
    session: SessionDep,
) -> None:
    user = await _get_user_or_404(session, user_id)
    if user.status != UserStatus.waiting_confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user is not awaiting confirmation",
        )
    if not smtp_configured():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_SMTP_DETAIL)
    # Commit the new token before sending so the emailed link is always valid;
    # a send failure then surfaces as 502 and the admin can retry.
    confirm_token = await _issue_confirmation_token(session, user.id)
    await session.commit()
    try:
        await send_confirmation_email(user, confirm_token)
    except Exception as exc:
        logger.exception("Failed to resend confirmation email to user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the confirmation email",
        ) from exc
