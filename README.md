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
cp .env.example.dev .env                               # dev template, ready to run as-is
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

Every dev port is published on the loopback interfaces only (`127.0.0.1` and
`[::1]`), so the stack is not reachable from your network: it runs with the
documented placeholder credentials from `.env.example.dev`. Redis is not published
at all; it is reachable only as `redis:6379` on the compose network.

> `.env.example.dev` is the dev template and `.env.example` is the production
> reference. They differ where it matters: dev marks `ENVIRONMENT=dev` and turns
> the `Secure` cookie flag off for plain HTTP, which is exactly the configuration
> the backend refuses to boot with anywhere else (see below).

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
only the frontend (nginx) is exposed, and only in the mode file you run.

Each mode is a single self-contained compose file: copy the one you need and run
it on its own (there is no base file to combine). Pick one of three modes:

**1. Behind your own TLS-terminating reverse proxy (recommended).** nginx stays
on HTTP; your proxy handles TLS, the HTTP to HTTPS redirect, and HSTS.
`compose.prod.traefik.yml` is a Traefik template: edit the router rule,
entrypoints, cert resolver, and external network to match your install.

```bash
docker compose -f compose.prod.traefik.yml up -d --build
```

**2. nginx terminates TLS with your own certificate (no front proxy).** Put
`fullchain.pem` and `privkey.pem` in `./volumes/certs`, then:

```bash
docker compose -f compose.prod.tls.yml up -d --build
```

**3. Plain HTTP on :80, for a local smoke test only** (never internet-facing):

```bash
docker compose -f compose.prod.http.yml up -d --build
```

### Production checklist

Start from `cp .env.example .env` (the production reference, not
`.env.example.dev`) and set:

- `POSTGRES_PASSWORD` to a strong secret, and the same password in
  `DATABASE_URL`. These are two independent paths to one credential: compose
  interpolates the former into the `db` service, and the backend authenticates
  with the latter.
- `APP_KEY` to a freshly generated key:
  `docker compose -f compose.prod.tls.yml run --rm backend python -m app.cli generate-key`.
  Pass the compose file you are deploying, or you will build and start the dev
  stack instead. Required for two-factor auth; a 2FA-enrolled user cannot log in
  without it.
- `APP_BASE_URL` to your real public HTTPS origin (used to build email links).
- SMTP values if you want account confirmation or the test-email button.

The prod stack forces `ENVIRONMENT=prod`, `COOKIES_SECURE=true`, and
`TRUST_FORWARDED_FOR=true` regardless of `.env`, so cookies are HTTPS-only and
per-IP rate limiting reads the real client IP behind the proxy. Every mode must
terminate TLS in front of the app; never set `COOKIES_SECURE=false` in prod.

**The backend refuses to start** outside a dev environment if any of these is
wrong, rather than booting into a deployment that fails quietly later: a missing
or malformed `APP_KEY` (which would otherwise turn away every 2FA-enrolled user
with an opaque 503 at login), `COOKIES_SECURE=false`, or a `DATABASE_URL` whose
password is empty or one of the publicly known placeholders. Each problem is
logged individually, and all of them are reported on the first attempt, so
`docker compose logs backend` tells you everything to fix in one pass.

Only the web process is gated, which is what makes it recoverable: management
commands do not run the app's startup path, so they still work against a backend
that is refusing to serve. Use `run --rm` rather than `exec`, since there is no
healthy container to exec into:

```bash
docker compose -f compose.prod.tls.yml run --rm backend python -m app.cli generate-key
docker compose -f compose.prod.tls.yml run --rm backend alembic upgrade head
```

Then, inside the running stack, run migrations and create the first admin (same
commands as dev, they are required here too). Use the same compose file you
deployed with (the examples use the TLS mode):

```bash
docker compose -f compose.prod.tls.yml exec backend alembic upgrade head
docker compose -f compose.prod.tls.yml exec backend python -m app.cli init \
    --email admin@yourdomain --first-name Admin --last-name User
```

nginx sends security response headers on every response (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, plus HSTS in the
TLS-terminating modes), hides its version, and caps request bodies at 6 MB.
Uploaded avatars live in a named `storage` volume and the database in
`./volumes/db`, so both survive restarts.

