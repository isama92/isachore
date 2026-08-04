# isachore

Chore management for households. Track who does what, see what is overdue, due
today, or coming up, shared between the people in a household, with a JSON API so
mobile clients can join later.

Features: multi-user households with invitations, ownership transfer and per-member
roles, chores with four assignment strategies (manual, alphabetical, least-done,
random) and turn-taking rotation, a My Chores due view with one-tap completion and daily
progress, a separate Unscheduled Chores view for the ones you do whenever you feel
like it (never due, repeatable on demand, showing how long since each was last
done), completion history, per-household tags, a Statistics page, admin user and
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
| Infra    | Docker for both dev and prod. Everything Docker-related lives in `docker/` (multi-stage Dockerfiles, nginx config, the prod compose modes); the dev `compose.yml` stays at the root. Prod pulls prebuilt images from GHCR. |

There is **no self-registration**. The first admin is created with the `init`
command (see below); every other user is created by an admin in the UI under
**Admin > Users**.

A new account starts with no household. Creating one is the user's own first step,
under **Households**, or they accept an invitation to somebody else's.

### Household roles

Every membership carries a role, so a shared household can hand out chores without
handing over the household. Roles are set from **Households > edit**, which the owner and its
organisers reach with the pencil icon while everybody else gets a read-only eye; picking a new
role asks for confirmation before it takes effect. A page somebody's role does not cover is not
shown to them in the sidebar at all.

|                                                     | owner | organiser | deputy | helper |
| --------------------------------------------------- | :---: | :-------: | :----: | :----: |
| Mark chores done, scheduled or unscheduled          |   ✓   |     ✓     |   ✓    |   ✓    |
| My Chores, Unscheduled Chores, the household list   |   ✓   |     ✓     |   ✓    |   ✓    |
| History of your own completions and skips           |   ✓   |     ✓     |   ✓    |   ✓    |
| Undo your own completion or skip                    |   ✓   |     ✓     |   ✓    |   ✓    |
| History of the whole household, and Statistics      |   ✓   |     ✓     |   ✓    |        |
| Undo somebody else's completion or skip             |   ✓   |     ✓     |        |        |
| Create, edit and delete chores, manage tags         |   ✓   |     ✓     |        |        |
| Invite people, set deputy and helper roles          |   ✓   |     ✓     |        |        |
| Grant or change the organiser role                  |   ✓   |           |        |        |
| Rename or delete the household, remove members      |   ✓   |           |        |        |
| Transfer the household to somebody else             |   ✓   |           |        |        |
| Read the household's activity log (**Logs**)        |   ✓   |           |        |        |

The owner is one per household and is not a fourth role: they are an organiser, and the extra
rights come from owning the household. Their row shows as **Admin** in the members table, which
is the only place that word means the owner rather than the site-wide admin flag. A site admin
can set any role from **Admin > Households** too, with the same reach as the owner; the one row
nobody can change is the owner's own, which moves by transferring the household.

Creating a household makes you its owner. Accepting an invitation makes you a **helper**, and
an organiser promotes from there. The owner's own role cannot be changed by anybody, including
themselves; transferring the household, which promotes the new owner, is how that moves.

The one asymmetry between an owner and an organiser worth knowing: an organiser may move people
between deputy and helper, but may not hand out `organiser` or change anybody who already holds
it. So they can share the day-to-day load without being able to grow the set of people who
could demote them.

Invitations belong to the household rather than to whoever made them: every organiser sees the
same list, can revoke or delete any of it, and the cap of five outstanding invites is shared
between them.

Roles are per household, and the views that span several of them narrow rather than
refuse: an organiser of one household who is a helper in another sees the second one's
chores on My Chores and can tick them off, and finds those closures of their own on History,
while the rest of that household's history, its statistics and its chores management stay out
of reach.

