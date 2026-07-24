"""Management commands. Run inside the backend container:

docker compose exec backend python -m app.cli init \\
    --email you@example.com --first-name You --last-name Example
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_event
from app.core.config import is_dev_environment, settings
from app.core.crypto import generate_key
from app.core.households import add_to_default_household
from app.core.invitations import run_expire_invitations
from app.core.rate_limit import clear_login_throttle
from app.core.security import hash_password
from app.db.redis import redis_client
from app.db.seed import seed
from app.db.session import async_session_factory
from app.models import (
    AuditAction,
    AuthToken,
    ConfirmationToken,
    TwoFactorChallenge,
    TwoFactorRecoveryCode,
    User,
    UserStatus,
)


async def init_admin(
    session: AsyncSession, email: str, first_name: str, last_name: str, password: str
) -> None:
    """Bootstrap the first admin, or restore admin access when none works.

    No-op when an *active* admin already exists, so it is safe to leave in a
    deploy script and harmless to run twice. Otherwise it is also the recovery
    tool (I2): an existing account with this email is promoted, re-activated and
    given the supplied password, because only counting active admins would still
    leave a locked-out install unrecoverable under its own address. A disabled
    admin is not reachable through the API, but direct DB changes can produce one
    and this is the documented way back in.
    """
    # Normalise like the API schema does, since the CLI bypasses Pydantic (L3)
    email = email.lower()
    active_admin = await session.execute(
        select(User.id).where(User.is_admin.is_(True), User.status == UserStatus.active).limit(1)
    )
    if active_admin.scalar_one_or_none() is not None:
        print("an active admin already exists, nothing to do")
        return
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        await _restore_admin(session, existing, password)
        return
    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        password_hash=hash_password(password),
        is_admin=True,
        status=UserStatus.active,
        confirmed_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    await add_to_default_household(session, user.id)
    await session.commit()
    print(f"admin user {email!r} created")


async def _restore_admin(session: AsyncSession, user: User, password: str) -> None:
    """Give an existing account working admin access back, reporting exactly what
    it changed since this is destructive to the account's credentials.

    It clears everything that would otherwise leave the operator still locked out
    or leave a stale way in, mirroring what the API does on the same changes
    (`update_user` / `reset_two_factor` in api/v1/users.py): two-factor enrolment,
    because a restored password still dead-ends at the TOTP challenge; live
    sessions, so one parked before the lockout cannot return as an admin session;
    and any pending confirmation link, which could otherwise set a password of its
    own and log straight in as the admin we just restored.

    The account's name is deliberately left alone: recovery is about access, not
    identity, and renaming a real person from a deploy-script placeholder would be
    worse than ignoring the flags.
    """
    changes: list[str] = []
    if not user.is_admin:
        user.is_admin = True
        changes.append("promoted to admin")
    if user.status != UserStatus.active:
        changes.append(f"status {user.status} -> {UserStatus.active}")
        user.status = UserStatus.active
    if user.confirmed_at is None:
        user.confirmed_at = datetime.now(UTC)
        changes.append("marked confirmed")
    changes.append("password reset")
    user.password_hash = hash_password(password)
    if user.totp_enabled or user.totp_secret is not None:
        user.totp_enabled = False
        user.totp_secret = None
        await session.execute(
            delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id)
        )
        await session.execute(
            delete(TwoFactorChallenge).where(TwoFactorChallenge.user_id == user.id)
        )
        changes.append("two-factor enrolment cleared")
    await session.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    await session.execute(delete(ConfirmationToken).where(ConfirmationToken.user_id == user.id))
    changes.append("sessions and pending confirmation links revoked")
    # Deliberately not add_to_default_household: an existing user already has its
    # memberships, and that helper inserts unconditionally rather than checking,
    # so calling it here would duplicate a household_members row.
    #
    # No actor_id: there is no logged-in admin, only whoever holds shell access,
    # the same "no known actor" case as login_failed. user_updated is reused
    # rather than adding an enum member, since audit_events.action is a DB enum
    # and a new value would need a migration.
    await record_event(
        session,
        action=AuditAction.user_updated,
        target_id=user.id,
        detail=f"cli init recovery: {', '.join(changes)}"[:255],
    )
    await session.commit()
    print(f"restored admin access for {user.email!r}: {', '.join(changes)}")


async def _init_admin_main(email: str, first_name: str, last_name: str, password: str) -> None:
    async with async_session_factory() as session:
        await init_admin(session, email, first_name, last_name, password)


async def clear_throttle(session: AsyncSession, redis: Redis, user_id: int | None) -> None:
    """Clear login rate-limit counters. With a user id, clear only that user's
    per-email counter (a user maps to an email but never to an IP, so this can't
    clear an IP lockout); without one, clear every login throttle key."""
    if user_id is None:
        cleared = await clear_login_throttle(redis)
        print(f"cleared {cleared} login throttle entr{'y' if cleared == 1 else 'ies'}")
        return
    email = (
        await session.execute(select(User.email).where(User.id == user_id))
    ).scalar_one_or_none()
    if email is None:
        sys.exit(f"error: no user with id {user_id}")
    cleared = await clear_login_throttle(redis, email=email)
    print(
        f"cleared throttle for user {user_id} ({email!r}): "
        f"{cleared} entr{'y' if cleared == 1 else 'ies'}"
    )


async def _clear_throttle_main(user_id: int | None) -> None:
    async with async_session_factory() as session:
        await clear_throttle(session, redis_client, user_id)
    await redis_client.aclose()


async def _expire_invitations_main() -> None:
    """Run the invitation-expiry sweep once (the same job the hourly scheduler
    runs). Handy for manual runs or an external cron."""
    count = await run_expire_invitations()
    print(f"expired {count} invitation{'' if count == 1 else 's'}")


async def _seed_main(fresh: bool) -> None:
    async with async_session_factory() as session:
        summary = await seed(session, fresh=fresh)
    print(str(summary))


def _guard_dev_environment() -> None:
    """Refuse to seed anywhere that isn't marked as a dev environment (fail-closed)."""
    if not is_dev_environment():
        sys.exit(f"refusing to seed: environment {settings.environment!r} is not a dev environment")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init",
        help=(
            "create the first admin user (no-op if an ACTIVE admin exists); with no active "
            "admin it recovers instead, taking over the account with this email: promoted, "
            "re-activated, password RESET, 2FA cleared, sessions revoked"
        ),
    )
    init.add_argument("--email", required=True)
    init.add_argument("--first-name", required=True)
    init.add_argument("--last-name", required=True)
    init.add_argument("--password", help="prompted securely when omitted")

    clear = subparsers.add_parser(
        "clear-login-throttle",
        help="clear login rate-limit counters (one user by id, or all when omitted)",
    )
    clear.add_argument(
        "user_id", nargs="?", type=int, default=None, help="user id; omit to clear all throttles"
    )

    subparsers.add_parser(
        "expire-invitations",
        help="mark stale pending household invitations as expired (the hourly job, run once)",
    )

    subparsers.add_parser(
        "generate-key",
        help="print a fresh Fernet key for APP_KEY (required outside a dev environment)",
    )

    seed_parser = subparsers.add_parser(
        "seed",
        help="populate a rich dev/test dataset (users, households, chores, history)",
    )
    seed_parser.add_argument(
        "--fresh", action="store_true", help="wipe all app data first, then reseed"
    )

    args = parser.parse_args()
    if args.command == "init":
        password = args.password or getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("error: password must be at least 8 characters")
        asyncio.run(_init_admin_main(args.email, args.first_name, args.last_name, password))
    elif args.command == "clear-login-throttle":
        asyncio.run(_clear_throttle_main(args.user_id))
    elif args.command == "expire-invitations":
        asyncio.run(_expire_invitations_main())
    elif args.command == "generate-key":
        print(generate_key())
    elif args.command == "seed":
        _guard_dev_environment()
        try:
            asyncio.run(_seed_main(args.fresh))
        except RuntimeError as exc:
            sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
