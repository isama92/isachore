# isachore

Chore management for households. Track who does what, see what is overdue, due
today, or coming up, shared between the people in a household, with a JSON API so
mobile clients can join later.

Features: multi-user households with invitations and ownership transfer, chores
with four assignment strategies (manual, alphabetical, least-done, random) and
turn-taking rotation, a Home due view with one-tap completion and daily progress,
completion history, per-household tags, a Statistics page, admin user and
household management with impersonation, English/Italian UI, per-user theming,
optional TOTP two-factor authentication, and optional email-based account
confirmation.

## Stack

| Layer    | Tech                                                                        |
| -------- | --------------------------------------------------------------------------- |
| Backend  | FastAPI, async SQLAlchemy 2, asyncpg, Alembic, Python 3.13 (managed with uv) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, react-router 8, shadcn/ui (Radix) |
| Database | PostgreSQL 18                                                               |
| Cache    | Redis (login rate limiting)                                                 |
| Infra    | Docker for both dev and prod (multi-stage Dockerfiles, compose files)       |

There is **no self-registration**. The first admin is created with the `init`
command (see below); every other user is created by an admin in the UI under
**Admin > Users**.

## Development

### Prerequisites

- Docker and the Docker Compose plugin.
- Optional, for the lint git hook: `uv tool install pre-commit && pre-commit install`.

### First run

```bash
cp .env.example .env                                   # dev placeholder values are fine
docker compose up --build                              # db + redis + backend (reload) + frontend (HMR) + mailpit
docker compose exec backend alembic upgrade head       # run migrations (inside the container so host "db" resolves)
docker compose exec backend python -m app.cli init \
    --email you@example.com --first-name You --last-name Example   # create the first admin (prompts for a password)
```

> **The `init` step is required on every fresh setup.** Without it there is no
> way to log in (no self-registration). It is a one-time bootstrap: it does
> nothing if an admin already exists, so it is safe to leave in a deploy script
> and harmless to run twice.

Then open http://localhost:5173 and log in.

### Services

| Service              | URL                                   |
| -------------------- | ------------------------------------- |
| Frontend (SPA)       | http://localhost:5173                 |
| Backend API          | http://localhost:8000/api/v1          |
| API docs (Swagger)   | http://localhost:8000/docs            |
| Health check         | http://localhost:8000/api/v1/health   |
| Postgres             | localhost:5432                        |
| Mailpit (dev email)  | http://localhost:8025                 |

Redis is not published to the host; it is reachable only as `redis:6379` on the
compose network.

### Seed data

To fill the app with a realistic dataset for manual testing (five users, a solo
household each plus one shared household, tags, and chores covering every option
with completion history), run the seeder. It refuses to run outside a dev
environment. `--fresh` wipes all app data first, so it also doubles as a reset.

```bash
docker compose exec backend python -m app.cli seed --fresh
```

Every seeded user's password is `password`; the admin is `admin@example.com`
(the others are `bram@`, `cara@`, `dan@`, `eve@example.com`). If the DB is empty,
this is the quickest way to get a working login; if you only need a bare admin,
use `init` instead.

### Account confirmation (optional)

If **Admin > Server settings > Require user confirmation** is on, a new user
starts as *waiting confirmation* and is emailed a link to set their own password;
the account becomes active only once they do. When it is off, the admin sets the
password in the create form and the user is active immediately. Confirmation
needs SMTP configured (see the env table below); in dev, compose already points
SMTP at mailpit and captured mail shows at http://localhost:8025.

## Production

Production runs the same two services (a FastAPI backend and an nginx image that
serves the built SPA and reverse-proxies `/api/` to the backend), plus Postgres
and Redis. Neither the database, Redis, nor the backend publishes a host port;
only the frontend (nginx) is exposed, and only when you add a mode overlay.

The base file `compose.prod.yml` publishes no host port on its own. Pick one of
three modes:

**1. Behind your own TLS-terminating reverse proxy (recommended).** nginx stays
on HTTP; your proxy handles TLS, the HTTP to HTTPS redirect, and HSTS.
`compose.prod.traefik.yml` is a Traefik template: edit the router rule,
entrypoints, cert resolver, and external network to match your install.

```bash
docker compose -f compose.prod.yml -f compose.prod.traefik.yml up -d --build
```

**2. nginx terminates TLS with your own certificate (no front proxy).** Put
`fullchain.pem` and `privkey.pem` in `./volumes/certs`, then:

```bash
docker compose -f compose.prod.yml -f compose.prod.tls.yml up -d --build
```

**3. Plain HTTP on :80, for a local smoke test only** (never internet-facing):

```bash
docker compose -f compose.prod.yml -f compose.prod.http.yml up -d --build
```

### Production checklist

Set these in `.env` before deploying:

- `POSTGRES_PASSWORD` to a strong secret (and matching `DATABASE_URL`).
- `APP_KEY` to a freshly generated Fernet key (see the env table). Required for
  two-factor auth; a 2FA-enrolled user cannot log in without it.
- `APP_BASE_URL` to your real public HTTPS origin (used to build email links).
- SMTP values if you want account confirmation or the test-email button.

The prod stack forces `ENVIRONMENT=prod`, `COOKIES_SECURE=true`, and
`TRUST_FORWARDED_FOR=true` regardless of `.env`, so cookies are HTTPS-only and
per-IP rate limiting reads the real client IP behind the proxy. Every mode must
terminate TLS in front of the app; never set `COOKIES_SECURE=false` in prod.

Then, inside the running stack, run migrations and create the first admin (same
commands as dev, they are required here too):

