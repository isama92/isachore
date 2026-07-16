# isachore

Chore management app for households: chores shared between multiple people,
overdue / due-today / due-soon views, JSON API for future mobile clients.

## Workflow

- Work happens in small steps — the TODO list in README.md is the roadmap:
  check it for what's next and tick items off when they're done.
- When requirements are ambiguous or a decision shapes UX/architecture, ask
  the user before building; don't assume.
- Every feature ships with tests in the same step: backend endpoints get
  `pytest` cases, frontend components/pages get `vitest` cases, covering the
  negative paths too (not just the happy one). Both suites must be green before
  you commit. See Verification for how to run them.
- Once the suites are green and before you commit a completed step, run a
  read-only review subagent over the uncommitted changes (`git status` /
  `git diff` / `git diff --staged`). Brief it explicitly, because it starts with
  none of this conversation's context: what the feature should do, its
  acceptance criteria, and to follow this CLAUDE.md for conventions. It reports
  findings only and must not edit files. Then triage the report yourself: fix the
  real issues, skip the false positives, and note what you decided before moving
  on. Re-run the suites if a fix touched code, then commit.
- Commit per completed step (descriptive message; the pre-commit hook must pass).
- Keep the standard ports (5173/8000/5432 dev, 80 prod). If a port is taken,
  another local project's stack probably holds it — never remap isachore's
  ports and never touch the other stack; ask the user to free it.

## Stack

- **Backend** (`backend/`): FastAPI, async SQLAlchemy 2 + asyncpg, Alembic,
  pydantic-settings. Python 3.13, managed with uv.
- **Frontend** (`frontend/`): React 19 + TypeScript, Vite, Tailwind CSS v4,
  react-router 8, npm.
- **DB**: PostgreSQL 18. **Redis** backs login rate limiting (reachable only as
  `redis:6379` on the compose network, not published to the host). **Docker** for
  dev and prod (multi-stage Dockerfiles, `compose.yml` dev / `compose.prod.yml` prod).

## Commands

```bash
docker compose up --build                          # dev stack: db + backend (reload) + frontend (HMR)
docker compose -f compose.prod.yml up --build      # prod: nginx on :80 serving SPA + /api proxy

docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head   # run alembic INSIDE the container so host "db" resolves
docker compose exec backend python -m app.cli create-admin --email you@example.com --name You

cd backend && uv run ruff check . && uv run ruff format .
cd frontend && npm run lint && npm run format && npm run build   # build also typechecks (tsc -b)

docker compose exec backend uv run pytest          # backend tests (run in the container so host "db" resolves)
docker compose exec backend uv run pytest --cov=app --cov-report=term-missing --cov-report=html  # + coverage -> backend/htmlcov/
cd frontend && npm run test                        # frontend tests (npm run test:coverage -> frontend/coverage/)

pre-commit run --all-files                         # what the git hook runs
```

## Conventions

- API lives under `/api/v1`, JSON only. Routers in `backend/app/api/v1/`,
  registered in `router.py`.
