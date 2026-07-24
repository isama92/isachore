"""Tests for the fail-closed boot configuration check (app/core/startup.py, I1).

Every case pins the settings singleton by monkeypatch, the way the feature tests
do. Note conftest's autouse `_reset_app_key` clears `app_key`, so a case that
needs a usable one must set it explicitly.
"""

import logging

import pytest
from cryptography.fernet import Fernet

from app.core.config import DEV_ENVIRONMENTS, settings
from app.core.startup import check_startup_config, enforce_startup_config

# Throwaway values generated/written for the tests; never real credentials.
_KEY = Fernet.generate_key().decode()
_STRONG_URL = "postgresql+asyncpg://isachore:not-a-real-but-strong-password@db:5432/isachore"
# The literal placeholder shipped in .env.example: Fernet-key-shaped to a human,
# garbage to Fernet.
_PLACEHOLDER_APP_KEY = "changeme-generate-a-fernet-key"


def _prod_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-dev deployment that must be allowed to boot."""
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "cookies_secure", True)
    monkeypatch.setattr(settings, "app_key", _KEY)
    monkeypatch.setattr(settings, "database_url", _STRONG_URL)


def test_clean_prod_config_has_no_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    assert check_startup_config() == []


# --- APP_KEY --------------------------------------------------------------


def test_missing_app_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "app_key", None)
    problems = check_startup_config()
    assert len(problems) == 1
    assert "APP_KEY is not set" in problems[0]
    # The message names the fix, since a refused boot is the only diagnostic.
    assert "generate-key" in problems[0]


def test_empty_app_key_is_reported_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # APP_KEY= in .env yields "" rather than None.
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "app_key", "")
    assert "APP_KEY is not set" in check_startup_config()[0]


def test_placeholder_app_key_is_reported_as_invalid_not_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # crypto_configured() collapses missing and malformed; the boot message must
    # not, or an operator who did set the .env.example placeholder is told their
    # key is absent and goes looking in the wrong place.
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "app_key", _PLACEHOLDER_APP_KEY)
    problems = check_startup_config()
    assert len(problems) == 1
    assert "APP_KEY is not a valid Fernet key" in problems[0]
    assert "not set" not in problems[0]


def test_truncated_app_key_is_reported_as_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real key with a byte lost in copy-paste: the case that is silent today.
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "app_key", _KEY[:-1])
    assert "not a valid Fernet key" in check_startup_config()[0]


# --- COOKIES_SECURE -------------------------------------------------------


def test_insecure_cookies_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "cookies_secure", False)
    problems = check_startup_config()
    assert len(problems) == 1
    assert "COOKIES_SECURE" in problems[0]


# --- DATABASE_URL ---------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["isachore_dev_password", "postgres", "password", "changeme", "isachore"],
)
def test_known_bad_db_password_is_reported(monkeypatch: pytest.MonkeyPatch, password: str) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings, "database_url", f"postgresql+asyncpg://isachore:{password}@db:5432/isachore"
    )
    problems = check_startup_config()
    assert len(problems) == 1
    assert "publicly known password" in problems[0]


def test_db_password_is_never_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The message goes to the container log, so it must not carry the credential
    # or the whole URL with it. Uses the distinctive placeholder rather than a
    # generic one like "password", which appears in the message wording itself.
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://isachore:isachore_dev_password@db:5432/isachore",
    )
    problem = check_startup_config()[0]
    assert "isachore_dev_password" not in problem
    assert settings.database_url not in problem


def test_known_bad_db_password_match_ignores_case(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://isachore:PostGres@db:5432/isachore"
    )
    assert "publicly known password" in check_startup_config()[0]


def test_db_url_without_a_password_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://isachore@db:5432/isachore")
    assert "no password" in check_startup_config()[0]


def test_short_but_unlisted_db_password_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deliberate: the rule is an exact-match blocklist, not a length or entropy
    # test, so no real deploy is ever refused over a password that looks short.
    # Change this test only alongside a decision to add a length rule.
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://isachore:hunter2@db:5432/isachore"
    )
    assert check_startup_config() == []


def test_query_string_password_counts_as_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # `...@host/db?password=x` is a legitimate SQLAlchemy form that leaves
    # url.password None. Reading only that attribute would refuse a deploy that
    # does have a credential, and a false positive here bricks a boot.
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://isachore@db:5432/isachore?password=not-a-real-strong-one",
    )
    assert check_startup_config() == []


def test_query_string_password_is_still_blocklisted(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://isachore@db:5432/isachore?password=isachore_dev_password",
    )
    assert "publicly known password" in check_startup_config()[0]


@pytest.mark.parametrize(
    "database_url",
    [
        "not a database url",
        # A non-numeric port escapes SQLAlchemy's parser as a bare ValueError
        # rather than an ArgumentError, so both must be caught or the check
        # itself raises instead of reporting.
        "postgresql+asyncpg://isachore:pw@db:5432x/isachore",
    ],
)
def test_unparseable_db_url_is_reported(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "database_url", database_url)
    problems = check_startup_config()
    assert len(problems) == 1
    assert "DATABASE_URL could not be parsed" in problems[0]
    # The parser's own message can embed the URL (and so the password) depending
    # on the SQLAlchemy version, so it must not be interpolated into ours.
    assert database_url not in problems[0]


# --- Environment gating ---------------------------------------------------


@pytest.mark.parametrize("environment", sorted(DEV_ENVIRONMENTS))
def test_dev_environments_skip_every_check(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    # Dev is plain HTTP with the documented placeholder credentials, which is
    # exactly what this refuses elsewhere, so it must not be checked at all.
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "cookies_secure", False)
    monkeypatch.setattr(settings, "app_key", _PLACEHOLDER_APP_KEY)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://isachore:isachore_dev_password@db:5432/isachore",
    )
    assert check_startup_config() == []


def test_dev_environment_match_ignores_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "DEV")
    monkeypatch.setattr(settings, "cookies_secure", False)
    assert check_startup_config() == []


@pytest.mark.parametrize("environment", ["prod", "production", "staging", "prood", ""])
def test_unrecognised_environment_is_treated_as_a_deployment(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    # Fail-safe: only the known dev markers opt out, so a typo'd or empty
    # ENVIRONMENT gets the strict treatment rather than skipping the checks.
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "cookies_secure", False)
    assert check_startup_config() != []


# --- enforce_startup_config ----------------------------------------------


def test_every_problem_is_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    # An operator fixing one issue at a time through a container restart loop is
    # miserable, so all problems must surface on the first boot attempt.
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "cookies_secure", False)
    monkeypatch.setattr(settings, "app_key", None)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://isachore:isachore_dev_password@db:5432/isachore",
    )
    problems = check_startup_config()
    assert len(problems) == 3
    joined = " ".join(problems)
    assert "COOKIES_SECURE" in joined
    assert "APP_KEY" in joined
    assert "publicly known password" in joined


def test_enforce_raises_and_logs_each_problem(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prod_config(monkeypatch)
    monkeypatch.setattr(settings, "app_key", None)
    monkeypatch.setattr(settings, "cookies_secure", False)
    with (
        caplog.at_level(logging.ERROR, logger="app.startup"),
        pytest.raises(RuntimeError) as excinfo,
    ):
        enforce_startup_config()
    message = str(excinfo.value)
    assert "refusing to start" in message
    assert "COOKIES_SECURE" in message and "APP_KEY" in message
    # The escape hatch is named: the web process is dead, but the CLI still runs.
    assert "app.cli" in message
    logged = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == "app.startup"]
    assert len(logged) == 2


def test_enforce_is_a_noop_on_a_clean_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_config(monkeypatch)
    enforce_startup_config()  # no raise


def test_enforce_is_a_noop_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "cookies_secure", False)
    monkeypatch.setattr(settings, "app_key", None)
    enforce_startup_config()  # no raise