```bash
docker compose -f compose.prod.yml exec backend alembic upgrade head
docker compose -f compose.prod.yml exec backend python -m app.cli init \
    --email admin@yourdomain --first-name Admin --last-name User
```

nginx sends security response headers on every response (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, plus HSTS in the TLS-terminating modes)
and caps request bodies at 6 MB. Uploaded avatars live in a named `storage`
volume and the database in `./volumes/db`, so both survive restarts.

<details>
<summary>Self-signed certificate for testing the TLS mode</summary>

```bash
mkdir -p volumes/certs && openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout volumes/certs/privkey.pem -out volumes/certs/fullchain.pem \
  -days 365 -subj "/CN=localhost"
```

Testing the TLS mode on `localhost` makes your browser pin HSTS for `localhost`
for two years, which can force other local HTTP projects to HTTPS and break them.
Prefer a throwaway hostname, or clear it afterwards at
`chrome://net-internals/#hsts` ("Delete domain": localhost).
</details>

## Environment variables

Configured via `.env` (see `.env.example`). All are read by
`backend/app/core/config.py`.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | dev placeholders | Postgres container credentials. Use a strong password in prod. |
| `DATABASE_URL` | `postgresql+asyncpg://...@db:5432/isachore` | Async DB URL. Must use the `postgresql+asyncpg://` scheme. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for login rate limiting (compose sets the container host). |
| `ENVIRONMENT` | `dev` | Deployment marker (informational). Gates the dev-only `seed` command; forced to `prod` by the prod stack. |
| `COOKIES_SECURE` | `true` | Secure flag on auth cookies. Must be `false` in dev (plain HTTP); forced `true` in prod. |
| `APP_KEY` | unset | Fernet key encrypting secrets at rest (the 2FA seed). Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Optional at boot, but 2FA fails closed without it. Rotating it strands existing 2FA enrolments. |
| `TRUST_FORWARDED_FOR` | `false` | Trust proxy IP headers. Off for direct/dev access; forced `true` in prod (behind nginx). |
| `APP_BASE_URL` | `http://localhost:5173` | Public SPA origin used to build emailed confirmation/invite links. Set to the real HTTPS origin in prod. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins per email before a 429 lockout within the window. |
| `LOGIN_IP_MAX_ATTEMPTS` | `20` | Failed logins per client IP before lockout (looser, for shared NATs). |
| `LOGIN_ATTEMPT_WINDOW` | `900` | Lockout window in seconds (shared by the 2FA throttle). |
| `TWO_FACTOR_MAX_ATTEMPTS` | `5` | Failed 2FA codes per user before a 429 within the window. |
| `TOTP_ISSUER` | `isachore` | Label shown beside the account in authenticator apps (cosmetic). |
| `TEST_EMAIL_COOLDOWN` | `10` | Seconds between admin test-email sends, per admin. |
| `STORAGE_DIR` | `storage` | Where uploaded avatars are written (relative to the backend workdir). |
| `AVATAR_MAX_BYTES` | `5242880` | Max raw upload size (~5 MB). |
| `AVATAR_MAX_PIXELS` | `50000000` | Max decoded pixel count (guards decompression bombs). |
| `AVATAR_PX` | `512` | Side length of the stored square avatar. |
| `MAX_REQUEST_BYTES` | `6291456` | App-level cap on any request body (~6 MB, 413 past it). Defence in depth behind nginx's `client_max_body_size`; keep the two in sync. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | unset / `587` | SMTP for confirmation and test emails. Confirmation and the test button need at least a host and from address. |
| `SMTP_STARTTLS` / `SMTP_USE_TLS` | `true` / `false` | STARTTLS (port 587) vs implicit TLS (port 465); mutually exclusive. |

## Commands

Run backend commands inside the container so the `db` host resolves. In prod,
prefix with `-f compose.prod.yml`.

### Setup and operations

```bash
# Create the first admin (REQUIRED at setup; no-op if an admin exists)
docker compose exec backend python -m app.cli init \
    --email you@example.com --first-name You --last-name Example

# Database migrations
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "describe change"

# Seed / reset the dev dataset (dev environments only)
docker compose exec backend python -m app.cli seed --fresh

# Clear login rate-limit lockouts (see below)
docker compose exec backend python -m app.cli clear-login-throttle        # all lockouts
docker compose exec backend python -m app.cli clear-login-throttle 42     # one user, by id

# Expire stale household invitations now (the hourly job, run once)
docker compose exec backend python -m app.cli expire-invitations
```

**Clearing a lockout:** repeated failed logins lock out both the attempted email
and the client IP for the window. `clear-login-throttle` with a user id clears
only that user's per-email counter (a user maps to an email, never to an IP);
with no argument it clears every counter, per-email and per-IP.

### Linting and formatting

```bash
cd backend && uv run ruff check . && uv run ruff format .
cd frontend && npm run lint && npm run format && npm run build   # build also typechecks (tsc -b)
pre-commit run --all-files                                       # what the git hook runs
```

### Tests

Backend uses pytest, frontend uses vitest; both must pass before you commit.

```bash
docker compose exec backend uv run pytest                        # backend (run in the container)
cd frontend && npm run test                                      # frontend

# with coverage (HTML report at backend/htmlcov/ and frontend/coverage/):
docker compose exec backend uv run pytest --cov=app --cov-report=term-missing --cov-report=html
cd frontend && npm run test:coverage
```

## Contributing

Conventions, architecture notes, and gotchas for working in this codebase live in
[CLAUDE.md](CLAUDE.md). UI mockups are in `../isachore-design/`.

### Roadmap

- [ ] Live updates when a housemate completes a chore (websocket)
- [ ] CI (lint + test on push)
- [ ] Chore change log (who changed what)