**Logs** is the household's activity log, and the one page the owner alone reaches: an organiser
manages the chores, and this is the record of that management, so it answers to whoever the
household belongs to. It lists who created, edited or deleted a chore and who undid somebody's
completion or skip, newest first, filterable by action, person and household. An edit records
*which* fields moved rather than their values, which keeps the log a record of activity rather
than a second copy of every chore. Entries are kept for **90 days** and then deleted; the window
is enforced by the read itself as well as by a nightly sweep, so nothing older shows even if the
sweep has not run. Doing the chores is not logged, since History already lists every completion
and skip.

History is the one page that narrows within itself rather than being hidden. Everybody reaches
it: where your role is deputy or above you see the whole household's completions and skips,
and where you are a helper you see your own. With nothing but helper roles there is nothing
left to slice, so the filters are not shown at all. Undoing follows the same split, since an
undo of the most recent closure makes the chore due again and rolls a rotation back: your own
entries are always yours to undo, and an organiser can undo anybody's in their household,
which is what makes a housemate's mis-skip fixable. Somebody else's entry is marked in the
warning colour and names them in the confirmation, because it is somebody's record of work
done.

## Development

### Prerequisites

- Docker and the Docker Compose plugin.
- Optional, for the lint git hook: `uv tool install pre-commit && pre-commit install`.

### First run

```bash
cp .env.example.dev .env                               # dev template, ready to run as-is
docker compose up --build                              # db + redis + backend (reload) + frontend (HMR) + mailpit
docker compose exec backend python -m app.cli init \
    --email you@example.com --first-name You --last-name Example   # create the first admin (prompts for a password)
```

There is no migration step: the backend container runs `alembic upgrade head`
itself before starting the web server, on this first run and on every later one
that brings in new migrations. `docker compose logs backend` shows it.