In the TLS mode nginx serves TLS 1.2 and 1.3 with an ECDHE-only, AEAD-only
cipher list (Mozilla's intermediate profile), so no `dhparam` file is needed, and
session tickets are off. The key-exchange group list is deliberately left at
OpenSSL's default, which leads with the post-quantum hybrid `X25519MLKEM768`:
pinning `ssl_ecdh_curve` would replace that list and quietly drop back to
classical-only key exchange. OCSP stapling is deliberately not enabled either:
Let's Encrypt stopped serving OCSP in 2025 and no longer puts an OCSP URI in its
certificates, which makes stapling a no-op; `nginx.tls.conf` documents what to add
if your CA still publishes it.

### Container hardening

Every prod service runs with `no-new-privileges` and all Linux capabilities
dropped, keeping back only what each image demonstrably needs (nginx: binding
:80/:443 and chowning the temp dirs it hands to its worker user; Postgres:
chowning its data dir before dropping privileges; Redis: only the privilege drop;
the backend: nothing at all). The backend and nginx also run on a read-only root
filesystem, with tmpfs mounts for the paths they genuinely write: `/tmp` for the
backend (multipart uploads spool there) and nginx's temp dirs and pid file. A
consequence worth knowing: inside a running backend or frontend container you can
only write to `/tmp` and, in the backend, `/app/storage`.

Both web-tier services have healthchecks, and on `docker compose up` `frontend`
waits for `backend` to be *healthy* rather than merely started, so nginx does not
answer 502s while the backend is still booting. Two limits worth knowing: plain
Compose does not restart an unhealthy container (only Swarm acts on health), and a
host reboot brings containers back through the restart policy, which ignores
`depends_on` ordering. So the healthchecks give you an accurate
`docker compose ps` plus that one readiness gate, not self-healing. `/healthz` on
the frontend is the probe target, a static `ok` that needs neither the backend nor
a redirect.

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

Configured via `.env`: copy `.env.example.dev` for development or `.env.example`
for production. All are read by `backend/app/core/config.py`, and the ones marked
**boot-checked** are validated on startup outside a dev environment
(`backend/app/core/startup.py`).

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | dev placeholders | Postgres container credentials. Use a strong password in prod, and keep it identical in `DATABASE_URL`. |
| `DATABASE_URL` | `postgresql+asyncpg://...@db:5432/isachore` | Async DB URL. Must use the `postgresql+asyncpg://` scheme. **Boot-checked**: refuses to start when its password is empty or a publicly known placeholder. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for login rate limiting (compose sets the container host). |
| `ENVIRONMENT` | `prod` | Deployment marker. Gates two things: the dev-only `seed` command runs only on a dev-like value (`dev`/`development`/`local`/`test`/`testing`), and the startup config check runs only when it is *not* one of those. Defaults to `prod` and anything unrecognised reads as a real deployment, so both fail safe. The prod stack forces `prod`. |
| `COOKIES_SECURE` | `true` | Secure flag on auth cookies. Must be `false` in dev (plain HTTP); forced `true` in prod. **Boot-checked**: refuses to start when false. |
| `APP_KEY` | unset | Fernet key encrypting secrets at rest (the 2FA seed). Generate with `python -m app.cli generate-key`. Optional in dev, where 2FA fails closed without it; **boot-checked** elsewhere, where a missing or malformed key refuses to start. Rotating it strands existing 2FA enrolments. |
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
prefix with the compose file you deployed (e.g. `-f compose.prod.tls.yml`).

### Setup and operations

```bash
# Create the first admin (REQUIRED at setup; no-op if an admin exists)
docker compose exec backend python -m app.cli init \
    --email you@example.com --first-name You --last-name Example

# Print a fresh Fernet key for APP_KEY (required outside a dev environment)
docker compose exec backend python -m app.cli generate-key

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

- [ ] check ../REPORT.md
- [ ] have compose prod files pull images instead of building them
- [ ] is it possible to have a docker folder with Dockerfile inside?
- [ ] Live updates when a housemate completes a chore (websocket)
- [ ] CI (lint + test on push)
- [ ] Chore change log (who changed what)
