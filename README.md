# isachore

Chore management for households. Keep track of who does what, see what's
overdue, what has to be done today, and what's coming up — shared between
multiple people, with a JSON API so mobile clients can join later.

## Stack

| Layer    | Tech                                                              |
| -------- | ----------------------------------------------------------------- |
| Backend  | FastAPI · async SQLAlchemy 2 · asyncpg · Alembic · Python 3.13 (uv) |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS v4 · react-router 8 · shadcn/ui (Radix) |
| Database | PostgreSQL 18                                                     |
| Infra    | Docker everywhere (dev and prod)                                  |

## Quickstart (dev)

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli init --email you@example.com --first-name You --last-name Example
```

There is no self-registration. The first admin is bootstrapped with the `init`
command above (it prompts for a password). `init` is a one-time bootstrap: it
does nothing if an admin already exists, so it's safe to leave in a deploy
script. Every other user is created by an admin in the UI under
**Admin → Users**.

If **Admin → Server settings → Require user confirmation** is on, a new user
starts as *waiting confirmation* and receives an email with a link to set their
own password; only then does the account become active. When it's off, the
admin sets the password in the create form and the user is active immediately.
Confirmation needs SMTP configured (see `.env.example`); in dev, emails are
captured by mailpit at http://localhost:8025.

Login is rate limited: repeated failures lock out both the email and the client
IP for a window. To lift a lockout without waiting it out, clear the throttle:

```bash
docker compose exec backend python -m app.cli clear-login-throttle       # clear every lockout
docker compose exec backend python -m app.cli clear-login-throttle 42    # clear one user (by id)
```

With a user id it clears only that user's per-email counter (a user maps to an
email but never to an IP); with no argument it clears every counter, per-email
and per-IP.

To fill the app with a rich dataset for manual testing (five users, a solo
household each plus one shared household, and many chores covering every option
with completion history), run the seeder. It refuses to run outside a dev
environment; `--fresh` wipes all app data first so it doubles as a reset.

```bash
docker compose exec backend python -m app.cli seed --fresh
```

Every seeded user's password is `password`; the admin is `admin@example.com`.

| Service       | URL                                     |
| ------------- | --------------------------------------- |
| Frontend      | http://localhost:5173                   |
| Backend API   | http://localhost:8000/api/v1            |
| API docs      | http://localhost:8000/docs              |
| Health check  | http://localhost:5173/api/v1/health     |
| Postgres      | localhost:5432                          |
| Mailpit (dev email) | http://localhost:8025             |

### Production

The prod stack (`compose.prod.yml`) builds the SPA, serves it and reverse-proxies
the API through nginx, and sends security response headers (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy; plus HSTS in the TLS mode). The base
stack publishes no host port on its own, so pick a mode.

Behind your own TLS-terminating reverse proxy (recommended; e.g. Traefik). nginx
stays on HTTP and the proxy handles TLS, the HTTP->HTTPS redirect and HSTS.
`compose.prod.traefik.yml` is a template: edit the router rule, entrypoints, cert
resolver and external network to match your Traefik.

```bash
docker compose -f compose.prod.yml -f compose.prod.traefik.yml up --build
```

nginx terminates TLS with your own certificate (no front proxy). Put
`fullchain.pem` and `privkey.pem` in `./volumes/certs`, then:

```bash
docker compose -f compose.prod.yml -f compose.prod.tls.yml up --build
```

Plain HTTP on :80 for a local smoke test only (never internet-facing):

```bash
docker compose -f compose.prod.yml -f compose.prod.http.yml up --build
```

In production set `APP_BASE_URL=https://<your-domain>` in `.env` and never set
`COOKIES_SECURE=false` (prod forces Secure cookies, which need TLS). A self-signed
certificate for testing the TLS mode:

```bash
mkdir -p volumes/certs && openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout volumes/certs/privkey.pem -out volumes/certs/fullchain.pem \
  -days 365 -subj "/CN=localhost"
```

Note: testing the TLS mode on `localhost` makes your browser pin HSTS for
`localhost` for two years, which can force other local HTTP projects on
`localhost` to HTTPS and break them. Prefer a throwaway hostname, or clear it
afterwards at `chrome://net-internals/#hsts` ("Delete domain": localhost).

One-time setup for the lint git hook:

```bash
uv tool install pre-commit
pre-commit install
```

## Frontend UI

