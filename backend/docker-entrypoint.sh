#!/bin/sh
# Container entrypoint for the backend image (dev and prod stages alike).
#
# Brings the schema up to date before the web process starts, so deploying an
# upgrade is `pull` + `up -d` with no manual migration step to forget. Lives
# under backend/ because that is the Docker build context.
set -e

# Only when the container is starting the web server. `docker compose run --rm
# --no-deps backend python -m app.cli generate-key` is the documented way out of
# a deploy the startup check refuses to boot (see README, Production checklist)
# and deliberately runs with no database at all, so migrating unconditionally
# would break the very recovery path that has to keep working. Same reasoning
# spares `run --rm backend alembic ...` from being upgraded behind its own back.
case "$1" in
uvicorn)
    if [ "${RUN_MIGRATIONS:-true}" = "false" ]; then
        echo "entrypoint: RUN_MIGRATIONS=false, skipping alembic upgrade head"
    else
        echo "entrypoint: running alembic upgrade head"
        # set -e applies: a failed migration exits non-zero, so the container
        # dies (and crash-loops under restart: unless-stopped) instead of
        # serving against a schema the code does not match.
        alembic upgrade head
    fi
    ;;
esac

exec "$@"
