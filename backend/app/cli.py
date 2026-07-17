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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.households import add_to_default_household
from app.core.rate_limit import clear_login_throttle
from app.core.security import hash_password
from app.db.redis import redis_client
from app.db.session import async_session_factory
from app.models import User, UserStatus


async def init_admin(email: str, first_name: str, last_name: str, password: str) -> None:
    """Bootstrap the first admin. No-op if any admin already exists, so it's safe
    to run once when the app is first deployed and harmless to run again."""
    # Normalise like the API schema does, since the CLI bypasses Pydantic (L3)
    email = email.lower()
    async with async_session_factory() as session:
        existing_admin = await session.execute(
            select(User.id).where(User.is_admin.is_(True)).limit(1)
        )
        if existing_admin.scalar_one_or_none() is not None:
            print("an admin already exists, nothing to do")
            return
        clash = await session.execute(select(User.id).where(User.email == email))
        if clash.scalar_one_or_none() is not None:
            sys.exit(f"error: a user with email {email!r} already exists")
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init", help="create the first admin user (no-op if an admin already exists)"
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

    args = parser.parse_args()
    if args.command == "init":
        password = args.password or getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("error: password must be at least 8 characters")
        asyncio.run(init_admin(args.email, args.first_name, args.last_name, password))
    elif args.command == "clear-login-throttle":
        asyncio.run(_clear_throttle_main(args.user_id))


if __name__ == "__main__":
    main()
