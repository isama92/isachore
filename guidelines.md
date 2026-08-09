# isachore guidelines

How code is written in this repository: the stack, the conventions, and the rules that apply
to any new work.

Read this before your first change. It is meant to be read start to finish once, then
consulted. For the *rationale* behind one particular subsystem — why timezones are anchored
the way they are, why the role ladder has three guards — see
[docs/architecture/](docs/architecture/); [CLAUDE.md](CLAUDE.md) routes between them.

Setup, env vars, operations and production live in [README.md](README.md). Process — branching,
pull requests, commit style — lives in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Tech stack

### Backend (`backend/`)

Python 3.13, managed with **uv**.

| Concern | Choice |
|---|---|
| Web framework | FastAPI |
| ORM | SQLAlchemy 2 (async) + asyncpg |
| Migrations | Alembic |
| Config | pydantic-settings |
| Validation | pydantic v2 (`pydantic[email]`) |
| Passwords | pwdlib with Argon2 |
| HTML sanitising | nh3 |
| 2FA | pyotp + qrcode |
| Scheduled jobs | APScheduler 3 (in-process) |
| Rate limiting | Redis (`redis[hiredis]`) |
| Email | aiosmtplib |
| Lint / format | ruff |
| Tests | pytest + pytest-asyncio, fakeredis |

Four dependency choices carry reasons that are easy to undo by accident, and each is recorded
as a comment in `backend/pyproject.toml`:

- **`joserfc`, not `authlib.jose`.** Same author's new and old JOSE APIs; the old one is
  scheduled to disappear in authlib 2.0, which would silently take OIDC ID token verification
  with it. authlib itself is still used, but only `integrations.httpx_client`.
- **`httpx` is a runtime dependency**, not a test-only one: `app/core/oidc.py` talks to the
  provider with it. Do not move it back to the dev group.
- **`tzdata` is insurance.** `zoneinfo` reads the system tz database first, but a base image
  that stopped shipping `/usr/share/zoneinfo` would turn every request into a 500 now that
  every household carries an IANA zone.
- **`pyyaml` is a declared dev dependency** for `tests/test_openapi_spec.py`, rather than
  borrowed from `uvicorn[standard]` where it merely happens to be today.

### Frontend (`frontend/`)

React 19 + TypeScript, Vite, npm.

| Concern | Choice |
|---|---|
| Routing | react-router 8 (import from `react-router`, never `react-router-dom`) |
| Styling | Tailwind CSS v4, CSS-first (no `tailwind.config.js`) |
| Components | shadcn/ui (radix-nova style) over `radix-ui`, owned in `src/components/ui/` |
| Tables | TanStack Table 8, fully manual mode |
| Charts | recharts |
| Rich text | Tiptap v3 |
| Dates | date-fns |
| i18n | i18next + react-i18next |
| Toasts | sonner |
| Icons | lucide-react |
| Lint / format | eslint 10 (`--max-warnings=0`) + prettier |
| Tests | vitest + Testing Library + jsdom |

**`shadcn` is a `devDependency`, and that is deliberate even though the app's CSS imports it.**
It is needed to *build*, never to run: nothing in `src/` imports its JavaScript, and the prod
image is `nginx:stable-alpine` serving static assets, so no `node_modules` ships at all.

Classifying it as a runtime dependency put **312 of 492** packages into the production graph
that only it reaches — `express`, `hono`, `@modelcontextprotocol/sdk`, `cors`, `jose`, `undici`,
`eventsource`, a whole MCP server stack behind a stylesheet — and every transitive CVE in that
tree then read as a production advisory. Moving it changed no build output whatsoever (the
emitted CSS is byte-identical, same content hash), because both `npm ci` sites install dev
dependencies.

The one thing that would break it: **adding `--omit=dev` or `--production`** to
`docker/frontend.Dockerfile`'s base stage as an image-size optimisation. If image size ever
matters there, split the install rather than pruning dev dependencies out of the stage that
compiles the SPA.

### Infrastructure

PostgreSQL 18. Redis backs login rate limiting (reachable only as `redis:6379` on the compose
network, never published to the host). Docker + Compose for dev and prod; see
[docs/architecture/deployment.md](docs/architecture/deployment.md).

**The Dockerfiles own the toolchain versions.** CI `sed`s python, uv and node versions out of
`docker/*.Dockerfile` rather than restating them, so a base-image bump reaches CI on its own.

---

## Repository layout

