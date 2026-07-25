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
