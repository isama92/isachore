from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from sqlalchemy import delete

from app.api.deps import CurrentUser, Impersonator, SessionDep, get_request_token
from app.core.audit import record_event
from app.core.avatars import delete_avatar, store_avatar
from app.core.config import settings
from app.core.rate_limit import client_ip
from app.core.security import hash_password, hash_token, verify_password
from app.models import AuditAction, AuthToken, User
from app.schemas import ProfileUpdate, UserRead

router = APIRouter()


@router.patch("", response_model=UserRead)
async def update_profile(
    payload: ProfileUpdate,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    """Update the current user's own name and/or password. Self-service edits
    reuse the user_updated audit action (actor == target); if an admin is doing
    this while impersonating, impersonator_id keeps the trail back to them."""
    changed: list[str] = []
    if payload.name is not None and payload.name != user.name:
        user.name = payload.name
        changed.append("name")

    if payload.new_password is not None:
        if not verify_password(payload.current_password or "", user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
        user.password_hash = hash_password(payload.new_password)
        changed.append("password")
        # Keep this device signed in but drop every other session for the user.
        current = get_request_token(request)
        stmt = delete(AuthToken).where(AuthToken.user_id == user.id)
        if current is not None:
            stmt = stmt.where(AuthToken.token_hash != hash_token(current))
        await session.execute(stmt)

    if changed:
        await record_event(
            session,
            action=AuditAction.user_updated,
            actor_id=user.id,
            target_id=user.id,
            impersonator_id=impersonator.id if impersonator else None,
            ip=client_ip(request),
            detail=",".join(changed),
        )
    await session.commit()
    await session.refresh(user)
    return user


@router.put("/avatar", response_model=UserRead)
async def upload_avatar(
    file: UploadFile,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    """Replace the current user's avatar. The file is decoded, validated and
    re-encoded before it touches disk (see app.core.avatars)."""
    # Bound what we pull into memory to the cap (one byte past, to detect
    # oversize). The full multipart body is still received/spooled by Starlette
    # first; the prod nginx client_max_body_size gives a transport-level bound.
    data = await file.read(settings.avatar_max_bytes + 1)
    if len(data) > settings.avatar_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image is too large",
        )
    try:
        filename = store_avatar(data)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file is not a valid image",
        ) from None

    old = user.avatar_path
    user.avatar_path = filename
    await record_event(
        session,
        action=AuditAction.user_updated,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
        detail="avatar",
    )
    await session.commit()
    await session.refresh(user)
    # Drop the previous file only after the new one is safely committed.
    delete_avatar(old)
    return user


@router.delete("/avatar", response_model=UserRead)
async def remove_avatar(
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    """Remove the current user's avatar (falls back to initials). Idempotent."""
    old = user.avatar_path
    if old is None:
        return user
    user.avatar_path = None
    await record_event(
        session,
        action=AuditAction.user_updated,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
        detail="avatar",
    )
    await session.commit()
    await session.refresh(user)
    delete_avatar(old)
    return user