The UI is built on [shadcn/ui](https://ui.shadcn.com) (the `radix-nova` style,
Radix UI under the hood). Components you own and can edit live in
`frontend/src/components/ui/`; the config is `frontend/components.json`. Import
them through the `@/` alias (e.g. `@/components/ui/button`) and combine classes
with the `cn()` helper in `frontend/src/lib/utils.ts`.

Add more components with the CLI (run from `frontend/`):

```bash
# NOTE: this prompts to overwrite the brand-customised button.tsx — decline it,
# which the piped "n" does. If it changed package.json, also install in the
# container (a named volume shadows the container's node_modules).
printf 'n\n' | npx shadcn@latest add <component>
docker compose exec frontend npm install
```

- **Design tokens & theming** live only in `frontend/src/index.css`. The four
  Catppuccin flavours are `[data-theme]` blocks (Latte = light; Frappé /
  Macchiato / Mocha = dark) and the accent colour is re-pointed by
  `:root[data-accent]` rules; `frontend/src/theme/themes.ts` holds the metadata.
- **Theme**: `useTheme()` from `frontend/src/theme/` exposes `theme` (flavour) +
  `accent`. Both are a per-user preference chosen on the profile page, persisted
  server-side (`users.theme` / `users.accent_color`) and mirrored to
  `localStorage` (with a pre-paint script in `index.html` to avoid a flash). It
  follows the OS preference until the user picks a flavour; the calendar starts
  weeks on Monday.
- **Language**: the UI ships in English (the default) and Italian, chosen on the
  profile page. Like the theme it is a per-user preference, saved server-side
  (`users.language`) and mirrored to `localStorage` (`isachore-language`), so it
  survives reloads and is re-applied on login on any device. Strings live in
  `frontend/src/i18n/locales/{en,it}.json`, keyed Laravel-style (nested dot keys
  such as `chores.title`); components read them with `useTranslation()` /
  `t('chores.title')`. Dates follow the active locale (en → en-GB, it → it-IT).
  Built on `react-i18next` + `i18next`. See the i18n conventions in `CLAUDE.md`
  before adding new strings.
- **Toasts**: `import { toast } from 'sonner'` and call `toast.success(...)`
  for success feedback; the single `<Toaster />` is mounted in `main.tsx`.

Libraries the migration added: `radix-ui`, `class-variance-authority`, `clsx`,
`tailwind-merge`, `lucide-react` (icons), `tw-animate-css`, `shadcn` (provides
`shadcn/tailwind.css`), `react-day-picker` + `date-fns` (date picker) and
`sonner` (toasts).

## Tests

Backend uses pytest, frontend uses vitest; both can report coverage. Run the
backend suite inside the container so the `db` host resolves.

```bash
docker compose exec backend uv run pytest                          # backend
cd frontend && npm run test                                        # frontend

# with coverage:
docker compose exec backend uv run pytest --cov=app --cov-report=term-missing --cov-report=html
cd frontend && npm run test:coverage
```

Coverage prints a per-file table in the terminal and writes a browsable HTML
report — open `backend/htmlcov/index.html` or `frontend/coverage/index.html`.
Every feature should ship with tests; both suites must pass before committing.

## TODO

The idea, step by step. Done so far: project scaffold, linters + pre-commit
hook, Docker dev/prod, hello world at `/`, login page UI at `/login`, chores +
users management UI, a shadcn/ui component kit with light/dark theming, a
self-service profile page (name / password / avatar upload) reached from an
avatar menu in the top bar, English/Italian UI translations (react-i18next)
picked per user on the profile page, email-based user confirmation with a
server-settings page (SMTP, mailpit in dev) plus the one-time `init` bootstrap,
a Home due view (overdue / due today / due within a week) with one-tap chore
completion and a daily progress bar, and optional TOTP two-factor authentication
(authenticator app plus one-time recovery codes, managed from the profile's
Security section and enforced as a second login step; the TOTP seed is encrypted
at rest with `APP_KEY`, and admins can reset a locked-out user's enrolment).

The app is organised into four areas (context for future work):

- **Homepage**: the due view (what is overdue, due today, due soon), filterable by
  household and by assignees. It defaults to your own chores plus shared ones, and
  widening the assignee filter shows the whole household's.
- **Admin**: manage server settings, users, and anything else that comes up.
- **Chores management**: manage the household's chores.
- **Tags management**: create, edit and delete tags.

- [ ] if one person mark a task as done, the other person see it live (websocket)
- [ ] CI (lint + test on push)
- [ ] chores changes log (see who changed the chores)

Design mockups live in `../isachore-design/` (login = variant 1a).
