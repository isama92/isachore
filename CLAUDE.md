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
  react-router 8, npm. UI is built on shadcn/ui (radix-nova style, Radix UI);
  the owned component code lives in `src/components/ui/`.
- **DB**: PostgreSQL 18. **Redis** backs login rate limiting (reachable only as
  `redis:6379` on the compose network, not published to the host). **Docker** for
  dev and prod (multi-stage Dockerfiles, `compose.yml` dev / `compose.prod.yml` prod).

## Commands

```bash
docker compose up --build                          # dev stack: db + backend (reload) + frontend (HMR)
docker compose -f compose.prod.yml up --build      # prod: nginx on :80 serving SPA + /api proxy

docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head   # run alembic INSIDE the container so host "db" resolves
docker compose exec backend python -m app.cli init --email you@example.com --first-name You --last-name Example  # one-time bootstrap of the first admin; no-op if an admin exists

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
  self-registration — admins create users; the first admin comes from the one-
  time `init` CLI (no-op if an admin already exists). Passwords hashed with
  Argon2 (pwdlib). Protect endpoints by reusing `CurrentUser` / `AdminUser` from
  `app/api/deps.py`; users may never demote or deactivate themselves.
- User lifecycle: `users.status` is a `UserStatus` StrEnum
  (`waiting_confirmation` / `active` / `disabled`; stored as a plain String,
  closed set enforced at the schema layer like theme/accent/language) plus a
  `confirmed_at` timestamp. Only `active` users can log in or be impersonated;
  deactivation is a soft delete (`status=disabled`). Login/impersonation gate on
  `status == UserStatus.active`.
- Email confirmation: server-wide `app_settings.require_confirmation` (single-
  row table, `get_app_settings`) toggles it. When on, creating a user emails a
  `confirmation_tokens` link (same hashed-opaque-token pattern as auth tokens);
  the public `/api/v1/confirm/{token}` GET/POST sets the password, flips to
  `active` + `confirmed_at`, and auto-logs-in. SMTP is env-only
  (`app/core/config.py`, optional at boot; `smtp_configured()` in
  `app/core/email.py`); enabling confirmation or the test-email button needs it.
  Emails are English-only (backend has no i18n). Server settings live under
  `/api/v1/settings` (admin) and the **Admin → Server settings** page. Dev SMTP
  goes to the mailpit compose service (http://localhost:8025).
- Impersonation: `POST /users/{id}/impersonate` swaps the session cookie to the
  target user and parks the admin's own token in the `isachore_admin_token`
  cookie; `POST /auth/stop-impersonating` restores it. `/auth/me` reports
  `impersonating`; logout ends both sessions.
- Frontend auth: `useAuth()` from `src/auth/useAuth.ts`; API calls through the
  `api` wrapper in `src/lib/api.ts` (throws `ApiError`). Protected routes wrap
  in `RequireAuth` / `RequireAdmin` (`src/components/`); authenticated pages
  render under the `TopBar`.
- Design tokens (colours, fonts, radii, shadows) live ONLY in
  `frontend/src/index.css` — never hardcode hex values in components. Since the
  shadcn adoption they are split by role: theme-invariant tokens (fonts,
  shadows, brand radii) under `@theme`; the runtime colour vars under
  `:root`/`.dark` (light/dark values); and the utility mappings (both shadcn's
  `--color-*` names and the legacy isachore aliases) under `@theme inline`.
  Tailwind v4 is CSS-first: there is NO tailwind.config.js and none should be
  added.
- Import routing from `react-router` (v8) — never `react-router-dom`.
- UI components: shadcn/ui (radix-nova style) live in
  `frontend/src/components/ui/`, config in `components.json`. Import via the
  `@/` alias (`@/components/ui/button`) and compose classes with `cn()`
  (`@/lib/utils`). Add components with
  `printf 'n\n' | npx shadcn@latest add <name>` from `frontend/` (see Gotchas
  for the `n`). Several primitives are customised to the brand and you should
  keep using them rather than raw HTML: Button (brand default variant +
  `rounded-button`), Input/Textarea and the Select trigger (`rounded-input`,
  `h-10`), Label + Table headers (uppercase micro-label), Calendar
  (Monday-first). When a primitive needs brand radius/sizing, edit the
  component itself — don't fight it with per-call classes (see Gotchas).
- Theme/dark mode: `ThemeProvider` + `useTheme()` in `frontend/src/theme/`
  (context/provider/hook split, same rule as `src/auth/`). Light mode is the
  teal brand; dark is derived. The toggle is in `TopBar`. Toasts:
  `toast.success(...)` from `sonner`; a single `<Toaster />` is mounted in
  `main.tsx`. Feedback pattern: success -> toast, errors -> inline text.
- i18n / translations: `react-i18next` + `i18next`. The `frontend/src/i18n/`
  module mirrors `theme/`: `languages.ts` (the closed `Language` set = `'en' |
  'it'`, autonym `LANGUAGES` metadata, `DEFAULT_LANGUAGE` = `en`, `isLanguage`
  guard, `localeFor` → BCP47 for dates), `i18n.ts` (singleton init, the typed-
  keys `declare module 'i18next'` augmentation, the `changeLanguage` persist
  wrapper, and the `languageChanged` → `<html lang>` listener), `useLanguage.ts`
  (`{ language, setLanguage }` hook), and `locales/{en,it}.json`. The singleton
  is initialised by `import './i18n/i18n'` in `main.tsx` — no React provider.
  - Adding ANY user-facing string: add the key to BOTH `en.json` and `it.json`
    (identical nested trees), then render it with `useTranslation()` /
    `t('group.key')` — never hardcode. Keys are typed off `en.json`, so a typo
    or a key missing from `en.json` fails `tsc -b`; keep `it.json` in lockstep
    (there is no compiler check that `it.json` matches, so drift is silent).
    Keys are grouped by feature (`common`/`login`/`chores`/`profile`/`users`/
    `options`/…), dot-separated (Laravel-style). Interpolation is `{{var}}`;
    a two-way conditional becomes two keys; dynamic keys use a literal-union
    template (`t(`options.repeat.${value}`)` where `value` is a literal union).
  - Persistence mirrors theme's "persist only on an explicit choice": the
    `changeLanguage()` wrapper in `i18n.ts` writes `localStorage`
    (`isachore-language`); the `languageChanged` listener only sets `<html
    lang>` and must NOT persist. Use the wrapper (via `useLanguage.setLanguage`,
    or directly in `AuthProvider`); call bare `i18n.changeLanguage` only for a
    non-persisting reset (e.g. test teardown in `src/test/setup.ts`).
  - Per-user field `users.language` (nullable; `Language = Literal["en","it"]`
    in `schemas/user.py`, kept in sync with the frontend `Language` type) is in
    `UserRead` + `ProfileUpdate` (self-service; NOT admin `UserUpdate`, same as
    theme) and adopted by `AuthProvider.syncAppearance` (skipped while
    impersonating). The selector is on the Profile page, saved optimistically
    then PATCHed with rollback (like `saveAppearance`). Dates: `formatDate` in
    `lib/chores.ts` uses `localeFor(i18n.language)`.
  - Not translated (deliberate): the brand name `isachore`, the Catppuccin
    flavour names, and the 14 accent colour names.
  - Gotcha: a handler closure captures the render-time `t`, so a toast fired
    right after switching language would show the OLD language. The Profile
    language-save success toast reads via the `i18n` singleton (`i18n.t(...)`)
    so it confirms in the just-selected language; rollback/error paths keep
    using the closure `t` (already the correct, restored language).
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
  only). Create your own via the `init` CLI if missing.

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
  context, provider component, and hook in separate files (see `src/auth/` and
  `src/theme/`). shadcn `ui/**` files co-export a component plus its cva
  variants; an eslint override for `src/components/ui/**` permits that, so leave
  those files in their canonical shape.
- Adding a shadcn component re-pulls its registry deps and offers to overwrite
  the brand-customised `button.tsx` — always decline
  (`printf 'n\n' | npx shadcn@latest add <name>`), then double-install if
  `package.json` changed (host + `docker compose exec frontend npm install`).
  The radix-nova style ships `@import 'shadcn/tailwind.css'` (the `shadcn`
  runtime dep supplies the `data-open`/`data-checked`/... variants the
  components rely on), plus the unified `radix-ui` package and `tw-animate-css`
  — don't remove them.
- The shadcn radius scale (`--radius-sm/md/lg/...`) is deliberately NOT
  redefined in `index.css`; brand roundness comes from `rounded-input` (13px) /
  `rounded-button` (15px). tailwind-merge does not dedupe those custom radius
  tokens against a base `rounded-*`, so set radius (and height) in the
  component's own class string, as Button/Input/Select already do — not via a
  call-site `className`.
- Testing Radix components in jsdom: build the user with
  `userEvent.setup({ pointerEventsCheck: 0 })` (Radix sets `pointer-events:none`
  on the body when a modal opens) and query portaled content with
  `within(await screen.findByRole('dialog' | 'alertdialog'))` /
  `findByRole('option')`. The required jsdom stubs (`hasPointerCapture`,
  `scrollIntoView`, `ResizeObserver`, `matchMedia`) are in `src/test/setup.ts`
  — don't remove them. `renderWithProviders` wraps `ThemeProvider`, and its
  `afterEach` clears `localStorage` + the `.dark` class so theme state can't
  leak between tests.
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
