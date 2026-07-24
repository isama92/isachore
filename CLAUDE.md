# isachore

Chore management app for households: chores shared between multiple people,
overdue / due-today / due-soon views, JSON API for future mobile clients.

Human-facing setup, deploy, env vars and the full command list live in
[README.md](README.md). This file is the working guide: conventions, test setup,
and the non-obvious gotchas.

## Workflow

- Work in small steps; the roadmap in README.md is the backlog (tick items off
  when done). When a requirement is ambiguous or a decision shapes UX or
  architecture, ask before building.
- Every feature ships with tests in the same step: backend endpoints get
  `pytest` cases, frontend components/pages get `vitest` cases, covering the
  negative paths too. Both suites must be green before you commit.
- Before committing a completed step, run a read-only review subagent over the
  uncommitted changes (`git status` / `git diff` / `git diff --staged`). Brief it
  explicitly (it has none of this conversation's context): what the feature does,
  its acceptance criteria, and to follow this CLAUDE.md. It reports only, never
  edits. Then triage: fix real issues, skip false positives, note your calls.
  Re-run the suites if a fix touched code, then commit. (The `ship` skill runs
  this flow.)
- Commit per completed step with a descriptive message; the pre-commit hook must
  pass.
- Keep the standard ports (5173/8000/5432 dev, 80 prod). If a port is taken,
  another local project's stack probably holds it: never remap isachore's ports
  and never touch the other stack, ask the user to free it.

## Stack

- **Backend** (`backend/`): FastAPI, async SQLAlchemy 2 + asyncpg, Alembic,
  pydantic-settings. Python 3.13, managed with uv.
- **Frontend** (`frontend/`): React 19 + TypeScript, Vite, Tailwind CSS v4,
  react-router 8, npm. UI built on shadcn/ui (radix-nova style, Radix UI); owned
  component code in `src/components/ui/`.
- **DB**: PostgreSQL 18. **Redis** backs login rate limiting (reachable only as
  `redis:6379` on the compose network, not published to the host).
- **Docker** (`docker/`): everything Docker-related except the dev compose file,
  which stays at the root as `compose.yml` because it is the everyday entry point.
  `docker/` holds `backend.Dockerfile` and `frontend.Dockerfile` (multi-stage),
  `nginx/` (the three nginx configs), and one self-contained
  `compose.prod.<mode>.yml` per prod deployment mode: http / tls / traefik.
- **CI** (`.github/workflows/`): `ci.yml` (ruff + pytest + eslint + prettier +
  `tsc -b` + vitest + a no-push build of both prod images) runs on pull requests
  and is *called* by `publish.yml`, which on every push to `main` pushes
  `ghcr.io/isama92/isachore-{backend,frontend}:latest`. `ci.yml` deliberately has
  no `push` trigger, or every `main` commit would run it twice. One-time manual
  step, not scriptable: GHCR packages are created **private** on first publish and
  inherit nothing from repo visibility, so both must be flipped to public
  (Packages > package > settings) or every `docker compose pull` in README.md's
  Production section fails with `denied`.

## Commands

Full reference (setup, seeding, throttle clearing, prod modes, env vars) is in
README.md. The essentials, run inside the container so the `db` host resolves:

```bash
docker compose up --build                           # dev stack
docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli init --email you@example.com --first-name You --last-name Example  # first admin; no-op if an ACTIVE one exists, else recovers that email
docker compose exec backend python -m app.cli generate-key  # fresh APP_KEY (required outside dev)
docker compose exec backend python -m app.cli seed --fresh   # dev-only reseed (5 users, all password `password`, incl. admin@example.com)

docker compose exec backend uv run pytest           # backend tests (in the container)
cd frontend && npm run test                          # frontend tests
cd backend && uv run ruff check . && uv run ruff format .
cd frontend && npm run lint && npm run format && npm run build   # build also typechecks (tsc -b)
pre-commit run --all-files                           # what the git hook runs
```

## Conventions

- API lives under `/api/v1`, JSON only. Routers in `backend/app/api/v1/`,
  registered in `router.py`.
- **Docker layout / prod is pull-only**: `compose.yml` is the ONLY file with
  `build:` blocks; the prod mode files carry `image:` and nothing else, so a
  deployment is a compose file, a `.env` and a `docker compose pull` with no repo
  checkout on the host. Never add `build:` back to a prod mode file: on a server
  there is no `./backend` to build from, so `up -d` would fail confusingly.
  Three coupled details:
  - Build **contexts stay `./backend` and `./frontend`** even though the
    Dockerfiles moved, because every `COPY`/`--mount=source=` inside them is
    context-relative. Only a `dockerfile: ../docker/<name>.Dockerfile` was added
    (a relative `dockerfile` resolves from the context). The `.dockerignore`
    files stay beside the contexts too, which is where Docker looks for them.
  - The frontend prod stage takes its nginx configs from the **`nginxconf` named
    build context** (`docker/nginx`), not the build context. Any compose block or
    `docker build` that targets `prod` needs
    `additional_contexts: {nginxconf: ./docker/nginx}` / `--build-context
    nginxconf=./docker/nginx`, or `COPY --from=nginxconf` degrades into trying to
    pull an image called `nginxconf`. It is declared on the dev block too for
    exactly that reason.
  - `nginx.tls.conf` is baked to `/etc/nginx/modes/tls.conf`, where it is inert
    (nginx only auto-includes `conf.d/*.conf`), *and* bind-mounted by the tls mode
    from beside the compose file. The baked copy exists so an operator can extract
    the version matching their image; if you change that conf, keep both the
    Dockerfile path and the compose bind mount in step.
- Relative paths in a prod mode file (`.env`, `./volumes/db`, `./nginx.tls.conf`)
  resolve against **the compose file's own directory**, not the repo root. Running
  one from the repo therefore wants a `docker/.env` (already gitignored) and
  creates `docker/volumes/`; `.gitignore`'s `volumes/` entry is unanchored so that
  cannot be committed.
- Config via `app/core/config.py` (pydantic-settings, env vars from `.env`). In
  compose the DB host is `db`; the code default targets `localhost` for host-side
  tooling. `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.
- **Startup config check** (I1): `app/core/startup.py` refuses to boot outside a
  dev environment (`DEV_ENVIRONMENTS` in `config.py`) on an unusable `APP_KEY`,
  `COOKIES_SECURE=false`, or a known-bad `DATABASE_URL` password. Enforced from
  the `lifespan` in `main.py`, deliberately NOT as a `Settings` validator: the
  settings singleton is built at import time by every process, so a validator
  would also break `pytest` and `python -m app.cli`, including the commands
  needed to repair the deploy it rejected. Add new invariants to
  `check_startup_config()` (pure, returns a list of problems) rather than inline.
- Models live in `app/models/` and inherit from `app.db.base.Base` (naming
  convention for Alembic autogenerate). Re-export new models from
  `app/models/__init__.py`: that import is what registers them on
  `Base.metadata`. Pydantic schemas live in `app/schemas/`.
- **Auth**: DB-backed opaque tokens (`auth_tokens` table, SHA-256 hashed), sent
  as an httpOnly `isachore_token` cookie or `Authorization: Bearer`. NO
  self-registration: admins create users; the first admin comes from the `init`
  CLI. Passwords hashed with Argon2 (pwdlib). Protect endpoints by reusing
  `CurrentUser` / `AdminUser` from `app/api/deps.py`; users may never demote or
  deactivate themselves. Note that self-guard is the ONLY floor: nothing counts
  admins, so admins can disable each other down to zero active ones.
- **Admin lockout recovery** (I2): `init` no-ops only while an *active* admin
  exists. With none, it takes over the account named by `--email` (promote,
  re-activate, reset password, clear 2FA, revoke sessions and confirmation links)
  or creates a fresh admin if that email is unknown. Any new "restore access"
  step belongs in `_restore_admin`, which mirrors the revocations `update_user` /
  `reset_two_factor` do for the same changes; forgetting one leaves a stale way
  in. It cannot help while an admin row is active but unusable (2FA lost,
  password forgotten): that needs a direct DB edit first.
- **CSRF**: `CsrfProtectMiddleware` (`app/core/csrf.py`, global, outermost) rejects
  unsafe-method requests (POST/PATCH/PUT/DELETE) that carry an auth cookie
  (`isachore_token` / `isachore_admin_token`) but lack a non-empty `X-CSRF-Token`
  header, with 403. It's a custom-header defence in depth over `SameSite=Lax`,
  sound because there is no CORS. `Authorization: Bearer` requests and public
  pre-auth flows (no cookie) are exempt. The frontend `api` wrapper adds the
  header automatically, so app code needs no changes.
- **User lifecycle**: `users.status` is a `UserStatus` StrEnum
  (`waiting_confirmation` / `active` / `disabled`; stored as a plain String,
  closed set enforced at the schema layer like theme/accent/language) plus a
  `confirmed_at` timestamp. Only `active` users can log in or be impersonated;
  deactivation is a soft delete (`status=disabled`). Login and impersonation gate
  on `status == UserStatus.active`.
- **Email confirmation**: server-wide `app_settings.require_confirmation`
  (single-row table, `get_app_settings`) toggles it. When on, creating a user
  emails a `confirmation_tokens` link (same hashed-opaque-token pattern as auth
  tokens); the public `/api/v1/confirm/{token}` GET/POST sets the password, flips
  to `active` + `confirmed_at`, and auto-logs-in. SMTP is env-only
  (`app/core/config.py`, optional at boot; `smtp_configured()` in
  `app/core/email.py`); enabling confirmation or the test-email button needs it.
  Emails are English-only (the backend has no i18n). Server settings live under
  `/api/v1/settings` (admin) and the **Admin > Server settings** page. Dev SMTP
  goes to the mailpit compose service (http://localhost:8025).
- **Impersonation**: `POST /users/{id}/impersonate` swaps the session cookie to
  the target user and parks the admin's own token in the `isachore_admin_token`
  cookie; `POST /auth/stop-impersonating` restores it. `/auth/me` reports
  `impersonating`; logout ends both sessions.
- **Frontend auth**: `useAuth()` from `src/auth/useAuth.ts`; API calls through the
  `api` wrapper in `src/lib/api.ts` (throws `ApiError`). Protected routes wrap in
  `RequireAuth` / `RequireAdmin` (`src/components/`); authenticated pages render
  under the `TopBar`.
- **Design tokens** (colours, fonts, radii, shadows) live ONLY in
  `frontend/src/index.css`, never hardcode hex in components. They are split by
  role: theme-invariant tokens (fonts, shadows, brand radii) under `@theme`; the
  runtime colour vars under `:root` / `.dark`; the utility mappings (shadcn's
  `--color-*` names and the legacy isachore aliases) under `@theme inline`.
  Tailwind v4 is CSS-first: there is NO `tailwind.config.js` and none should be
  added.
- Import routing from `react-router` (v8), never `react-router-dom`.
- **UI components**: shadcn/ui (radix-nova) live in `frontend/src/components/ui/`,
  config in `components.json`. Import via the `@/` alias and compose classes with
  `cn()` (`@/lib/utils`). Add with `printf 'n\n' | npx shadcn@latest add <name>`
  from `frontend/` (see Gotchas for the `n`). Several primitives are brand
  customised (Button, Input/Textarea, Select trigger, Label + Table headers,
  Monday-first Calendar): keep using them rather than raw HTML, and when one needs
  brand radius/sizing, edit the component itself rather than fighting it with
  per-call classes (see Gotchas).
- **Theme / dark mode**: `ThemeProvider` + `useTheme()` in `frontend/src/theme/`
  (context/provider/hook split, same rule as `src/auth/`). Light mode is the teal
  brand; dark is derived. The toggle is in `TopBar`. Toasts: `toast.success(...)`
  from `sonner`, a single `<Toaster />` in `main.tsx`. Feedback pattern: success
  -> toast, errors -> inline text.
- **i18n**: `react-i18next` + `i18next`. `frontend/src/i18n/` mirrors `theme/`:
  `languages.ts` (the closed `Language` set `'en' | 'it'`, `LANGUAGES` autonyms,
  `DEFAULT_LANGUAGE` = `en`, `isLanguage` guard, `localeFor` -> BCP47),
  `i18n.ts` (singleton init, the typed-keys `declare module` augmentation, the
  `changeLanguage` persist wrapper, the `languageChanged` -> `<html lang>`
  listener), `useLanguage.ts`, and `locales/{en,it}.json`. Initialised by
  `import './i18n/i18n'` in `main.tsx`, no React provider.
  - Any user-facing string: add the key to BOTH `en.json` and `it.json` (identical
    nested trees), render with `useTranslation()` / `t('group.key')`, never
    hardcode. Keys are typed off `en.json`, so a typo or a key missing from
    `en.json` fails `tsc -b`; there is no check that `it.json` matches, so keep it
    in lockstep manually. Keys are grouped by feature, dot-separated. Interpolation
    is `{{var}}`; a conditional becomes two keys; dynamic keys use a literal-union
    template.
  - Persistence (mirrors theme's "persist only on an explicit choice"): the
    `changeLanguage()` wrapper in `i18n.ts` writes `localStorage`
    (`isachore-language`); the `languageChanged` listener only sets `<html lang>`
    and must NOT persist. Use the wrapper (via `useLanguage.setLanguage`, or in
    `AuthProvider`); call bare `i18n.changeLanguage` only for a non-persisting
    reset (test teardown).
  - Per-user `users.language` (nullable; `Language` Literal in `schemas/user.py`,
    kept in sync with the frontend type) is in `UserRead` + `ProfileUpdate`
    (self-service, NOT admin `UserUpdate`, like theme) and adopted by
    `AuthProvider.syncAppearance` (skipped while impersonating). Saved
    optimistically on Profile then PATCHed with rollback. Dates: `formatDate` in
    `lib/chores.ts` uses `localeFor(i18n.language)`.
  - Not translated (deliberate): the brand name `isachore`, the Catppuccin flavour
    names, the 14 accent colour names.
  - Gotcha: a handler closure captures the render-time `t`, so a toast fired right
    after switching language would show the OLD language. The Profile
    language-save success toast reads via the `i18n` singleton (`i18n.t(...)`) so
    it confirms in the just-selected language; rollback/error paths keep the
    closure `t`.
- Pages in `frontend/src/pages/`, one component per route.
- UI mockups: `../isachore-design/Choreo Screens.dc.html` (login = variant 1a,
  add chore = variant 2a; variants are anchor ids).

## Verification

Tests live in `backend/tests/` (pytest) and alongside the code as
`frontend/src/**/*.test.{ts,tsx}` (vitest). Mirror the existing patterns; cover
the negative paths (401/403/400/404/409), not just the happy one.

- **Backend**: `docker compose exec backend uv run pytest` (in the container so
  `db` resolves). Fixtures spin up a throwaway `isachore_test` DB and roll each
  test back via a SAVEPOINT; build cases with `client` / `make_user` /
  `auth_client` from `tests/conftest.py`. Redis is faked with `fakeredis` (the
  `fake_redis` fixture overrides `get_redis`); tune the login throttle per-test by
  monkeypatching `settings.login_*`. Coverage: add
  `--cov=app --cov-report=term-missing --cov-report=html` (report at
  `backend/htmlcov/`).
- **Frontend**: `cd frontend && npm run test` (coverage -> `frontend/coverage/`).
  Use `renderWithProviders` + the `fetch` mock from `src/test/utils.tsx` and the
  synthetic fixtures in `src/test/fixtures.ts`, never real personal data.
  `npm run build` (`tsc -b`) also typechecks tests via `tsconfig.vitest.json`, so
  a test type error breaks the build.
- Beyond the suites, exercise the running dev stack for what they don't cover:
  API with `curl` against `http://localhost:8000/api/v1/...` and a cookie jar
  (`-c/-b`; a cookie-authenticated mutation also needs `-H 'X-CSRF-Token: 1'` or
  the CSRF middleware returns 403); UI via `puppeteer-core` (npm-install it in a
  scratch dir outside the repo) driving the system Chrome at
  `/usr/bin/google-chrome` against `http://localhost:5173`, and screenshot the
  result.

## Gotchas

- After changing `frontend/package.json`: run `npm install` locally (pre-commit
  hooks use local node_modules) AND `docker compose exec frontend npm install` (a
  named volume shadows the container's node_modules).
- After changing `backend/pyproject.toml` deps: the venv is baked into the image
  at `/opt/venv`, so update the lock and reinstall with
  `docker compose exec backend uv sync --no-install-project`, then rebuild
  (`docker compose up -d --build backend`) so the change persists.
- Changing `POSTGRES_*` in `.env` after first boot needs `docker compose down -v`.
- Keep the ruff version in `.pre-commit-config.yaml` (`ruff-pre-commit` rev) in
  sync with the ruff dev dependency in `backend/pyproject.toml`.
- `.github/workflows/ci.yml` restates two toolchain versions that the Dockerfiles
  own: uv (`docker/backend.Dockerfile`'s `ghcr.io/astral-sh/uv` tag) and node
  (`docker/frontend.Dockerfile`'s base image). CI installs them directly rather
  than running the suites inside the images, so bumping either Dockerfile means
  bumping `ci.yml` too or CI silently tests on a different toolchain.
- Never commit `.env`. Two templates, both committed: `.env.example.dev` (dev,
  ready to run) and `.env.example` (the prod reference, placeholders only). Note
  `.gitignore`'s `.env.*` line means any further template needs its own `!`
  negation or it is silently never committed. No real secrets, credentials, or
  production hostnames anywhere in the repo.
- Auth cookies get the `Secure` flag by default (fail-closed). Local dev is plain
  HTTP, so `COOKIES_SECURE=false` (already set in `.env.example.dev`) or login
  cookies won't be sent. Leave it unset/true in production (which must terminate
  TLS). `ENVIRONMENT` does not control cookie security; it gates the dev-only
  `seed` command and the startup check below.
- eslint-plugin-react-hooks v7 (`set-state-in-effect`): never call a
  state-setting function synchronously in a `useEffect` body; do data loading with
  promise chains where setState happens only inside `.then/.catch/.finally` (see
  `AuthProvider.tsx` / `Users.tsx`).
- react-refresh `only-export-components` + `--max-warnings=0`: keep React context,
  provider component, and hook in separate files (see `src/auth/` and
  `src/theme/`). shadcn `ui/**` files co-export a component plus its cva variants;
  an eslint override for `src/components/ui/**` permits that, so leave those files
  in their canonical shape.
- Adding a shadcn component re-pulls its registry deps and offers to overwrite the
  brand-customised `button.tsx`: always decline (`printf 'n\n' | npx shadcn@latest
  add <name>`), then double-install if `package.json` changed (host +
  `docker compose exec frontend npm install`). The radix-nova style ships
  `@import 'shadcn/tailwind.css'` (the `shadcn` runtime dep supplies the
  `data-open`/`data-checked`/... variants), plus the unified `radix-ui` package
  and `tw-animate-css`: don't remove them.
- The shadcn radius scale (`--radius-sm/md/lg/...`) is deliberately NOT redefined
  in `index.css`; brand roundness comes from `rounded-input` (13px) /
  `rounded-button` (15px). tailwind-merge does not dedupe those custom radius
  tokens against a base `rounded-*`, so set radius (and height) in the component's
  own class string (as Button/Input/Select do), not via a call-site `className`.
- Testing Radix in jsdom: build the user with
  `userEvent.setup({ pointerEventsCheck: 0 })` (Radix sets `pointer-events:none`
  on the body when a modal opens) and query portaled content with
  `within(await screen.findByRole('dialog' | 'alertdialog'))` /
  `findByRole('option')`. The required jsdom stubs (`hasPointerCapture`,
  `scrollIntoView`, `ResizeObserver`, `matchMedia`) are in `src/test/setup.ts`,
  don't remove them. `renderWithProviders` wraps `ThemeProvider`, and its
  `afterEach` clears `localStorage` + the `.dark` class so theme state can't leak.
- FastAPI 0.139 registers included routers lazily; to introspect routes use
  `app.openapi()['paths']`, not `app.routes`.
- Alembic files generated inside the container are root-owned on the host:
  `docker compose exec backend chown -R $(id -u):$(id -g) alembic/versions`.
- Smoke-testing prod compose no longer builds anything: the mode files pull
  `:latest` from GHCR, so what you test is the last merge to `main`, not your
  working tree. Use a separate project name and a `docker/.env`, then
  `docker compose -f docker/compose.prod.http.yml -p isachore-prod up -d` (and
  `down -v` afterwards). To exercise a prod *Dockerfile* change before it is
  published, build it directly instead of through compose:
  `docker build -f docker/frontend.Dockerfile --target prod --build-context
  nginxconf=./docker/nginx ./frontend`. On a PR, `ci.yml`'s `images` job does the
  same build, so a broken prod Dockerfile fails the PR rather than the publish.
- Test-infra quirks (handled in the committed setup, don't undo them): coverage
  needs `concurrency = ["greenlet"]` in `pyproject.toml` or async SQLAlchemy
  endpoint bodies read as uncovered; pydantic `EmailStr` rejects `.test` TLDs, so
  use `@example.com` in fixtures; httpx won't send a cookie set with an explicit
  `domain="testserver"`, so set it without a domain.
