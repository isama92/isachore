"""App-level cap on the size of any request body.

In prod, nginx rejects oversized bodies at the edge (client_max_body_size in
frontend/nginx-common.conf; keep the two limits in sync). This middleware is
defence in depth for a deployment that exposes the backend directly: Starlette
spools an entire multipart body (memory, then temp files) before a handler's
own size check ever runs, so without a transport-level bound a client could
push arbitrarily large uploads. A body with an honest Content-Length is
refused before any of it is read; a chunked body is cut off as soon as the
running total passes the cap.
"""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.status import HTTP_413_CONTENT_TOO_LARGE
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_DETAIL = "Request body is too large"


class BodySizeLimitMiddleware:
    """Pure-ASGI middleware enforcing settings.max_request_bytes.

    The cap is read per request, not at construction, so tests can monkeypatch
    the setting (same call-time pattern as avatars_dir()).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = settings.max_request_bytes
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            response = JSONResponse({"detail": _DETAIL}, status_code=HTTP_413_CONTENT_TOO_LARGE)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    # Raised from inside the app's body read; FastAPI re-raises
                    # middleware HTTPExceptions untouched, so this surfaces as a
                    # clean 413 instead of a 500.
                    raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, _DETAIL)
            return message

        await self.app(scope, limited_receive, send)
