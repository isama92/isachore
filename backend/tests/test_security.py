import pytest
from fastapi import Response

from app.core.config import Settings, settings
from app.core.security import clear_auth_cookie, set_auth_cookie


def _set_cookie_header(secure: bool, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "cookies_secure", secure)
    response = Response()
    set_auth_cookie(response, "a-token")
    return response.headers["set-cookie"]


def test_auth_cookie_has_secure_flag_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    header = _set_cookie_header(True, monkeypatch).lower()
    # Match the attribute token, not a bare substring, so the cookie name/value
    # can't accidentally satisfy it
    assert "; secure" in header
    # The other hardening attributes stay put alongside Secure
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header


def test_auth_cookie_omits_secure_flag_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    header = _set_cookie_header(False, monkeypatch).lower()
    assert "; secure" not in header
    # Disabling Secure must not weaken the rest
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header


def test_auth_cookie_defaults_to_persistent(monkeypatch: pytest.MonkeyPatch) -> None:
    # The default call (used by impersonation / confirmation login) keeps the
    # 30-day persistent session: a Max-Age is present.
    header = _set_cookie_header(True, monkeypatch).lower()
    assert "max-age=2592000" in header  # 30 days


def test_auth_cookie_session_when_max_age_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # A login without "remember me" passes max_age=None, yielding a browser-
    # session cookie (no Max-Age) while keeping every hardening attribute.
    monkeypatch.setattr(settings, "cookies_secure", True)
    response = Response()
    set_auth_cookie(response, "a-token", max_age=None)
    header = response.headers["set-cookie"].lower()
    assert "max-age" not in header
    assert "; secure" in header
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header


def test_cookies_secure_defaults_to_true() -> None:
    # Fail-closed: a deploy that configures nothing gets Secure cookies. Assert
    # the declared default so ambient env (.env / COOKIES_SECURE) can't mask it.
    assert Settings.model_fields["cookies_secure"].default is True


def _clear_cookie_header(secure: bool, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "cookies_secure", secure)
    response = Response()
    clear_auth_cookie(response)
    return response.headers["set-cookie"]


def test_clear_auth_cookie_mirrors_attributes_when_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Removal must mirror the set attributes or some browsers won't clear it (L4)
    header = _clear_cookie_header(True, monkeypatch).lower()
    assert "; secure" in header
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header
    # It's a deletion, so the cookie is expired immediately
    assert "max-age=0" in header


def test_clear_auth_cookie_omits_secure_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    header = _clear_cookie_header(False, monkeypatch).lower()
    assert "; secure" not in header
    assert "samesite=lax" in header
    assert "path=/" in header
    assert "max-age=0" in header