```
backend/app/
  api/v1/        routers, one module per resource; registered in router.py
  api/deps.py    CurrentUser, AdminUser, the security schemes
  api/responses.py  shared OpenAPI `responses=` blocks
  core/          business logic; pure where it can be
  db/            Base, session, redis, seed
  models/        SQLAlchemy models
  schemas/       pydantic request/response schemas
  cli.py         init, generate-key, seed, and the scheduled-job entry points
  main.py        app, middleware, lifespan

frontend/src/
  auth/          context / provider / hook, split across three files
  theme/         same split
  i18n/          languages, singleton, hook, locales/
  components/    shared components; ui/ is shadcn, the rest is ours
  components/data-table/  DataTable + useServerTable
  lib/           api wrapper, endpoints, formatters, permissions, types
  pages/         one component per route; admin/ for admin routes
  test/          renderWithProviders, fixtures, setup, the rich-text mock
```

---

## Architecture patterns

**The API lives under `/api/v1`, JSON only.** Routers in `backend/app/api/v1/`, registered in
`router.py`.

**A route gated on `AdminUser` answers under `/api/v1/admin`.** All 20 do, across
`admin_users.py`, `admin_settings.py` and `admin_households.py`, which is what lets the path be
read as a claim about *who* a route serves rather than only what it returns; the three
`include_router` calls are grouped at the bottom of `router.py` for the same reason.

