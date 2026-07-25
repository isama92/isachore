# Contributing

Thanks for looking. This is a small household chore-tracking app; the aim is to
keep it easy to read rather than to grow features quickly.

Two documents do most of the work, so this file only covers the process:

- **[README.md](README.md)** for setup, the commands, env vars, and production.
- **[CLAUDE.md](CLAUDE.md)** for conventions, architecture and the non-obvious
  gotchas. Read it before your first change. It is the working guide, and it is
  more specific than this file about how the code is meant to fit together.

## Getting set up

Docker and the Docker Compose plugin run the app:

```bash
cp .env.example.dev .env      # dev template, ready to run as-is
docker compose up --build     # foreground; the next commands want a second terminal
docker compose exec backend alembic upgrade head
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

- **Commit messages**: imperative mood, sentence case, no type prefix and no
  trailing full stop. `Add a chore change log`, not `feat: added chore change log.`
  Explain *why* in the body when the reason is not obvious from the diff. Some of
  the history predates this; do not read it as licence.
- **Changed a model?** Generate a revision in the same change:
  `docker compose exec backend alembic revision --autogenerate -m "describe change"`
  (then `chown` it, see CLAUDE.md). CI's `alembic check` fails without it.
- **Any user-facing string** needs a key in **both** `frontend/src/i18n/locales/en.json`
  and `it.json`, with identical nested trees. Keys are typed off `en.json`, so a
  missing English key fails the build, but nothing checks that Italian matches:
  keep it in lockstep by hand.
- **Colours, fonts, radii and shadows** live only in `frontend/src/index.css`.
  Never hardcode a hex value in a component.
- **No secrets, credentials or production hostnames** anywhere in the repo. `.env`
  is gitignored. Of the two committed templates, `.env.example` holds placeholders
  only; `.env.example.dev` holds the documented dev credentials and nothing real.

## Licence

isachore is GPLv3 (see [COPYING](COPYING)). Contributions are accepted under the
same licence.
