"""Redis-backed login throttling (M2).

Failed logins are counted in Redis, keyed by the attempted email and by the
client IP, over a fixed window. When either counter reaches its threshold,
`/login` is refused with 429 *before* the password is verified. A successful
login clears that email's counter. While locked out we do not increment, so the
lockout is bounded by the window TTL.

The 429 fires on attempt volume regardless of whether the account exists, so it
keeps the existing anti-enumeration property of the login endpoint.

Redis is treated as best-effort: if it is unavailable the throttle fails open
(logs a warning and allows the request) rather than turning a cache outage into a
total auth outage. Argon2 still slows each attempt in that degraded mode.
"""

import logging

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

_LOCKED_OUT_DETAIL = "Too many failed login attempts. Please try again later."


def client_ip(request: Request) -> str | None:
    """Best-effort client IP.

    Trusts proxy headers only when configured to (i.e. behind a trusted reverse
    proxy such as the prod nginx). Then it prefers `X-Real-IP`, which nginx sets
    to the connection peer it observed and overwrites on every request, and falls
    back to the *right-most* `X-Forwarded-For` hop, which the trusted proxy
    appends. The left-most XFF entries are client-supplied and must never be used
    as the key, or a caller could evade or spoof the per-IP limit. When trust is
    off (dev / direct access) the socket peer is used.
    """
    if settings.trust_forwarded_for:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else None


_KEY_PREFIX = "login:fail:"


def _email_key(email: str) -> str:
    return f"{_KEY_PREFIX}email:{email}"


def _ip_key(ip: str) -> str:
    return f"{_KEY_PREFIX}ip:{ip}"


async def _retry_after(redis: Redis, key: str) -> int:
    ttl = await redis.ttl(key)
    return ttl if ttl and ttl > 0 else settings.login_attempt_window


def _locked_out(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_LOCKED_OUT_DETAIL,
        headers={"Retry-After": str(retry_after)},
    )


async def _incr_with_ttl(redis: Redis, key: str) -> None:
    # INCR and EXPIRE in one transaction so an interruption can't leave the key
    # without a TTL (which would lock it forever). EXPIRE nx sets the window only
    # when the key has none yet, so it runs from the first failure and repeated
    # failures cannot extend the lockout.
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, settings.login_attempt_window, nx=True)
        await pipe.execute()


async def enforce_login_rate_limit(redis: Redis, *, email: str, ip: str | None) -> None:
    """Raise 429 if the email or IP is currently locked out. Call before
    verifying the password."""
    try:
        email_key = _email_key(email)
        if int(await redis.get(email_key) or 0) >= settings.login_max_attempts:
            raise _locked_out(await _retry_after(redis, email_key))
        if ip is not None:
            ip_key = _ip_key(ip)
            if int(await redis.get(ip_key) or 0) >= settings.login_ip_max_attempts:
                raise _locked_out(await _retry_after(redis, ip_key))
    except RedisError:
        logger.warning("Login rate-limit check skipped: Redis unavailable", exc_info=True)


async def record_login_failure(redis: Redis, *, email: str, ip: str | None) -> None:
    try:
        await _incr_with_ttl(redis, _email_key(email))
        if ip is not None:
            await _incr_with_ttl(redis, _ip_key(ip))
    except RedisError:
        logger.warning("Login failure not recorded: Redis unavailable", exc_info=True)


async def clear_login_failures(redis: Redis, *, email: str) -> None:
    # Only the per-email counter is cleared on success; the per-IP counter stays
    # so one legitimate login can't reset an attacker's IP-wide budget.
    try:
        await redis.delete(_email_key(email))
    except RedisError:
        logger.warning("Login failure counter not cleared: Redis unavailable", exc_info=True)


_TWO_FACTOR_KEY_PREFIX = "twofa:fail:"


def _twofa_user_key(user_id: int) -> str:
    return f"{_TWO_FACTOR_KEY_PREFIX}user:{user_id}"


