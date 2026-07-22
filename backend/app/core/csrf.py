"""Custom-header CSRF defence (defence in depth, L4).

Auth is a browser-auto-sent httpOnly session cookie, so a cross-site page can
make the browser attach it to a forged mutation. SameSite=Lax on the cookie
(security.py) is the primary defence; this middleware adds a second layer that
does not depend on the SameSite assumption holding.

It works because the app registers no CORS middleware: a cross-site page cannot
set a custom (non-safelisted) request header without a CORS preflight, and the
preflight gets no Access-Control-Allow-* response, so the forged request never
fires. Requiring the presence of X-CSRF-Token on unsafe methods therefore blocks
cross-site mutations without any token store or server-side state.

Scope is cookie-authenticated requests only: Authorization: Bearer clients (the
JSON API for future mobile clients) are CSRF-immune by construction, so they are
left untouched. The isachore_2fa challenge cookie is deliberately NOT treated as
a session cookie here: verify-2fa is already gated by the secret TOTP code, so it
isn't a CSRF target, and excluding it keeps that pre-auth step header-free.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_403_FORBIDDEN
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import ADMIN_COOKIE_NAME, COOKIE_NAME

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER = "x-csrf-token"
# Cookies whose presence means the request is authenticated by an auto-sent
# cookie (i.e. CSRF-reachable). isachore_2fa is excluded on purpose (see module
# docstring).
_AUTH_COOKIES = (COOKIE_NAME, ADMIN_COOKIE_NAME)
_DETAIL = "Missing CSRF header"


class CsrfProtectMiddleware:
    """Reject cookie-authenticated unsafe requests that lack the CSRF header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.method not in SAFE_METHODS:
            cookie_auth = any(name in request.cookies for name in _AUTH_COOKIES)
            # request.headers.get returns "" for an empty header, which is falsy,
            # so an empty X-CSRF-Token is treated as missing.
            if cookie_auth and not request.headers.get(CSRF_HEADER):
                response = JSONResponse({"detail": _DETAIL}, status_code=HTTP_403_FORBIDDEN)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