A new admin surface goes under that prefix, in an `admin_*.py` module, with an `admin-*` tag.
Two near-misses stay outside it deliberately, and both look like oversights:
`POST /auth/stop-impersonating` (see
[auth.md](docs/architecture/auth.md#impersonation)) and `/logs`, which reads like an operator
surface but is `CurrentUser`-gated and scoped by household *ownership*.

On the frontend the same split is in `lib/endpoints.ts`: `adminUsers`, `adminSettings` and
`adminHouseholds`, with `auth.stopImpersonating` left where it is. Today's paths are pinned
twice over — exact-string assertions in `lib/endpoints.test.ts`, and the admin page tests, whose
`endsWith` / regex stubs carry the whole `/api/v1/admin/...` prefix and so stop matching if one
slips back (measured: 28 failures). Keep those stubs fully prefixed: shortened to
`endsWith('/users')` they would accept the old path and the new one alike, and that is the one
edit that would make the page tests stop guarding this.

**Keep business logic in `core/`, and keep it pure where it can be.** `core/chores.py` is pure
recurrence maths taking `now` as a parameter; `core/occurrences.py` is the DB-touching layer
over it. A module needed by two routers belongs in `core/`, not as private helpers in one of
them — `api/v1/chores.py` already imports from `api/v1/households.py`, so the reverse would be
an import cycle.

**Config goes through `app/core/config.py`** (pydantic-settings, env vars from `.env`). In
compose the DB host is `db`; the code default targets `localhost` for host-side tooling.
`DATABASE_URL` must use the `postgresql+asyncpg://` scheme.

**Startup invariants go in `check_startup_config()`, never as a `Settings` validator.**
`app/core/startup.py` refuses to boot outside a dev environment (`DEV_ENVIRONMENTS` in
`config.py`) on an unusable `APP_KEY`, `COOKIES_SECURE=false`, or a known-bad `DATABASE_URL`
password, enforced from the `lifespan` in `main.py`.

Not a validator, because the settings singleton is built at import time by every process, so a
validator would also break `pytest` and `python -m app.cli` — including the commands needed to
repair the deploy it rejected. Add new invariants to that function, which is pure and returns a
list of problems, rather than inline. Note dev is exempt from every startup check.

---

## Language standards

### Python

- **3.13.** `backend/.python-version` mirrors the Dockerfile and CI asserts they match.
- **ruff** for both lint and format, line length **100**. Selected rule sets: `E`, `W`
  (pycodestyle), `F` (pyflakes), `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM`
  (simplify), `C4` (comprehensions), `RUF`.
- Type-annotate signatures. Async everywhere on request paths — the ORM is async, so a sync
  call blocks the loop.
- Private helpers take a leading underscore (`_reconcile_open_occurrence`,
  `_get_organised_household`); that prefix is how the codebase signals "not part of this
  module's surface".

### TypeScript

- **Strict.** `npm run build` runs `tsc -b` before Vite, and it typechecks tests too via
  `tsconfig.vitest.json`, so a test type error breaks the build.
- **prettier**: single quotes, no semicolons, print width 100.
- **eslint with `--max-warnings=0`.** A warning is an error here; see
  [Code quality](#code-quality) for the two rules that shape file layout.
- Prefer a closed `const` tuple plus a derived union over a hand-written union, so the runtime
  list and the type cannot drift (`HOUSEHOLD_ROLES`, `LOG_ACTIONS`, `VALIDATION_TYPES`).

### Prose

Comments, docstrings, commit messages and documentation: **UK English**, no em dashes or en
dashes. Say what the code does and why a non-obvious choice was made; do not narrate what the
next line plainly says.

**When removing a feature, remove its comment too.** A comment describing something that is no
longer there is worse than none.

---

## Database conventions

**Models live in `app/models/` and inherit from `app.db.base.Base`** (naming convention for
Alembic autogenerate). Pydantic schemas live in `app/schemas/`.

**Re-export every new model from `app/models/__init__.py`.** That import is what registers it on
`Base.metadata`. Miss it and autogenerate silently produces an *empty* migration while every
test fails on a missing relation, since `conftest` builds the schema from that metadata.

**A new table also belongs in `db/seed.py`'s `_WIPE_ORDER`**, before whatever it references. A
CASCADE would usually cover it, which is exactly why forgetting fails quietly, and
`seed --fresh` promises to wipe app data rather than to lean on an `ondelete` a later change
could relax.

### Closed-set columns are `String` + a `StrEnum`

Not a native Postgres enum. The values come from a `StrEnum` on the backend, the column is a
plain `String`, and the closed set is enforced at the **schema layer**, where a bad value is a
422 rather than a 500.

Used by `users.status`, `household_members.role`, `household_log_entries.action`,
`users.theme` / `accent` / `language`, `households.timezone`.

The payoff: **adding a value needs no migration.** The cost, and it is asymmetric:

| Change | Cost |
|---|---|
| Add a value | Nothing. Add it to the enum (and to any hand-mirrored frontend tuple). |
| Remove a value | **A data migration before the deploy.** Rows holding it will be coerced back through `EnumType(value)`, which raises `ValueError` — a 500, not a degraded read. |

Contrast `audit_events.action`, which *is* a native Postgres enum: a new value there needs an
`ALTER TYPE`, which is why `cli.py` reuses `user_updated` rather than adding one.

### Enums stay on the backend; the wire carries strings

A read schema types a closed-set column as `str`, not as the enum and not as a `Literal` union.
Coercing on the way out would raise on a row a newer release wrote — an unfilterable 500 on
every page holding one. The closed set lives on the client as a hand-mirrored tuple, and the
client degrades an unknown value to a readable form.

The enum still guards a query *parameter*, where a 422 is the right answer.

Those frontend tuples (`HOUSEHOLD_ROLES`, `LOG_ACTIONS`, `LOG_FIELDS`, `users.language`) have
nothing checking them against the backend: keep them in step by hand.

### Migrations

Autogenerate inside the container, then fix the ownership:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe change"
docker compose exec backend chown -R $(id -u):$(id -g) alembic/versions
```

- **A model change ships with its revision in the same change.** CI's `alembic check` fails
  without it.
- **`pytest` never executes a migration.** The fixtures build the schema from
  `Base.metadata.create_all`, so a broken chain passes both suites. `ci.yml`'s "Migrations build
  an empty database" step is the only guard. After touching `alembic/`, run it by hand against a
  scratch database:

  ```bash
  docker compose exec db psql -U isachore -d postgres -c 'CREATE DATABASE scratch'
  docker compose exec -e DATABASE_URL=postgresql+asyncpg://isachore:<pw>@db:5432/scratch \
    backend alembic upgrade head
  ```
- **Do not seed rows a NOT NULL foreign key cannot satisfy.** `households.admin_id` is NOT NULL,
  so a household cannot exist before its owner; an owner-less row is what used to make
  `alembic upgrade head` unrunnable on an empty database.
- Prefer three cheap statements over one expensive one. `ADD COLUMN ... NOT NULL DEFAULT now()`
  forfeits Postgres's metadata-only fast path because `now()` is volatile, making it two full
  table rewrites; add nullable, backfill, then set NOT NULL.
- **Never `AT TIME ZONE <column>` at runtime.** Postgres carries its own tz database, so a name
  Python and Postgres do not share raises *inside the query*. Do the zone maths in Python.

---

## API conventions

### Gates

Four different facts, four different mechanisms. Do not collapse them:

| Gate | Asks | Refusal |
|---|---|---|
| `CurrentUser` | Is there a session? | 401 |
| `AdminUser` | Is this a site admin? | 403 (`FORBIDDEN_ADMIN`) |
| `require_role` | Do they reach this rung in this household? | 403 (`FORBIDDEN_ROLE`) — a promotion would fix it |
| `_get_owned_household` | Do they own this household? | 403 (`FORBIDDEN_OWNER`) — a promotion would NOT; only a transfer helps |

**Reads narrow, writes 403.** A list endpoint spanning several households takes
`member_household_ids(user_id, min_role)` and returns *less data* rather than refusing. A
mutation goes through `require_role` and 403s, because the caller can see the resource elsewhere
and a 404 would be a lie. Full worked reasoning in
[households.md](docs/architecture/households.md#reads-narrow-writes-403).

### Errors

- **A hand-raised `HTTPException` carries a string `detail`** and is shown to the user verbatim.
  Write it as a sentence someone can act on.
- **A 422 keeps pydantic's array shape.** `/api/v1` has future non-browser clients that need the
  machine-readable form; the frontend turns it into a sentence in `lib/validationError.ts`. Do
  NOT add a backend handler that flattens `detail` to a string.
- **A 422 does not echo the rejected value under `input`.** `strip_the_rejected_value` in
  `main.py` drops that key, because it carried the value that failed — so a password under
  `min_length=8` used to come back in the response body in plaintext on four routes. Three things
  must survive with it: the array shape, `ctx` (the frontend interpolates `min_length` and
  friends), and `jsonable_encoder` (a `value_error` carries an exception object in `ctx`, which
  is not JSON). `_openapi_without_the_rejected_value` drops `input` from the published
  `ValidationError` schema to match.

  Scoped deliberately: the absolute version of that sentence is false. A validator writing
  `f"{value!r} is not a known timezone"` puts the value in `msg`, and `schemas/household.py`
  does exactly that. The mechanism removes one key; keeping a value out of a message a validator
  composes is still the validator author's job.

### The published spec must describe what the route actually does

FastAPI infers less than it looks like it does, in two separate ways.

**A handler annotated with a `Response` subclass documents itself as an unconstrained 200 and
drops every other branch.** `-> JSONResponse` and `-> RedirectResponse` carry no schema, so the
generator infers a JSON 200 and the real answer goes unpublished: `/health` hid its 503, and
both `/auth/oidc/*` endpoints claimed a JSON body when they answer 302 with a `Location`
header. Such a route needs `response_model` / `responses=` / `status_code=` restating what it
does.

Those declarations are **inert at runtime** — FastAPI assigns a returned `Response` as-is — which
is what makes them safe to add to a working handler, and also why only a spec assertion can pin
them. Two traps: `response_class=RedirectResponse` makes the *inferred* code 307, so declaring a
302 by hand without `status_code=` publishes both; and the auto-generated 422 on any route with
parameters cannot be removed per-route.

**A gate contributes nothing either.** `securitySchemes` and per-operation `security` come only
from `SecurityBase` dependencies, and `Depends` carries no `responses` at all, so before
`app/api/responses.py` existed every gated route published itself as anonymous with no refusals.

- The schemes are three `Security(...)` declarations in `api/deps.py` (`sessionCookie`,
  `bearerToken`, `parkedAdminCookie`), all `auto_error=False` and all **ignored parameters**.
  They are documentation: the token read stays in `get_request_token`, because four routes call
  that helper outside the dependency system. Deleting them is silent at runtime and fails four
  tests.
- **`X-CSRF-Token` is deliberately not a scheme.** FastAPI emits one `security` entry per scheme
  and OpenAPI reads separate entries as *alternatives*, so it would publish "cookie OR csrf
  header" where `core/csrf.py` requires both. It lives in `main.py`'s `API_DESCRIPTION` instead.
- **401 goes on the `include_router` call, 403 mostly does not.** Every route in a gated router
  needs a session, so the 401 is uniform. The 403 is not: `households`, `chores`, `tags` and
  `completions` each mix `require_role` routes with routes open to any member, so a router-level
  `FORBIDDEN_ROLE` would put a 403 on `POST /households`, `GET /completions/filters` and
  `GET /chores/{id}` — 12 of those 28 operations. It is per route on the 16 that can raise it.
- A fourth 403 exists and is deliberately undocumented per route: `CsrfProtectMiddleware`, which
  is transport-level.

**Regenerate `docs/api/openapi.yaml` after any of this**, or `tests/test_openapi_spec.py` fails.
The command is pinned in README.md.

---

## Frontend patterns

- **One page component per route**, in `frontend/src/pages/` (`pages/admin/` for admin routes).
- **Import routing from `react-router`**, never `react-router-dom`.
- **Keep React context, provider component and hook in separate files** (see `src/auth/` and
  `src/theme/`). This is forced by react-refresh's `only-export-components` rule under
  `--max-warnings=0`, not a style preference.
- **API calls go through the `api` wrapper** in `src/lib/api.ts`, which throws `ApiError` and
  adds `X-CSRF-Token` automatically. Endpoint paths live in `lib/endpoints.ts`, never inline.
- **Every list view is `DataTable` + `useServerTable`.** A column's `id`/`accessorKey` IS the
  server sort key, so it must match that endpoint's whitelist (`CHORE_SORT_COLUMNS` and friends)
  or sorting breaks silently. Mechanics in
  [frontend.md](docs/architecture/frontend.md#server-driven-tables).
- **Design tokens live ONLY in `frontend/src/index.css`.** Never hardcode a hex value in a
  component. Set brand radius and height in the primitive's own class string, not via a call-site
  `className` — tailwind-merge does not dedupe the custom radius tokens against a base
  `rounded-*`.
- **Every user-facing string needs a key in BOTH `en.json` and `it.json`**, with identical nested
  trees. Render with `useTranslation()` / `t('group.key')`, never hardcode. Keys are typed off
  `en.json`, so a missing English key fails `tsc -b`; nothing checks that Italian matches, so
  keep it in lockstep by hand.
- **Feedback: success -> toast (`sonner`), errors -> inline text.** On a list page an inline
  error needs `role="alert"` plus `scrollIntoView`, or a row action failing on row 90 reports
  itself off-screen.
- **Table pages span the full width**; only form pages keep a `max-w` cap.
- **Charts use the theme `--primary`**, not a fixed hue, so a single-series mark tracks the
  user's accent.
- **Never read a filter's value as a proxy for how much is in scope.** A household `Select`
  renders only above one option, so for a single-household user its state can never leave `''`.
  Ask the data instead.

---

## Testing

Tests live in `backend/tests/` (pytest) and alongside the code as
`frontend/src/**/*.test.{ts,tsx}` (vitest). **Every feature ships with its tests in the same
change**, covering the negative paths (401/403/400/404/409), not just the happy one.

```bash
docker compose exec backend uv run pytest      # in the container, so `db` resolves
cd frontend && npm run test
```

Coverage: add `--cov=app --cov-report=term-missing --cov-report=html` (report at
`backend/htmlcov/`); `npm run test:coverage` (`frontend/coverage/`).

### The four disciplines

These are the rules that cost real work to learn. They are about whether a test pins anything at
all.

#### Satisfy every other clause

**A test for one clause of a compound condition must satisfy every other clause**, or it asserts
a fall-through and pins nothing.

This has cost real work four times:

- The `sw.js` guards — a request shape matching no branch falls through whether or not the guard
  exists.
- `useServerTable`'s early-return guards — no URL change means no refetch either way, so only
  asserting `loading` catches a missing guard.
- The chore form's assignee picker — a test that switched strategy with an *empty* assignee pool
  proved nothing about the strategy gate, since the empty pool hides the picker by itself.
- The rich text toolbar's `useEditorState` — Tiptap v3's React binding is non-reactive, so a
  stale read is invisible whenever the document changes, because `onUpdate` re-renders and
  recomputes it by accident. Only a pure selection move is document-free.

**When adding a test for a guard, delete the guard and watch the test fail.**

And when you do: **change exactly one clause.** Replacing
`if not state or not cookie or not compare_digest(state, cookie)` with `if not state` fails a
test, so the guard looks pinned — but that deleted three clauses and the failing test only needed
the first. Dropping the `compare_digest` alone left the whole suite green.

#### The sentence saying what a guard covers is the part most likely to be wrong

Nothing executes prose. Distinct from the rule above, which is about a test that pins too little:
this is a test, comment, docstring or README line that pins the right thing and then *claims more
than it does*. It costs a reviewer's time every release, and it is the one defect CI cannot
catch, because a comment compiles whatever it says.

Five instances in the OpenAPI/admin-prefix work alone: a README sentence naming a drift guard
that did not exist yet; a test docstring asserting `response_model` validation that a measurement
in the same session had already disproved; an `endpoints.ts` comment describing a 2FA reset the
UI does not have; a comment claiming several page tests were prefix-blind when their `endsWith`
needles carried the full path; and a `responses=` block introduced as "what both endpoints answer
with" while omitting the 429 both reach *before* the 404 it did document.

So when you write down what something guards, mutate it and read the sentence again against what
actually failed. Three habits that catch most of it:

1. **Name the mechanism rather than the intent** — "the `endsWith` needles carry the full
   prefix", not "the page tests catch it".
2. **Say what is *not* covered in the same breath**, since a set claimed complete is the shape
   that rots.
3. **Prefer a claim a later reader can check in one grep** over one that needs the whole call
   graph.

#### When the decision is NOT to do something, the mutation is an addition

The delete-the-guard rule is written entirely in terms of deleting, so it silently covers nothing
when the protected behaviour is an *omission*: no automatic household provisioning, no
`repeats != manual` predicate on `most_skipped`, no local 2FA challenge in the OIDC callback, no
page number in stored table settings, no in-app OIDC unlink. There is no guard to delete.

The test has to assert **the thing still does not happen after a plausible edit that would make
it happen**. Three techniques, strongest first:

1. **Make it unrepresentable.** `OidcIdentity` has no `claims` or `email_verified` field at all,
   so "read the provider's `email_verified`" is not a one-line edit somebody makes
   absent-mindedly — it needs a dataclass change that forces them past the reasoning. Prefer this
   when the shape allows it: no test to rot.
2. **Assert the absence at the surface that would do it, having first made the mechanism live.**
   `test_create_user_creates_no_household` (plus
   `..._waiting_confirmation_creates_no_household_either`, because the endpoint has two branches)
   gives the admin a household, counts, POSTs, and asserts the count did not move. Counting on an
   empty database would pass no matter what the endpoint did. Same shape:
   `test_callback_skips_two_factor` turns `totp_enabled` **on** before asserting no `isachore_2fa`
   cookie, and `useServerTable`'s "remembers a sort, page size and filter change, but never the
   page" stores three siblings first, so the absent fourth is the rule rather than a dead code
   path.
3. **Execute the artefact rather than grepping it.** `src/serviceWorker.test.ts` runs `sw.js` in a
   `node:vm` against a fake `self`, which is what lets it assert "never caches `/api/`" as
   behaviour.

**The trap that hides this: asserting the consequence through a fixture proves nothing about the
endpoint.** `test_history_is_empty_for_a_member_of_no_household` builds its user with `make_user`
and so would keep passing with provisioning reintroduced into `POST /admin/users`. When you audit
an omission, mutate it and check that a test naming *that surface* fails.

Where there is no behaviour to observe at all, pin the closed set directly — `test_csrf.py`
asserts `_AUTH_COOKIES`' contents, like `test_every_role_is_on_the_ladder`.

#### The spec is guarded by two test files, and they work differently

Between them they are why a gated route cannot publish itself as anonymous, and why a
declared refusal has to be one the handler can actually raise.

**`tests/test_openapi_security.py` compares two hand-maintained sets.** `security` and the
401 are asserted to be the same set, give or take a two-entry allow-list. One side is derived
and the other hand-written, so they drift in opposite directions: a new gated route in an
unblocked router declares no 401, and a block on a public router declares one nothing raises.
`PUBLIC_OPERATIONS_ANSWERING_401` holds the two anonymous routes that genuinely answer 401 by
themselves (login's bad credentials, verify-2fa's missing challenge); a 401 on any other
public operation still fails.

It also reads the *descriptions*, not only the codes:
`test_the_owner_gate_and_the_role_gate_say_different_things` exists because swapping
`FORBIDDEN_ROLE` for `FORBIDDEN_OWNER` changes no status code and no test that merely counts
them.

**`tests/test_openapi_refusals.py` reads the code instead.** The per-endpoint refusals — 87 of
them across 53 operations, far too many to hold in a hand-written set — are checked by walking
each handler's call graph and comparing the reachable status codes with the declared ones,
failing in *both* directions. Four things about that walker to know before touching it, each
of which it got wrong once:

1. **Its symbol table spans `core/`, `deps.py` and the other routers**, because routers import
   from each other (`admin_households.py` takes `load_household_read` and `set_member_role`
   from `households.py`). Leaving the routers out made it report a route as raising nothing at
   all.
2. **It resolves module-level `HTTPException` constants by name**, not just calls —
   `_invalid_token_exc`, `_credentials_exc`. Following calls alone missed their routes.
3. **Operations are keyed by router prefix plus path**, not by handler name: eight handler
   names collide between `households.py` and `admin_households.py`, and keying by name
   silently compared one route against the other's declarations.
4. **The 401 and the admin 403 arrive by *dependency***, so the walk cannot see them, and
   `_invisible_to_the_walk` excludes exactly those two. Every other gate refusal is walkable,
   which is what lets it catch a `FORBIDDEN_ROLE` on a route that never calls `require_role`.

Where the walker over-reports, `UNREACHABLE` records the case and the reason. **Never silence
one by declaring the refusal instead** — that trades a red test for a document that lies, which
is the defect the file exists to prevent.

`tests/test_validation_errors.py` pins the 422 property the same way round: it asserts the
secret appears **nowhere** in the body, not merely that the `input` key is gone.

#### Know what neither suite can reach

Some things are structurally untestable here, and the honest answer is a by-hand check rather
than a test that pretends. The standing list:

| Not covered | Why | Check by |
|---|---|---|
| The boot migration | It is shell | `docker compose down -v && up -d --build backend`, then grep the logs |
| Scheduler jobs firing | Neither suite starts the scheduler | Run the paired CLI command |
| Concurrency races (invitation cap, zone change vs completion, the `update_chore` 409) | The fixtures give each test one connection inside a rolled-back savepoint, so two concurrent transactions never exist | Parallel `curl`, or a throwaway `asyncio.gather` script |
| `_client()`'s PKCE call | Never executed by either suite | By hand against a real provider |
| `defer(..., raiseload=True)` on the chores list | The fixtures share one session, so an already-loaded chore keeps its description | Read the compiled SQL |
| `chore_occurrences.updated_at` moving | Both defaults are SQL `now()`, frozen for the whole savepoint | Complete a chore on the dev stack, compare columns |

### Backend fixtures

Build cases with `client` / `make_user` / `auth_client` / `make_household` from
`tests/conftest.py`. A throwaway `isachore_test` database is created and each test rolls back via
a SAVEPOINT.

- **`make_household` defaults every member to `organiser`.** Load-bearing: it keeps the chores /
  tags / stats / history suites testing their own subjects instead of several hundred assertions
  about 403s. Role tests pass `roles={user.id: ...}`.
- **Every household fixture defaults to `timezone="UTC"`**, which keeps several hundred
  pre-timezone due assertions meaning what they used to.
- Redis is faked with `fakeredis` (the `fake_redis` fixture overrides `get_redis`); tune the login
  throttle per-test by monkeypatching `settings.login_*`.
- **Pin the clock with `app.core.clock.now`, and patch the module attribute.** Endpoints call
  `clock.now()` rather than importing the name precisely so `monkeypatch.setattr(clock, "now",
  ...)` reaches them; `from app.core.clock import now` in a caller would defeat it. The pure
  helpers in `core/chores.py` take `now` as a parameter and need no seam. The same reasoning
  applies to `oidc_core.begin` / `complete`.
- Autouse resets (`_reset_oidc`, `_reset_smtp`, `_reset_app_key`) exist because pytest runs inside
  the dev container with `env_file: .env`, so a block uncommented to try something by hand would
  otherwise leak into every test.

### Frontend fixtures

Use `renderWithProviders` + the `fetch` mock from `src/test/utils.tsx` and the synthetic fixtures
in `src/test/fixtures.ts` — **never real personal data**.

Radix in jsdom needs `userEvent.setup({ pointerEventsCheck: 0 })` and portal-aware queries; the
stubs in `src/test/setup.ts` are required, not optional. Contenteditable cannot be driven at all,
which is why `src/test/richTextEditorMock.tsx` is the only `vi.mock` in the repo. Details in
[frontend.md](docs/architecture/frontend.md#testing-the-frontend).

### Beyond the suites

Exercise the running dev stack for what they don't cover: the API with `curl` against
`http://localhost:8000/api/v1/...` and a cookie jar (`-c/-b`; a cookie-authenticated mutation also
needs `-H 'X-CSRF-Token: 1'`), and the UI via `puppeteer-core` (npm-install it in a scratch dir
outside the repo) driving `/usr/bin/google-chrome` against `http://localhost:5173`.

### Test-infra quirks

Handled in the committed setup; don't undo them:

- Coverage needs `concurrency = ["greenlet"]` in `pyproject.toml`, or async SQLAlchemy endpoint
  bodies read as uncovered.
- pydantic `EmailStr` rejects `.test` TLDs, so use `@example.com` in fixtures.
- httpx won't send a cookie set with an explicit `domain="testserver"`, so set it without a
  domain.

---

## Code quality

**pre-commit is the gate**, and it fixes rather than reports, so problems never reach a diff:

```bash
pre-commit run --all-files
```

Keep the ruff version in `.pre-commit-config.yaml` (`ruff-pre-commit` rev) in sync with the ruff
dev dependency in `backend/pyproject.toml`.

### Dependency changes need two installs

The container's `node_modules` is shadowed by a named volume, and the backend venv is baked into
the image at `/opt/venv`:

```bash
# frontend, after frontend/package.json OR frontend/package-lock.json changed
cd frontend && npm ci          # `ci` installs the lockfile exactly; `install` may rewrite it
docker compose exec frontend npm install

# backend, after pyproject.toml deps changed
docker compose exec backend uv sync --no-install-project
docker compose up -d --build backend
```

**A lockfile-only change counts.** The shadowing is identical, so skipping the container half
leaves the dev stack running the old tree indefinitely with nothing on screen to say so.

### The eslint rules that shape file layout

- **`react-hooks/set-state-in-effect`** (v7): never call a state-setting function synchronously in
  a `useEffect` body. Do data loading with promise chains where setState happens only inside
  `.then/.catch/.finally` (see `AuthProvider.tsx` / `Users.tsx`).
- **`react-refresh/only-export-components`** with `--max-warnings=0`: keep React context, provider
  component and hook in separate files. shadcn `ui/**` files co-export a component plus its cva
  variants; an override for `src/components/ui/**` permits that, so leave their *export* shape
  alone. That is about what a file exports, not a ban on editing `ui/**`.

### Never accept a shadcn overwrite

Adding a component re-pulls its registry deps and offers to overwrite files it thinks it owns:

```bash
printf 'n\n' | npx shadcn@latest add <name>
```

`button.tsx` holds brand styling; `chart.tsx` holds the CSS sanitiser around its
`dangerouslySetInnerHTML` **and** the `hideZero` tooltip behaviour. Losing the second is a
security regression. Both fail CI, but with a message that reads nothing like "you accepted an
overwrite".

### Other standing gotchas

- Changing `POSTGRES_*` in `.env` after first boot needs `docker compose down -v`.
- Alembic files generated in the container are root-owned on the host; `chown` them.
- FastAPI registers included routers lazily; to introspect routes use `app.openapi()['paths']`,
  not `app.routes`.
- Keep the standard ports (5173/8000/5432 dev, 80 prod). If one is taken, another local project's
  stack probably holds it: never remap isachore's ports and never touch the other stack — ask.

---

## Security and compliance

- **No secrets, credentials or production hostnames anywhere in the repo.** `.env` is gitignored.
  Two templates are committed: `.env.example.dev` (dev, ready to run, documented dev credentials
  and nothing real) and `.env.example` (prod reference, placeholders only). `.gitignore`'s `.env.*`
  line means any further template needs its own `!` negation or it is silently never committed.
- **Auth cookies get `Secure` by default** (fail-closed). Local dev is plain HTTP, so
  `COOKIES_SECURE=false` in `.env.example.dev`; leave it unset in production, which must terminate
  TLS. `ENVIRONMENT` does not control cookie security.
- **Sanitise on write, server-side.** A browser-side allowlist proves nothing when `curl` skips
  it. `backend/app/core/richtext.py` is the single definition of the rich-text format and the
  security boundary.
- **Keep any payload a household peer can reach off `UserRead`.** `ChoreRead.assignees` used to be
  `UserRead` and handed a helper their housemates' email addresses; they are
  `HouseholdMemberRead` now, and `main.py`'s avatar accepted-risk note depends on that staying
  true.
- **No free-text column on a surface a housemate reads.** That is where personal data creeps in;
  the household log carries field *names*, never values, and no `detail` field.
- **No real personal data in fixtures or tests** — synthetic only.
- Retention promises that are product decisions live as module constants (`LOG_RETENTION`,
  `MAX_PENDING_INVITATIONS`), not as `Settings` fields, so a deployment cannot quietly widen them.
