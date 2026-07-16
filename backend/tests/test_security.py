import pytest
from fastapi import Response

from app.core.config import Settings, settings
from app.core.security import set_auth_cookie


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


def test_cookies_secure_defaults_to_true() -> None:
    # Fail-closed: a deploy that configures nothing gets Secure cookies. Assert
    # the declared default so ambient env (.env / COOKIES_SECURE) can't mask it.
    assert Settings.model_fields["cookies_secure"].default is True
