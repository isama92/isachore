"""The API reference page, served entirely from this origin.

FastAPI's built-in `/redoc` is disabled (`redoc_url=None` in `main.py`) in favour of these
two routes, for reasons that are not cosmetic. Its stock page loads the ReDoc bundle from
`cdn.jsdelivr.net/npm/redoc@2/...` - a floating major range, resolved per request, with no
`integrity` attribute - and pulls Montserrat and Roboto from Google Fonts. On a deployment
that meant two things worth closing:

- **Supply chain.** That script runs same-origin with the SPA, where it can call `/api/v1`
  with the reader's session cookie and set `X-CSRF-Token` itself, which is exactly the pair
  `core/csrf.py` requires. Nothing pinned what it was.
- **AVG / GDPR.** Every signed-in reader's IP went to two third parties for typography
  alone, on an app that otherwise loads nothing external.

`get_redoc_html` parameterises all three of its outbound requests, so pointing them inward
closes both at once and shrinks what `docker/nginx/nginx-docs.conf` has to relax down to a
single directive. The bundle is vendored into the image at build time and pinned by sha256 -
see `docker/backend.Dockerfile`.

**Two routers, mounted at different depths, and that is a gate rule rather than a style
choice.** The prod nginx gates one exact location, `= /docs`, which it rewrites to the
backend's `/redoc`; it separately proxies everything under `/api/` with no gate at all. So
the page has to stay at the ROOT, where nothing but that gated location can reach it. Moving
it under `/api/v1/docs/` for tidiness would publish the whole reference anonymously through
the `/api/` proxy, straight past the auth_request. The bundle goes there deliberately, for
the same reason inverted: it is public JavaScript that needs no gate, and living under the
already-proxied prefix means it needs no new nginx location either.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import FileResponse, HTMLResponse

# Mounted at the app root in main.py: only the gated nginx location reaches it.
page_router = APIRouter()
# Mounted under /api/v1/docs: reachable through the existing /api/ proxy, ungated.
asset_router = APIRouter()

# The version is IN the url, which is what makes the immutable cache below safe: the response
# carries a year-long `immutable` Cache-Control, so with a fixed path a returning reader would
# keep the old bundle for a year after the image bumped ReDoc.
#
# It is a second copy of `ARG REDOC_VERSION` in docker/backend.Dockerfile, which is the one
# that decides which bytes are fetched - so bumping ReDoc means editing both. What keeps that
# honest is that the Dockerfile writes the file under its *versioned* name and this builds the
# same name: disagree, and the route looks for a file that is not there and says so on the
# first request, rather than serving new bytes at an old url that browsers cache for a year.
REDOC_VERSION = "2.5.3"
BUNDLE_FILENAME = f"redoc-{REDOC_VERSION}.standalone.js"
BUNDLE_URL = f"/api/v1/docs/{BUNDLE_FILENAME}"

# Outside /app so the dev stage's ./backend bind mount cannot hide it.
VENDOR_DIR = Path("/opt/redoc")
REDOC_BUNDLE = VENDOR_DIR / BUNDLE_FILENAME
# The name the bundle's own first line points at (`/*! For license information please see
# redoc.standalone.js.LICENSE.txt */`). Served under exactly that name, because the pointer is
# resolved relative to the bundle's url - vendoring the file into the image without serving it
# would leave the attribution dangling for anybody who actually followed it.
LICENSE_FILENAME = "redoc.standalone.js.LICENSE.txt"


def _vendored(path: Path, media_type: str) -> FileResponse:
    """Serve a file the image was supposed to vendor, or say plainly that it did not.

    `FileResponse` stats the path inside `__call__`, so a missing file becomes a RuntimeError
    and an opaque 500 with a traceback - and the page it breaks renders blank, with nothing on
    screen saying why. That is not an anomaly but a documented case: the bundle is fetched at
    image-build time, so it is absent from a bare checkout and from CI's host-side runner, and
    it would also be absent if `REDOC_VERSION` here drifted from the Dockerfile's ARG. A named
    503 turns an afternoon into a sentence.
    """
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{path.name} was not vendored into this image. It is fetched by "
                "docker/backend.Dockerfile at build time; check that REDOC_VERSION there "
                "matches the one in app/api/v1/docs.py."
            ),
        )
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@asset_router.get(f"/{BUNDLE_FILENAME}", include_in_schema=False)
async def redoc_bundle() -> FileResponse:
    """The vendored ReDoc bundle.

    Out of the schema because it is an asset rather than an operation, and ungated because it
    is public open-source JavaScript that discloses nothing about this deployment. The *page*
    is what nginx gates, and a reader with no session is redirected before ever asking for
    this.

    Cached for a year as `immutable`, which is only correct because the version is in the
    path: bump `REDOC_VERSION` and the URL changes with the bytes. An unversioned path with
    this header would leave returning readers on the old bundle long after an upgrade.
    """
    return _vendored(REDOC_BUNDLE, "text/javascript")


@asset_router.get(f"/{LICENSE_FILENAME}", include_in_schema=False)
async def redoc_license() -> FileResponse:
    """The bundle's licence text, at the name the bundle's first line points at.

    Not decoration: that pointer is resolved against the bundle's own url, so serving the
    script without this leaves a dangling attribution for third-party MIT code to anybody who
    follows it. Unversioned, because the pointer inside the file is.
    """
    return _vendored(VENDOR_DIR / LICENSE_FILENAME, "text/plain")


@page_router.get("/redoc", include_in_schema=False)
async def redoc_page() -> HTMLResponse:
    """The reference itself, with every third-party request pointed back at this origin.

    Stays at `/redoc` rather than moving under the API prefix - see the module docstring;
    the gate depends on it. The prod nginx serves it at `/docs`, rewriting the path, and in
    dev it is reached directly on :8000, exactly where FastAPI's own version used to be.

    `with_google_fonts=False` is what drops the Google Fonts stylesheet. ReDoc falls back to
    the system font stack, which is a fair trade for not disclosing every reader to a third
    party. The favicon is the SPA's, so a deployment shows the app's own icon; in dev the
    backend serves no `/favicon.svg` and the browser logs one 404 for it, which is harmless
    and not worth a second static route to silence.
    """
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="isachore API",
        redoc_js_url=BUNDLE_URL,
        redoc_favicon_url="/favicon.svg",
        with_google_fonts=False,
    )
