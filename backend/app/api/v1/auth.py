from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.api.deps import (
    CurrentUser,
    RedisDep,
    SessionDep,
    get_impersonator,
    get_request_token,
    get_user_by_token,
)
from app.core.audit import record_event
from app.core.rate_limit import (
    clear_login_failures,
    client_ip,
    enforce_login_rate_limit,
    record_login_failure,
)
from app.core.security import (
    ADMIN_COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    TOKEN_TTL,
    clear_auth_cookie,
    generate_token,
    hash_token,
    set_auth_cookie,
    verify_password,
)
from app.models import AuditAction, AuthToken, User
from app.schemas import LoginRequest, MeRead, UserRead

router = APIRouter()


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest,
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    response: Response,
) -> User:
    ip = client_ip(request)
    # Throttle key is case-insensitive so a differently-cased email can't sidestep
    # the lockout (user lookup itself stays case-sensitive; see L3).
    email = payload.email.lower()
    await enforce_login_rate_limit(redis, email=email, ip=ip)

    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    password_ok = verify_password(
        payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok or not user.is_active:
        await record_login_failure(redis, email=email, ip=ip)
        # Persist the failed attempt (actor unknown; the attempted email goes in
        # detail) even though the request itself fails with 401.
        await record_event(session, action=AuditAction.login_failed, ip=ip, detail=email)
        await session.commit()
        # One message for every failure mode so emails can't be enumerated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + TOKEN_TTL,
        )
    )
    await record_event(session, action=AuditAction.login_success, actor_id=user.id, ip=ip)
    await session.commit()

    await clear_login_failures(redis, email=email)
    set_auth_cookie(response, token)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)
    return user


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


@router.get("/me", response_model=MeRead)
async def me(request: Request, user: CurrentUser, session: SessionDep) -> MeRead:
    impersonating = await get_impersonator(request, session) is not None
    return MeRead.model_validate(user).model_copy(update={"impersonating": impersonating})


@router.post("/stop-impersonating", response_model=UserRead)
async def stop_impersonating(request: Request, session: SessionDep, response: Response) -> User:
    admin_token = request.cookies.get(ADMIN_COOKIE_NAME)
    admin = await get_user_by_token(session, admin_token) if admin_token else None
    if admin_token is None or admin is None or not admin.is_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No impersonation in progress"
        )

    # Drop the impersonated session and restore the admin one
    current = get_request_token(request)
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
