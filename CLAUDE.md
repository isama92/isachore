# isachore

Chore management app for households: chores shared between multiple people, overdue /
due-today / due-soon views, JSON API for future mobile clients.

## Read this first

- **[guidelines.md](guidelines.md)** — the stack, conventions, architecture, database and
  frontend patterns, testing discipline, code quality. Read it before your first change.
- **[README.md](README.md)** — setup, env vars, operations, production, the todo backlog.
- **[docs/architecture/](docs/architecture/)** — why one subsystem is the way it is. Routed
  from the table below.

This file is the map, not the manual. It carries only the workflow, the everyday commands,
and the traps that bite before you would think to look anything up.

## Workflow

- Work in small steps; the todo list in README.md is the backlog (tick items off when done).
  When a requirement is ambiguous or a decision shapes UX or architecture, ask before
  building.
- **Never commit to `main`.** Branch at the *start* of a step, before the first edit, and
  always from an updated `main` rather than from whatever branch you are on:
  `git checkout main && git pull`, then `git checkout -b <name>`. Finish by pushing and
  opening a PR (`gh pr create`).

  Beyond review, the PR is what makes the checks a *gate*: `ci.yml` triggers on
  `pull_request`, so they run before the code lands. A direct push to `main` does still run
  them, via `publish.yml` calling `ci.yml`, but only after the fact on a commit that is
  already there, and a failure then merely skips publishing. The git history predates this
  rule and is mostly direct commits to `main`; do not read that as permission.
- **Every feature ships with tests in the same step**, covering the negative paths too.
  Backend endpoints get `pytest` cases, frontend components and pages get `vitest` cases.
  Both suites must be green before you commit.
- **Before committing a completed step, run a read-only review subagent** over the
  uncommitted changes (`git status` / `git diff` / `git diff --staged`). Brief it explicitly —
  it has none of this conversation's context: what the feature does, its acceptance criteria,
  and to follow guidelines.md. It reports only, never edits. Then triage: fix real issues,
  skip false positives, note your calls. Re-run the suites if a fix touched code, then
  commit. (The `ship` skill runs this flow.)
- Commit per completed step with a descriptive message; the pre-commit hook must pass.
- **Keep the standard ports** (5173/8000/5432 dev, 80 prod). If a port is taken, another
  local project's stack probably holds it: never remap isachore's ports and never touch the
  other stack — ask the user to free it.

## Commands

Run inside the container so the `db` host resolves. Full reference in README.md.

```bash
docker compose up --build                            # dev stack; the entrypoint runs `alembic upgrade head` on boot
docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head     # escape hatch: boot already did this
docker compose run --rm backend alembic upgrade head # ...and this is the one that works when boot FAILED
docker compose exec backend python -m app.cli init --email you@example.com --first-name You --last-name Example
docker compose exec backend python -m app.cli generate-key   # fresh APP_KEY (required outside dev)
docker compose exec backend python -m app.cli seed --fresh   # dev-only reseed (5 users, all password `password`)

docker compose exec backend uv run pytest            # backend tests
cd frontend && npm run test                          # frontend tests
cd backend && uv run ruff check . && uv run ruff format .
cd frontend && npm run lint && npm run format && npm run build   # build also typechecks (tsc -b)
pre-commit run --all-files                           # what the git hook runs
```

## Where things are

**Read the matching document before editing, not after.** Each one exists because the
subsystem has non-obvious constraints that a reasonable change breaks silently.

| Touching | Read first |
|---|---|
| Anything with a date, a due calculation or a day boundary | [docs/architecture/timezones.md](docs/architecture/timezones.md) |
| Chores, occurrences, assignment, completion, skipping, rich text | [docs/architecture/chores.md](docs/architecture/chores.md) |
| Households, roles, members, invitations, the household log | [docs/architecture/households.md](docs/architecture/households.md) |
| Login, sessions, CSRF, 2FA, SSO, impersonation, confirmation, access tokens | [docs/architecture/auth.md](docs/architecture/auth.md) |
| Tables, theme, i18n, PWA, shadcn, the rich text editor | [docs/architecture/frontend.md](docs/architecture/frontend.md) |
| Docker, nginx, CI workflows, the committed OpenAPI spec | [docs/architecture/deployment.md](docs/architecture/deployment.md) |
| Adding a route, model, page or test; anything not above | [guidelines.md](guidelines.md) |

## Traps that bite first

Each of these has cost real work. The detail is in the linked document; this list exists so
you know there *is* one.

- **`pytest` never executes a migration.** The fixtures build the schema from
  `Base.metadata.create_all`, so a broken chain passes both suites. CI's empty-database step
  is the only guard.
- **Re-export every new model from `app/models/__init__.py`**, and add its table to
  `db/seed.py`'s `_WIPE_ORDER`. Miss the first and autogenerate produces an *empty* migration
  while every test fails on a missing relation.
- **Never `AT TIME ZONE <column>` at runtime.** A name Python and Postgres do not share
  raises inside the query — a 500 from SQL, not a 422 from a validator.
- **`chore_occurrences.scheduled_for` is local midnight in the household's zone**, not UTC
  midnight. Everything about due dates rests on this.
- **Nothing provisions a household.** Not `POST /admin/users`, not `cli init`, not confirming
  an account. Zero households is a normal, reachable state that nothing may assume away.
- **Closed-set columns are `String` + a `StrEnum`**, enforced at the schema layer. Adding a
  value needs no migration; *removing* one needs a data migration before the deploy.
- **The wire carries strings, not enums**, for those columns. Coercing on read 500s on a row a
  newer release wrote.
- **A handler returning a `Response` subclass documents itself as an unconstrained 200** and
  drops every other branch. Restate `response_model` / `responses=` / `status_code=`.
- **Regenerate `docs/api/openapi.yaml` after a backend change**, or
  `tests/test_openapi_spec.py` fails.
- **Decline every shadcn overwrite** (`printf 'n\n' | npx shadcn@latest add <name>`).
  `button.tsx` holds brand styling; `chart.tsx` holds a security-relevant sanitiser.
- **Double-install after a `package.json` *or lockfile* change** — host *and*
  `docker compose exec frontend npm install`. A named volume shadows the container's tree, so
  skipping it leaves the dev stack on the old one silently.
- **A test for one clause of a compound condition must satisfy every other clause**, or it
  pins nothing. Delete the guard and watch it fail. Where the decision is *not* to do
  something, the mutation is an addition instead.
- **Never commit `.env`**, and no secrets, credentials or production hostnames anywhere in
  the repo.