- Config via `app/core/config.py` (pydantic-settings, env vars from `.env`).
  In compose the DB host is `db`; the code default targets `localhost` for
  host-side tooling. `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.
- Models live in `app/models/` and inherit from `app.db.base.Base` (naming
  convention for Alembic autogenerate). Re-export new models from
  `app/models/__init__.py` — that import is what registers them on
  `Base.metadata` for autogenerate. Pydantic schemas live in `app/schemas/`.
- Auth: DB-backed opaque tokens (`auth_tokens` table, SHA-256 hashed), sent as
  an httpOnly `isachore_token` cookie or `Authorization: Bearer`. NO
  self-registration — admins create users; the first admin comes from the
  `create-admin` CLI. Passwords hashed with Argon2 (pwdlib). Protect endpoints
  by reusing `CurrentUser` / `AdminUser` from `app/api/deps.py`; soft delete
  only (`is_active=false`), and users may never demote or deactivate themselves.
- Impersonation: `POST /users/{id}/impersonate` swaps the session cookie to the
  target user and parks the admin's own token in the `isachore_admin_token`
  cookie; `POST /auth/stop-impersonating` restores it. `/auth/me` reports
  `impersonating`; logout ends both sessions.
- Frontend auth: `useAuth()` from `src/auth/useAuth.ts`; API calls through the
  `api` wrapper in `src/lib/api.ts` (throws `ApiError`). Protected routes wrap
  in `RequireAuth` / `RequireAdmin` (`src/components/`); authenticated pages
  render under the `TopBar`.
- Design tokens (colours, fonts, radii, shadows) live ONLY in
  `frontend/src/index.css` under `@theme` — never hardcode hex values in
  components. Tailwind v4 is CSS-first: there is NO tailwind.config.js and
  none should be added.
- Import routing from `react-router` (v8) — never `react-router-dom`.
- Pages in `frontend/src/pages/`, one component per route.
- UI mockups: `../isachore-design/Choreo Screens.dc.html` (login = variant 1a,
  "add chore" = variant 2a; variants are anchor ids in that file).

## Verification

Every feature needs automated tests, and both suites must pass before you
commit. Tests live in `backend/tests/` (pytest) and alongside the code as
`frontend/src/**/*.test.{ts,tsx}` (vitest) — mirror the patterns already there.

- Backend: `docker compose exec backend uv run pytest` (in the container so host
  `db` resolves). Fixtures spin up a throwaway `isachore_test` DB and roll each
  test back via a SAVEPOINT, so tests are isolated and leave no residue; build
  cases with the `client` / `make_user` / `auth_client` fixtures from
  `tests/conftest.py`. Cover the negative paths (401/403/400/404/409), not just
  the happy one. Redis is faked with `fakeredis` (the `fake_redis` fixture
  overrides `get_redis`), so tests need no real Redis and stay isolated; tune the
  login throttle per-test by monkeypatching `settings.login_*`. Coverage: add
  `--cov=app --cov-report=term-missing --cov-report=html` (report at
  `backend/htmlcov/`).
- Frontend: `cd frontend && npm run test` (coverage: `npm run test:coverage` ->
  `frontend/coverage/`). Use `renderWithProviders` + the `fetch` mock from
  `src/test/utils.tsx` and the synthetic fixtures in `src/test/fixtures.ts` —
  never real personal data. `npm run build` (`tsc -b`) also typechecks tests via
  `tsconfig.vitest.json`, so a type error in a test breaks the build.
- Beyond the suites, still exercise the running dev stack for anything they
  don't cover (visual/UX, integration across the proxy):
  - API: curl against `http://localhost:8000/api/v1/...` with a cookie jar
    (`-c/-b`).
  - UI: headless browser via `puppeteer-core` (npm-install it in a scratch dir
    outside the repo) driving the system Chrome at `/usr/bin/google-chrome`
    against `http://localhost:5173`, and screenshot the results.
- The local dev DB may already contain seed users created during earlier
  sessions (e.g. `admin@example.com` / `admin12345` — dev-only, this machine
  only). Create your own via the `create-admin` CLI if missing.

## Gotchas

- After changing `frontend/package.json`: run `npm install` locally (pre-commit
  hooks use local node_modules) AND `docker compose exec frontend npm install`
  (a named volume shadows the container's node_modules).
- After changing `backend/pyproject.toml` deps: the venv is baked into the image
  at `/opt/venv`, so update the lock and reinstall with
  `docker compose exec backend uv sync --no-install-project`, and rebuild the
  image (`docker compose up -d --build backend`) so the change persists.
- Changing `POSTGRES_*` in `.env` after first boot needs `docker compose down -v`.
- Keep the ruff version in `.pre-commit-config.yaml` (`ruff-pre-commit` rev) in
  sync with the ruff dev dependency in `backend/pyproject.toml`.
- Never commit `.env`; dev-only placeholder credentials belong in `.env.example`.
  No real secrets, credentials, or production hostnames anywhere in the repo.
- Auth cookies get the `Secure` flag by default (fail-closed). Local dev is
  served over plain HTTP, so set `COOKIES_SECURE=false` in the dev `.env` or
  login cookies won't be sent. Leave it unset/true in production (which must
  terminate TLS). `ENVIRONMENT` is now just an informational deployment marker
  and no longer controls cookie security.
- eslint-plugin-react-hooks v7 (`set-state-in-effect`): never call a
  state-setting function synchronously in a `useEffect` body — do data loading
  with promise chains where setState happens only inside `.then/.catch/.finally`
  callbacks (see `AuthProvider.tsx` / `Users.tsx` for the pattern).
- react-refresh `only-export-components` + `--max-warnings=0`: keep React
  context, provider component, and hook in separate files (see `src/auth/`).
- FastAPI 0.139 registers included routers lazily; to introspect routes use
  `app.openapi()['paths']`, not `app.routes`.
- Alembic files generated inside the container are root-owned on the host:
  `docker compose exec backend chown -R $(id -u):$(id -g) alembic/versions`.
- To smoke-test prod compose without touching the running dev stack, use a
  separate project name: `docker compose -f compose.prod.yml -p isachore-prod
  up --build -d` (and `down -v` afterwards).
- Test-infra quirks (all handled in the committed setup, don't undo them):
  coverage needs `concurrency = ["greenlet"]` in `pyproject.toml` or async
  SQLAlchemy endpoint bodies read as uncovered; pydantic `EmailStr` rejects
  `.test` TLDs, so use `@example.com` in fixtures; httpx won't send a cookie set
  with an explicit `domain="testserver"` — set it without a domain.
