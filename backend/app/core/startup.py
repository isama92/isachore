"""Fail-closed configuration check, run once at boot (I1).

Outside a dev environment a few settings have no safe default and cannot be
forced by compose the way ENVIRONMENT / COOKIES_SECURE / TRUST_FORWARDED_FOR
are, so getting them wrong is silent today. APP_KEY is the sharp case:
app/core/crypto.py deliberately reads a malformed key as "unconfigured", so a
typo stays invisible until an enrolled 2FA user is turned away with a 503. This
module turns those into a refusal to boot.

Deliberately NOT a pydantic validator on Settings: the settings singleton is
built at import time (config.py) by every process, so a validator would equally
refuse to run pytest and `python -m app.cli` - including the `init` and
`generate-key` commands needed to repair the very deploy it rejected. Enforced
from the FastAPI lifespan instead, which leaves
`docker compose run --rm backend python -m app.cli ...` and alembic working
while the web process refuses to serve.
"""

import logging

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import is_dev_environment, settings
from app.core.crypto import crypto_configured
from app.core.oidc import oidc_configured

logger = logging.getLogger("app.startup")

# DB passwords that are public knowledge: the placeholder shipped in
# .env.example plus the usual defaults. Deliberately an exact-match blocklist
# rather than a length or entropy rule, so a real deploy is never refused over a
# strong password that merely looks short.
_KNOWN_BAD_DB_PASSWORDS = frozenset(
    {
        "isachore_dev_password",
        "isachore",
        "postgres",
        "password",
        "changeme",
    }
)

_GENERATE_KEY_HINT = "generate one with `python -m app.cli generate-key`"


def _app_key_problem() -> str | None:
    if not settings.app_key:
        return f"APP_KEY is not set ({_GENERATE_KEY_HINT})"
    if not crypto_configured():
        # Reported separately from "not set" on purpose: crypto_configured()
        # collapses missing and malformed, and telling an operator who did set a
        # key that it is unset sends them hunting in the wrong place.
        return f"APP_KEY is not a valid Fernet key ({_GENERATE_KEY_HINT})"
    return None


def _database_password_problem() -> str | None:
    # The credential the backend actually authenticates with lives in
    # DATABASE_URL; POSTGRES_PASSWORD is not a setting here (config.py does not
    # declare it and extra="ignore" drops it), and in prod compose it only ever
    # reaches the db service.
    try:
        url = make_url(settings.database_url)
    except (ArgumentError, ValueError):
        # ValueError is not redundant: a non-numeric port (…@db:5432x/…) escapes
        # _parse_url as a bare ValueError. The exception text is deliberately not
        # included, because some SQLAlchemy versions embed the offending URL in
        # it, which would put the password in the container log.
        return "DATABASE_URL could not be parsed"
    # A password given as a query parameter (.../db?password=...) is a legitimate
    # SQLAlchemy form that leaves url.password None, so consult both rather than
    # refusing a deploy that does have a credential.
    query_password = url.query.get("password")
    if isinstance(query_password, tuple):  # a repeated ?password= yields a tuple
        query_password = next(iter(query_password), None)
    password = url.password or query_password
    if not password:
        # Refusing here means the app has no other supported way to authenticate:
        # PGPASSWORD, ~/.pgpass and cert/trust auth are not wired up anywhere in
        # the repo, so an empty password in prod is a misconfiguration, not a
        # style choice.
        return "DATABASE_URL carries no password"
    if password.lower() in _KNOWN_BAD_DB_PASSWORDS:
        # The matched value is not echoed: it is documented in .env.example, so
        # naming it adds nothing an operator cannot read from their own file.
        return (
            "DATABASE_URL uses a publicly known password; set POSTGRES_PASSWORD "
            "and the password in DATABASE_URL to a strong secret"
        )
    return None


def _oidc_problems() -> list[str]:
    """Single sign-on misconfigurations that are worth refusing a deploy over.

    All three are silent otherwise, and one of them is a lockout. A half-configured provider
    reads as "not configured", so the sign-in button never renders and the endpoints 404 -
    quiet in the worst way, since the operator plainly meant to turn it on. A plaintext
    issuer puts the client secret on the wire. And OIDC_ONLY without a provider leaves
    nobody able to sign in at all.
    """
    problems: list[str] = []
    present = {
        "OIDC_ISSUER": bool(settings.oidc_issuer),
        "OIDC_CLIENT_ID": bool(settings.oidc_client_id),
        "OIDC_CLIENT_SECRET": bool(settings.oidc_client_secret),
    }
    missing = sorted(name for name, is_set in present.items() if not is_set)
    if missing and len(missing) != len(present):
        # Some but not all: an operator who set two of three has clearly intended to
        # turn SSO on, so failing quietly (button never renders) would be the worst
        # outcome. All three unset is the ordinary "no SSO" deployment and fine.
        problems.append(
            "single sign-on is partly configured: "
            + ", ".join(missing)
            + " missing. Set all of OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET, "
            "or none of them"
        )
    if settings.oidc_issuer and not settings.oidc_issuer.lower().startswith("https://"):
        # The client secret is presented to the token endpoint under this origin.
        problems.append(
            "OIDC_ISSUER is not https, so the client secret would cross the network in plaintext"
        )
    if settings.oidc_only and not oidc_configured():
        problems.append(
            "OIDC_ONLY is true but no single sign-on provider is configured, which "
            "would leave nobody able to sign in; configure the provider or set "
            "OIDC_ONLY=false"
        )
    return problems


def check_startup_config() -> list[str]:
    """Configuration problems that must block boot; empty when there are none.

    Always empty in a dev environment: dev is served over plain HTTP with the
    documented placeholder credentials, which is precisely what this refuses
    everywhere else.
    """
    if is_dev_environment():
        return []
    problems: list[str] = []
    if not settings.cookies_secure:
        problems.append(
            "COOKIES_SECURE is false, so auth cookies would be sent over plain HTTP; "
            "every prod mode terminates TLS, so leave it unset or true"
        )
    if (problem := _app_key_problem()) is not None:
        problems.append(problem)
    if (problem := _database_password_problem()) is not None:
        problems.append(problem)
    problems.extend(_oidc_problems())
    return problems


def enforce_startup_config() -> None:
    """Raise RuntimeError when check_startup_config() finds anything, so the
    process exits non-zero instead of serving a deployment that would fail
    closed later. Every problem is also logged individually, so they stay
    greppable if the traceback is truncated."""
    problems = check_startup_config()
    if not problems:
        return
    for problem in problems:
        logger.error("refusing to start: %s", problem)
    raise RuntimeError(
        f"refusing to start in environment {settings.environment!r}: "
        + "; ".join(problems)
        + ". Fix .env and restart, or set ENVIRONMENT to a dev value for local work. "
        "Management commands still run: "
        "`docker compose run --rm backend python -m app.cli generate-key`."
    )