> **The `init` step is required on every fresh setup.** Without it there is no
> way to log in (no self-registration). It is a one-time bootstrap: it does
> nothing if an *active* admin already exists, so it is safe to leave in a deploy
> script and harmless to run twice. When there is no active admin it doubles as
> the recovery tool, see [Lost admin access](#lost-admin-access).

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
(the others are `bram@`, `cara@`, `dan@`, `eve@example.com`). In the shared household
they cover every role, so you can log in as each and compare: Alex owns it (organiser),
Bram is a second organiser, Cara a deputy, Dan and Eve helpers. Each also owns a solo
household, which makes all five organisers *somewhere* and so gives them the full
sidebar; to see a pared-down one, invite a fresh user (invitees join as helpers). If the DB is empty,
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

**Nothing is built on the server.** The two app images are built by CI and
published to GHCR, so a deployment is a compose file, a `.env`, and a pull. You
do not need a repo checkout, a toolchain, or build capacity on the host:

| Image | Contains |
| ----- | -------- |
| `ghcr.io/isama92/isachore-backend:latest` | FastAPI app, its venv, Alembic migrations and the `app.cli` commands |
| `ghcr.io/isama92/isachore-frontend:latest` | nginx plus the built SPA and the baked nginx config |

Both packages are public, so pulling needs no `docker login`. They are
`linux/amd64` only: an arm64 host (Raspberry Pi, Graviton, Apple silicon) cannot
run them as published.

Each mode is a single self-contained compose file from `docker/`: copy the one
you need onto the host and run it on its own (there is no base file to combine).
Relative paths inside it, including `.env`, resolve next to the compose file, so
put each deployment in its own directory. Pick one of three modes:

**1. Behind your own TLS-terminating reverse proxy (recommended).** nginx stays
on HTTP; your proxy handles TLS, the HTTP to HTTPS redirect, and HSTS.
`docker/compose.prod.traefik.yml` is a Traefik template: edit the router rule,
entrypoints, cert resolver, and external network to match your install. Needs
`compose.prod.traefik.yml` and `.env` in the directory.

```bash
docker compose -f compose.prod.traefik.yml up -d
```

**2. nginx terminates TLS with your own certificate (no front proxy).** The only
mode needing more than the compose file and `.env`: put `fullchain.pem` and
`privkey.pem` in `./volumes/certs`, and place an `nginx.tls.conf` beside the
compose file. Extract that conf from the image you are about to run rather than
copying it out of the repo, so the two cannot drift apart:

```bash
docker run --rm ghcr.io/isama92/isachore-frontend:latest \
    cat /etc/nginx/modes/tls.conf > nginx.tls.conf
docker compose -f compose.prod.tls.yml up -d
```

**3. Plain HTTP on :80, for a local smoke test only** (never internet-facing).
Needs `compose.prod.http.yml` and `.env`:

```bash
docker compose -f compose.prod.http.yml up -d
```

### Install it on a phone

The app is a PWA, so it can be added to a phone's home screen and runs without
browser chrome. On Android, Chrome offers an install prompt; on iOS, use
**Share > Add to Home Screen** (Safari gives no prompt).

This needs **HTTPS with a certificate the phone trusts**, so it works in modes 1
and 2 above but not in the plain-HTTP mode, and not with a self-signed
certificate. Offline, the app opens and renders, but anything needing the API
shows its usual error state: nothing from `/api/` is ever cached, so no household
data is stored on the device.

A manifest cannot follow a per-user setting, so the Android splash screen is
always the light (Latte) background even for someone using a dark flavour. The
status bar corrects itself as soon as the app has loaded. Not a bug, just the
one thing that cannot be themed.

### Upgrading

`latest` moves on every merge to `main`, but nothing on the host follows it until
you ask. Pull and recreate:

```bash
docker compose -f compose.prod.tls.yml pull
docker compose -f compose.prod.tls.yml up -d
```

That is the whole upgrade: the recreated backend container runs
`alembic upgrade head` before starting the web server. A failed migration exits
non-zero, so the container crash-loops with the error in
`docker compose logs backend` rather than serving against a schema the code does
not match.

That crash-loop is deliberate, but it does mean there is nothing to `exec` into,
so repair it the same way as a rejected startup config: with `run --rm`, which
takes an explicit command and so does not migrate on the way in.

```bash
docker compose -f compose.prod.tls.yml run --rm backend alembic upgrade head   # see the error
docker compose -f compose.prod.tls.yml run --rm backend alembic downgrade -1   # or step back
```

Setting `RUN_MIGRATIONS=false` in `.env` is the other way out: it gets you a
bootable container to work from, at the cost of running on the old schema until
you migrate by hand.

> **One instance may migrate, and only one.** If you run more than one backend
> against the same database, set `RUN_MIGRATIONS=false` in every instance's
> `.env` except one. Two containers starting at the same moment both run
> `alembic upgrade head` and race on the `alembic_version` row; the loser fails
> and crash-loops. Nothing in the app serialises them, so keeping the migrating
> instance unique is the safeguard. Only a *starting* container migrates, so a
> rolling restart is not itself a race; its hazard is the older container serving
> against the schema the newer one just migrated.

#### API response changes

`/api/v1` is a JSON API meant for future mobile clients as well as the web app,
so a field disappearing from a response is a breaking change even though the
path did not move. Anything of that kind is listed here.

- **`GET /api/v1/chores` no longer returns `description` on a list row.** It sends
  `has_description: bool` instead; fetch `GET /api/v1/chores/{id}` for the markup.
  `POST /chores`, `GET /chores/{id}` and `PATCH /chores/{id}` are unchanged and
  still carry the full description.

One more consequence of migrating before serving: the backend now needs the
database at startup, where before it would come up and answer 503s until Postgres
appeared. Docker's restart policy does not honour `depends_on`, so after a host
reboot the backend may crash-loop for a few seconds until Postgres accepts
connections. It clears itself through restart backoff.

In the TLS mode, re-extract `nginx.tls.conf` after an upgrade if the config
changed.

And because `latest` is the only published tag, the build you replace becomes
reachable only by digest, so record it *before* pulling if you want a way back:

```bash
docker image inspect --format '{{index .RepoDigests 0}}' \
    ghcr.io/isama92/isachore-backend:latest
```

To roll back, put that `ghcr.io/...@sha256:...` reference in the mode file's
`image:` line and run `up -d` again. Note `docker compose images` is not a
substitute: it reports the local image ID, which pins nothing on another host.

### Production checklist

Start from `.env.example`, the production reference (not `.env.example.dev`). It
is the one file the images cannot hand you, so on a host with no checkout fetch it
into the deploy directory:

```bash
curl -fsSL -o .env \
    https://raw.githubusercontent.com/isama92/isachore/main/.env.example
```

Then set:

- `POSTGRES_PASSWORD` to a strong secret, and the same password in
  `DATABASE_URL`. These are two independent paths to one credential: compose
  interpolates the former into the `db` service, and the backend authenticates
  with the latter.
- `APP_KEY` to a freshly generated key:
  `docker compose -f compose.prod.tls.yml run --rm --no-deps backend python -m app.cli generate-key`.
  Required for two-factor auth; a 2FA-enrolled user cannot log in without it. Two
  flags earn their place here. Always pass the mode file, because compose only
  auto-discovers `compose.yml`, so a bare `docker compose` either finds nothing in
  a deploy directory or starts the dev stack in a checkout. And `--no-deps`,
  because `run` otherwise starts `db` first and Postgres initialises its data
  directory with whatever `POSTGRES_PASSWORD` is in `.env` *at that moment* —
  still the placeholder, if you are generating the key before setting the
  password. The real password would then never authenticate, and only wiping
  `./volumes/db` would clear it. `generate-key` needs no database at all.
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
docker compose -f compose.prod.tls.yml run --rm --no-deps backend python -m app.cli generate-key
docker compose -f compose.prod.tls.yml run --rm backend alembic upgrade head
```

(`--no-deps` on the first only: a key needs no database, whereas the migration
obviously does.) Neither triggers the automatic migration, which the entrypoint
runs only when the container is starting the web server. That is deliberate:
`generate-key` is reachable precisely because it needs no database, so an
unconditional upgrade would fail it on a connection error just when you need it.

Then create the first admin (the same command as dev, required here too). Use the
same compose file you deployed with (the examples use the TLS mode):

```bash
docker compose -f compose.prod.tls.yml exec backend python -m app.cli init \
    --email admin@yourdomain --first-name Admin --last-name User
```

nginx sends security response headers on every response (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, plus HSTS in the
TLS-terminating modes), hides its version, and caps request bodies at 6 MB.
Uploaded avatars live in a named `storage` volume and the database in
`./volumes/db`, so both survive restarts.

Avatars are served unauthenticated, which is a deliberate trade rather than an
oversight. Each file is a capability URL: the name is 128 random bits and holds
no user id, the directory has no listing, and the name is only ever returned by
authenticated endpoints, so the people able to obtain one are the user, admins,
and their household peers, all of whom see the picture in the app anyway. Uploads
are re-encoded to WebP with no metadata carried over, so a file discloses the
picture and nothing about where or when it was taken. The accepted downside:
anyone who gets hold of a URL can fetch that image until the avatar is deleted or
replaced, which are the only ways to invalidate it. Worth revisiting if uploads
ever carry anything more sensitive than a profile picture.

In the TLS mode nginx serves TLS 1.2 and 1.3 with an ECDHE-only, AEAD-only
cipher list (Mozilla's intermediate profile), so no `dhparam` file is needed, and
session tickets are off. The key-exchange group list is deliberately left at
OpenSSL's default, which leads with the post-quantum hybrid `X25519MLKEM768`:
pinning `ssl_ecdh_curve` would replace that list and quietly drop back to
classical-only key exchange. OCSP stapling is deliberately not enabled either:
Let's Encrypt stopped serving OCSP in 2025 and no longer puts an OCSP URI in its
certificates, which makes stapling a no-op; `docker/nginx/nginx.tls.conf`
documents what to add if your CA still publishes it.

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

Run this in the deploy directory, beside `compose.prod.tls.yml`:

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
for production. The ones marked **boot-checked** are validated on startup outside
a dev environment (`backend/app/core/startup.py`). All are read by
`backend/app/core/config.py`, with one exception: `RUN_MIGRATIONS` is read by the
container entrypoint, before Python starts.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | dev placeholders | Postgres container credentials. Use a strong password in prod, and keep it identical in `DATABASE_URL`. |
| `DATABASE_URL` | `postgresql+asyncpg://...@db:5432/isachore` | Async DB URL. Must use the `postgresql+asyncpg://` scheme. **Boot-checked**: refuses to start when its password is empty or a publicly known placeholder. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for login rate limiting (compose sets the container host). |
| `RUN_MIGRATIONS` | `true` | Read by the container entrypoint, not the app: runs `alembic upgrade head` before the web server starts. Only the exact lowercase `false` opts out, so a typo still migrates (the safe direction). Set it in every instance but one when several back ends share a database (see [Upgrading](#upgrading)). |
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
| `AVATAR_MAX_BYTES` | `5242880` | Max raw upload size (~5 MB). The Profile page mirrors the default to reject an oversized pick before uploading and to word its hint, so change `AVATAR_MAX_MB` in `frontend/src/pages/Profile.tsx` to match, or the UI keeps advertising 5 MB. |
| `AVATAR_MAX_PIXELS` | `50000000` | Max decoded pixel count (guards decompression bombs). |
| `AVATAR_PX` | `512` | Side length of the stored square avatar. |
| `MAX_REQUEST_BYTES` | `6291456` | App-level cap on any request body (~6 MB, 413 past it). Defence in depth behind nginx's `client_max_body_size`; keep the two in sync. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | unset / `587` | SMTP for confirmation and test emails. Confirmation and the test button need at least a host and from address. |
| `SMTP_STARTTLS` / `SMTP_USE_TLS` | `true` / `false` | STARTTLS (port 587) vs implicit TLS (port 465); mutually exclusive. |

## Commands

Run backend commands inside the container so the `db` host resolves. In prod,
prefix with the compose file you deployed (e.g. `-f compose.prod.tls.yml`) and run
it from the deploy directory, so the mode file finds the `.env` beside it and, in
the TLS mode, its `nginx.tls.conf` and certs.

Alembic and `app.cli` are baked into the published backend image, so the setup and
recovery commands work against a pulled image with no checkout. Two below are
dev-only and will not work against a prod stack: `alembic revision
--autogenerate` needs to write into `/app/alembic/versions`, which is on a
read-only rootfs, and `seed` refuses to run outside a dev environment.

### Setup and operations

```bash
# Create the first admin (REQUIRED at setup; no-op if an ACTIVE admin exists.
# With none it recovers instead, taking over this email if it exists or creating
# a new admin if it does not - see "Lost admin access" below)
docker compose exec backend python -m app.cli init \
    --email you@example.com --first-name You --last-name Example

# Print a fresh Fernet key for APP_KEY (required outside a dev environment)
docker compose exec backend python -m app.cli generate-key

# Database migrations. `upgrade head` runs itself when the backend container
# starts, so this is the escape hatch: after RUN_MIGRATIONS=false, or to apply a
# migration without recreating the container.
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "describe change"

# Seed / reset the dev dataset (dev environments only)
docker compose exec backend python -m app.cli seed --fresh

# Clear login rate-limit lockouts (see below)
docker compose exec backend python -m app.cli clear-login-throttle        # all lockouts
docker compose exec backend python -m app.cli clear-login-throttle 42     # one user, by id

# Expire stale household invitations now (the hourly job, run once)
docker compose exec backend python -m app.cli expire-invitations

# Delete household log entries past their 90-day retention window (the nightly job, run once)
docker compose exec backend python -m app.cli prune-logs
```

**Scheduled jobs.** The backend runs two of its own, in-process, started with the app: the
invitation sweep hourly, and the household-log retention prune nightly at 03:30 UTC. Neither
needs an external cron. The two commands above are the same jobs run once by hand, for a manual
sweep or for an external scheduler. Note both assume a single web process, which is what the
prod compose files run; behind several, gate them with a lock (Redis is already wired).

**Clearing a lockout:** repeated failed logins lock out both the attempted email
and the client IP for the window. `clear-login-throttle` with a user id clears
only that user's per-email counter (a user maps to an email, never to an IP);
with no argument it clears every counter, per-email and per-IP.

### Lost admin access

Only an `active` admin can administer anything, and the UI cannot leave you with
none: nobody may demote or deactivate themselves. It is still reachable, though,
by disabling admins from another admin account or by editing the database
directly, and a disabled admin cannot be re-enabled from the UI because logging
in as one is impossible.

`init` is the way back in. With no active admin it stops being a pure bootstrap
and repairs instead, so run it exactly as at setup:

```bash
docker compose exec backend python -m app.cli init \
    --email locked-out@example.com --first-name Admin --last-name User
```

- **Pass the locked-out account's own email** and that account is taken over:
  promoted to admin if it was not one, re-activated, marked confirmed, and given
  the password you type at the prompt. It also clears the account's two-factor
  enrolment (a restored password alone would still dead-end at the authenticator
  prompt) and revokes its sessions and any pending confirmation link, so nothing
  issued before the lockout can be replayed. It prints exactly which of those it
  changed. All of that is unconditional, so name an account you intend to take
  over; `--first-name` / `--last-name` are ignored here, the existing name is
  kept.
- **Pass an email nobody has** and a brand new admin is created instead, leaving
  the old accounts untouched.

Either way it refuses to change anything while an active admin still exists, so
it stays safe in a deploy script. If the backend is also refusing to boot, use
`run --rm` instead of `exec` (see the [production checklist](#production-checklist)).

**The one case it cannot fix** is an admin row that is still `active` but that
nobody can log in as: a forgotten password, or a lost authenticator with no
recovery codes left. `init` sees a healthy admin and declines, and `reset-2fa`
needs an admin to call it. Set that row's `status` to `disabled` in the database
first, then run `init` as above.

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

### Continuous integration

Two workflows in `.github/workflows/`:

- **`ci.yml`** runs on every pull request: ruff (`check` and `format --check`)
  plus pytest against a Postgres service container, eslint, prettier `--check`,
  `tsc -b` and vitest, and a build of both prod images **without pushing**. That
  last job is the only pre-merge check on the Dockerfiles, since the prod compose
  files are pull-only and have no build path. It is skipped on the main-branch run,
  where `publish.yml` builds the same targets for real.
- **`publish.yml`** runs on every push to `main`: it calls `ci.yml` first and
  pushes to GHCR only if everything passed, so a red commit can never become
  `:latest`. Images are `linux/amd64`.

Nothing is published from a pull request, however many times you push to it: the
PR build is validation only, and `:latest` moves exactly once per merge.

`ci.yml` has no `push` trigger of its own (that would run every `main` commit
twice, once directly and once via `publish.yml`), so pushing a branch with no open
PR runs nothing.

To reproduce the prod image builds locally, build them directly rather than
through compose:

```bash
docker build -f docker/backend.Dockerfile --target prod -t isachore-backend:test ./backend
docker build -f docker/frontend.Dockerfile --target prod \
    --build-context nginxconf=./docker/nginx -t isachore-frontend:test ./frontend
```

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers the process: branching, tests, and what
CI checks. Conventions, architecture notes, and gotchas for working in this
codebase live in [CLAUDE.md](CLAUDE.md).

Security issues go through [SECURITY.md](SECURITY.md), privately, not a public
issue. isachore is GPLv3, see [COPYING](COPYING).

### Todo

- [ ] Live updates when a housemate completes a chore (websocket)