def _twofa_ip_key(ip: str) -> str:
    return f"{_TWO_FACTOR_KEY_PREFIX}ip:{ip}"


async def enforce_two_factor_rate_limit(redis: Redis, *, user_id: int, ip: str | None) -> None:
    """Raise 429 if this user (or IP) has failed too many 2FA codes. Call before
    verifying a submitted code. Keyed separately from the login throttle so the
    two limits are independent; the window and IP threshold are shared."""
    try:
        user_key = _twofa_user_key(user_id)
        if int(await redis.get(user_key) or 0) >= settings.two_factor_max_attempts:
            raise _locked_out(await _retry_after(redis, user_key))
        if ip is not None:
            ip_key = _twofa_ip_key(ip)
            if int(await redis.get(ip_key) or 0) >= settings.login_ip_max_attempts:
                raise _locked_out(await _retry_after(redis, ip_key))
    except RedisError:
        logger.warning("2FA rate-limit check skipped: Redis unavailable", exc_info=True)


async def record_two_factor_failure(redis: Redis, *, user_id: int, ip: str | None) -> None:
    try:
        await _incr_with_ttl(redis, _twofa_user_key(user_id))
        if ip is not None:
            await _incr_with_ttl(redis, _twofa_ip_key(ip))
    except RedisError:
        logger.warning("2FA failure not recorded: Redis unavailable", exc_info=True)


async def clear_two_factor_failures(redis: Redis, *, user_id: int) -> None:
    # Only the per-user counter is cleared on success; the per-IP counter stays
    # so one legitimate verify can't reset an attacker's IP-wide budget.
    try:
        await redis.delete(_twofa_user_key(user_id))
    except RedisError:
        logger.warning("2FA failure counter not cleared: Redis unavailable", exc_info=True)


_TEST_EMAIL_KEY_PREFIX = "test-email:cooldown:"
_TEST_EMAIL_COOLDOWN_DETAIL = "Please wait before sending another test email."


def _test_email_key(user_id: int) -> str:
    return f"{_TEST_EMAIL_KEY_PREFIX}{user_id}"


async def enforce_test_email_cooldown(redis: Redis, *, user_id: int) -> None:
    """Rate-limit the admin "send test email" button to one send per cooldown
    window, per admin. Call before sending.

    Uses an atomic `SET NX EX` so the check and the claim are one round trip and
    two tabs can't both slip through. When the key already exists the admin is
    still cooling down, so refuse with 429 plus a Retry-After of the remaining
    TTL. Best-effort like the login throttle: a Redis outage fails open (a full
    cache outage shouldn't disable a diagnostic tool). The cooldown is claimed
    even if the send later fails, so a broken relay can't be hammered either.
    """
    try:
        key = _test_email_key(user_id)
        claimed = await redis.set(key, "1", ex=settings.test_email_cooldown, nx=True)
        if not claimed:
            ttl = await redis.ttl(key)
            retry_after = ttl if ttl and ttl > 0 else settings.test_email_cooldown
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_TEST_EMAIL_COOLDOWN_DETAIL,
                headers={"Retry-After": str(retry_after)},
            )
    except RedisError:
        logger.warning("Test-email cooldown check skipped: Redis unavailable", exc_info=True)


async def clear_login_throttle(redis: Redis, *, email: str | None = None) -> int:
    """Maintenance helper for the management CLI. With `email`, delete only that
    address's counter; without it, delete every login throttle key (per-email
    and per-IP). Returns the number of keys removed.

    Unlike `clear_login_failures` (the login hot path, which fails open) this
    does NOT swallow `RedisError`: a management command should fail loudly rather
    than report success it can't guarantee.
    """
    if email is not None:
        return await redis.delete(_email_key(email))
    keys = [key async for key in redis.scan_iter(f"{_KEY_PREFIX}*")]
    return await redis.delete(*keys) if keys else 0
