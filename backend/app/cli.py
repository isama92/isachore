"""Management commands. Run inside the backend container:

docker compose exec backend python -m app.cli create-admin --email you@example.com --name You
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.households import add_to_default_household
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models import User


async def create_admin(email: str, name: str, password: str) -> None:
    async with async_session_factory() as session:
        existing = await session.execute(select(User.id).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            sys.exit(f"error: a user with email {email!r} already exists")
        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password),
            is_admin=True,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        await add_to_default_household(session, user.id)
        await session.commit()
    print(f"admin user {email!r} created")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-admin", help="create an admin user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password", help="prompted securely when omitted")

    args = parser.parse_args()
    if args.command == "create-admin":
        password = args.password or getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("error: password must be at least 8 characters")
        asyncio.run(create_admin(args.email, args.name, password))


if __name__ == "__main__":
    main()
