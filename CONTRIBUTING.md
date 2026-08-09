# Contributing

Thanks for looking. This is a small household chore-tracking app; the aim is to
keep it easy to read rather than to grow features quickly.

Other documents do most of the work, so this file only covers the process:

- **[guidelines.md](guidelines.md)** for the stack, conventions, architecture,
  database and frontend patterns, testing and code quality. Read it before your
  first change. It is more specific than this file about how the code is meant to
  fit together.
- **[README.md](README.md)** for setup, the commands, env vars, and production.
- **[docs/architecture/](docs/architecture/)** for why one particular subsystem
  works the way it does. [CLAUDE.md](CLAUDE.md) has a table routing you to the
  right one.

## Getting set up

Docker and the Docker Compose plugin run the app:

```bash
cp .env.example.dev .env      # dev template, ready to run as-is
docker compose up --build     # foreground; migrates on boot, the next command wants a second terminal
docker compose exec backend python -m app.cli seed --fresh   # a realistic dataset
```

Then http://localhost:5173, logging in as `admin@example.com` / `password`. Every
seeded user has that password. (`seed` is the shortcut; a real setup instead runs
`python -m app.cli init` to create the first admin, since there is no
self-registration. See the README.)

Two things also want tooling **on the host**, not just in the containers, because
the frontend suite and the git hook both run from `frontend/node_modules`:

```bash
cd frontend && npm install                       # needs Node (24, matching the image)
uv tool install pre-commit && pre-commit install # needs uv
```

## The workflow

**Branch from an up-to-date `main` and open a pull request. Do not commit to
`main`.** A pull request is what makes the checks a *gate*: they run before the
code lands, and a red run blocks the merge. Pushing straight to `main` still runs
the same lint and test jobs, but only after the fact, on a commit that is already
there. A failure then skips publishing rather than preventing the mistake.

```bash
git checkout main && git pull
git checkout -b short-descriptive-name
```

**Every change ships with its tests, in the same commit.** Backend endpoints get
`pytest` cases, frontend components and pages get `vitest` cases, and both cover
the negative paths (401/403/400/404/409) rather than only the happy one. Mirror the
patterns already in `backend/tests/` and `frontend/src/**/*.test.{ts,tsx}`.

**Both suites must be green before you push:**

```bash
docker compose exec backend uv run pytest    # in the container, so `db` resolves
cd frontend && npm run test
```

The hook you installed above fixes formatting and lint rather than just reporting
them, so problems never reach a diff. To sweep everything:
`pre-commit run --all-files`.

## What CI checks

`.github/workflows/ci.yml` is the source of truth and worth skimming; it lints and
tests the backend and frontend, and additionally does two things the suites cannot:

- Runs `alembic upgrade head` against an **empty** database, then `alembic check`.
  The suites build their schema with `create_all` and never execute a migration, so
  nothing else notices a migration that cannot build a fresh database, or a model
  change with no accompanying revision.
- Builds both production images. The prod compose files only ever pull, so this is
  the sole pre-merge check on the Dockerfiles.

A prose-only change runs nothing, by design: both workflows share a `paths-ignore`
list. Merging to `main` runs the lint and test jobs again and then publishes the
images, so a red commit cannot become `latest`.

## House style

Code standards live in **[guidelines.md](guidelines.md)** — language standards,
database and API conventions, frontend patterns, testing discipline, and the
security rules about secrets and personal data. One convention is process rather
than code, so it stays here:

- **Commit messages**: imperative mood, sentence case, no type prefix and no
  trailing full stop. `Add a chore change log`, not `feat: added chore change log.`
  Explain *why* in the body when the reason is not obvious from the diff. Some of
  the history predates this; do not read it as licence.

## Licence

isachore is GPLv3 (see [COPYING](COPYING)). Contributions are accepted under the
same licence.
