# syntax=docker/dockerfile:1
FROM python:3.14-slim AS base
# Keep in sync with the uv version used locally
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# The ReDoc bundle that renders /docs, vendored so the page is entirely first-party.
#
# Proxying FastAPI's stock page meant the browser fetched this from jsdelivr on a floating
# `redoc@2` range with no integrity attribute, and pulled Montserrat and Roboto from Google
# Fonts - an unpinned script running same-origin with the SPA, and every signed-in reader's
# IP going to two third parties for typography. Both close by serving our own copy; see
# app/api/v1/docs.py.
#
# Fetched at build time rather than committed, so a megabyte of minified JavaScript stays out
# of git, and pinned by DIGEST rather than by version, which is the part that matters: the
# version alone still trusts whatever the CDN serves under that tag today. Verified against
# two independent mirrors (jsdelivr and unpkg) when it was chosen.
#
# In /opt, NOT /app: the dev stage ships no source and takes it from the ./backend bind
# mount, which would hide anything placed under /app - the same reason docker-entrypoint.sh
# installs to /usr/local/bin. `prod` does not inherit from this stage, so it copies the
# directory across explicitly.
#
# python:3.14-slim carries no curl, and Python is right here, so urllib plus hashlib does it
# with no apt layer. The digest check is `RUN`-time, so a mismatch fails the build.
#
# Two consequences of fetching rather than committing, both acceptable and neither obvious:
# the image build now needs jsdelivr reachable, so a CDN outage or an egress-restricted
# runner fails `ci.yml`'s images job and `publish.yml` with a urlopen traceback rather than
# anything self-explanatory; and the bundle's LICENSE sibling has to come along, because the
# first line of the bundle points at it and shipping the pointer without the file would
# leave a dangling attribution for third-party MIT code.
#
# Bumping ReDoc means changing BOTH args here (a version without its digest pins nothing)
# and `REDOC_VERSION` in app/api/v1/docs.py, which versions the url for cache-busting.
ARG REDOC_VERSION=2.5.3
ARG REDOC_SHA256=1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0
RUN python - "$REDOC_VERSION" "$REDOC_SHA256" <<'PY'
import hashlib, pathlib, sys, urllib.request

version, expected = sys.argv[1], sys.argv[2]
base = f"https://cdn.jsdelivr.net/npm/redoc@{version}/bundles"


def fetch(name: str) -> bytes:
    return urllib.request.urlopen(f"{base}/{name}", timeout=60).read()  # noqa: S310


payload = fetch("redoc.standalone.js")
actual = hashlib.sha256(payload).hexdigest()
if actual != expected:
    raise SystemExit(f"redoc {version}: expected sha256 {expected}, got {actual}")

target = pathlib.Path("/opt/redoc")
target.mkdir(parents=True, exist_ok=True)
(target / "redoc.standalone.js").write_bytes(payload)
# Not digest-pinned, and deliberately not fatal: it is an attribution file the app never
# serves, so a missing one should not stop a build that has already verified the code.
try:
    (target / "redoc.standalone.js.LICENSE.txt").write_bytes(
        fetch("redoc.standalone.js.LICENSE.txt")
    )
except Exception as exc:  # noqa: BLE001
    print(f"warning: could not vendor the redoc LICENSE file: {exc}")
print(f"vendored redoc {version} ({len(payload)} bytes, sha256 {actual})")
PY

# dev: dependencies only; source code arrives via the compose bind mount.
# The venv lives at /opt/venv so the ./backend:/app mount cannot clobber it.
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project
# After the sync so editing the entrypoint doesn't invalidate the dependency
# layer. Installed to /usr/local/bin, not /app, because this stage ships no
# source at all: at /app the ./backend bind mount would be its only source.
# --chmod so the exec bit cannot be lost with the image still building green: an
# unexecutable entrypoint kills every container in every mode at once.
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS builder
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev
COPY . /app

FROM python:3.14-slim AS prod
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder /opt/venv /opt/venv
# The vendored ReDoc bundle. Needs its own COPY because this stage starts from a bare
# python image rather than `base`, so it inherits nothing the base stage fetched.
COPY --from=builder /opt/redoc /opt/redoc
COPY --from=builder --chown=app:app /app /app
# Create the avatars storage dir owned by the non-root app user so the mounted
# named volume inherits writable ownership on first mount.
RUN mkdir -p /app/storage/avatars && chown -R app:app /app/storage
# Straight from the build context (the same ./backend), which also leaves an
# inert copy at /app via the COPY above; /usr/local/bin is the one ENTRYPOINT
# names, so a future bind mount over /app cannot shadow it. See the dev stage for
# why the mode is set here rather than inherited from the checkout.
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
USER app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
