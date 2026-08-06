# isachore

Chore management app for households: chores shared between multiple people,
overdue / due-today / due-soon views, JSON API for future mobile clients.

Human-facing setup, deploy, env vars and the full command list live in
[README.md](README.md). This file is the working guide: conventions, test setup,
and the non-obvious gotchas.

## Workflow

- Work in small steps; the todo list in README.md is the backlog (tick items off
  when done). When a requirement is ambiguous or a decision shapes UX or
  architecture, ask before building.
- **Never commit to `main`.** Branch at the *start* of a step, before the first
  edit, and always from an updated `main` rather than from whatever branch you are
  on: `git checkout main && git pull`, then `git checkout -b <name>`. Finish by
  pushing and opening a PR (`gh pr create`). Beyond review, the PR is what makes
  the checks a *gate*: `ci.yml` triggers on `pull_request`, so they run before the
  code lands. A direct push to `main` does still run them, via `publish.yml`
  calling `ci.yml`, but only after the fact on a commit that is already there, and
  a failure then merely skips publishing. The git history predates this rule and is
  mostly direct commits to `main`; do not read that as permission.
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
- **Scheduled jobs**: an in-process APScheduler (`app/core/scheduler.py`), started and stopped
  by the `lifespan` in `main.py`. Two jobs today: the hourly invitation-expiry sweep and the
  nightly household-log prune. Each pairs a `run_*` entry point with a CLI command so an
  operator can run it once by hand, and each assumes a single web process, which is what the
  prod compose files run - behind several, gate them with a Redis lock. Neither suite runs a
  job for real, so a new one needs a by-hand check plus a registration test asserting the
  trigger string (see `tests/test_invitation_expiry.py`).
- **Docker** (`docker/`): everything Docker-related except the dev compose file,
  which stays at the root as `compose.yml` because it is the everyday entry point.
  `docker/` holds `backend.Dockerfile` and `frontend.Dockerfile` (multi-stage),
  `nginx/` (the three nginx configs), and one self-contained
  `compose.prod.<mode>.yml` per prod deployment mode: http / tls / traefik.
- **CI** (`.github/workflows/`): `ci.yml` (ruff + pytest + eslint + prettier +
  `tsc -b` + vitest, plus a no-push build of both prod images that runs on pull
  requests ONLY, since on the merge path publish.yml's own build is the gate)
  runs on pull requests and is *called* by `publish.yml`, which on push to `main` pushes
  `ghcr.io/isama92/isachore-{backend,frontend}:latest`. `ci.yml` deliberately has
  no `push` trigger, or every `main` commit would run it twice. Both carry the same
  `paths-ignore` list (root prose + `docs/**`) so a documentation change runs
  nothing and does not churn `:latest`; keep the two lists identical, and do NOT
  add `**.md`, since prettier does check markdown under `frontend/`. One-time manual
  step, not scriptable: GHCR packages are created **private** on first publish and
  inherit nothing from repo visibility, so both must be flipped to public
  (Packages > package > settings) or every `docker compose pull` in README.md's
  Production section fails with `denied`.

## Commands

Full reference (setup, seeding, throttle clearing, prod modes, env vars) is in
README.md. The essentials, run inside the container so the `db` host resolves:

```bash
docker compose up --build                           # dev stack; the backend entrypoint runs `alembic upgrade head` on boot
docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head    # escape hatch: boot already did this
docker compose run --rm backend alembic upgrade head  # ...and this is the one that works when boot FAILED: no container to exec into
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
  Four coupled details:
  - **`backend/docker-entrypoint.sh` runs `alembic upgrade head` on boot**, so an
    upgrade is `pull` + `up -d`. It is baked in as `ENTRYPOINT` in the `dev` and
    `prod` stages, which is what keeps this out of the compose files entirely:
    operators already hold copies of the prod mode files, and those must stay
    `image:`-only. It installs to `/usr/local/bin`, not `/app`, because the dev
    stage ships no source (only the bind mount) and a mount there would shadow it.
    Two rules when touching it: it migrates **only when `$1` is `uvicorn`**, since
    `run --rm --no-deps backend python -m app.cli generate-key` is the documented
    way out of a deploy the startup check rejected and deliberately runs with no
    database, so an unconditional upgrade would break exactly that recovery path;
    and `set -e` must stay, so a failed migration crash-loops the container
    instead of serving against a schema the code does not match.
    `RUN_MIGRATIONS=false` opts out (shell-only, deliberately NOT a `Settings`
    field: no Python reads it, and pydantic's `extra="ignore"` makes a stray var
    in `.env` harmless). Concurrency is a documented operator constraint, not a
    lock: two instances booting against one database race on `alembic_version`.
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
  `Base.metadata`. Miss it and autogenerate silently produces an *empty* migration while every
  test fails on a missing relation, since `conftest` builds the schema from that metadata. A
  new table also belongs in `db/seed.py`'s `_WIPE_ORDER`, before whatever it references: a
  CASCADE would usually cover it, which is exactly why forgetting fails quietly, and
  `seed --fresh` promises to wipe app data rather than to lean on an `ondelete` a later change
  could relax. Pydantic schemas live in `app/schemas/`.
- **`core/occurrences.py` is the DB-touching layer over `core/chores.py`**, which stays pure:
  the latter knows where the recurrence grid falls, the former knows which slots a chore has
  actually used (`free_slot_from`, `initial_slot`, `rule_for`, `zone_for`,
  `reanchor_open_occurrences`). It exists as its own module rather than as private helpers in
  the chores router because two routers need it - the chores one and the household one, which
  re-anchors slots on a timezone change - and `api/v1/chores.py` already imports from
  `api/v1/households.py`, so the reverse would be an import cycle.
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
- **NOTHING provisions a household.** Not `POST /users`, not `cli init`, not
  confirming an account: a new user, the bootstrap admin included, starts a member
  of none and creates their own through `POST /households` (open to any
  authenticated user) or accepts an invitation. Do not reintroduce an automatic one
  anywhere, including in the confirmation flow; it was removed because it left
  every account owning a household it never asked for. `seed` is the exception,
  building its own solo plus shared households, and is now the only consumer of
  `personal_household_name` (`app/core/households.py`), the naming helper that
  survives for it. Two consequences to keep in mind:
  - **Zero households is a normal, reachable state**, not an edge case, and it is
    the state every fresh install and every new account begins in. Nothing may
    assume a user has any household, let alone exactly one, and leaving or deleting
    the last one is allowed. `Households` has a first-run empty state; the three
    pages carrying `noHouseholds` copy do so for two different reasons, so do not
    treat them as one guard: `Tags` because its list call omits `household_id` and
    so hits `get_current_household` (`api/deps.py`), which 404s for a member of
    none and is the only endpoint that hard-fails; `ChoreCreate` and `TagCreate`
    because their forms have no `household_id` to submit at all. Everything else
    (Home, Chores, History, Statistics, Logs) scopes through `member_household_ids` (or
    `owned_household_ids`) and simply returns nothing. Note the `noHouseholds` states are now unreachable through
    the *sidebar*, since a member of none reaches no role and `RequireRole` sends them
    to Home; they are kept because the guard is client-side and the URLs still work.
  - Do NOT seed a household in a migration: `households.admin_id` is NOT NULL, so
    a household cannot exist before its owner, and an owner-less row is what used
    to make `alembic upgrade head` unrunnable on an empty database.
- **Household roles**: `household_members.role` is a `varchar(30)`, `HouseholdRole`
  StrEnum on the backend only (`models/household.py`, same String-column pattern as
  `users.status`, so a new role needs no migration). organiser > deputy > helper, and
  `_ROLE_LADDER` / `roles_at_least` in `app/core/households.py` is the ONLY place that
  ordering is written down on the backend; on the frontend it is the order of the
  `HOUSEHOLD_ROLES` tuple in `lib/types.ts` (strongest first), which
  `lib/permissions.ts` derives its ranks from. A role added to the enum but missing from
  `_ROLE_LADDER` satisfies no predicate at all, which `test_every_role_is_on_the_ladder`
  pins.

  **"A new role needs no migration" is about ADDING one. Removing a rung needs a data
  migration before the deploy**, and the two failure modes are nothing alike. Off-the-ladder
  fails quietly, as above. A value that is not in the enum at all fails hard, because three
  places coerce the raw string: `role_in_household` and `memberships_for`
  (`core/households.py`) and `build_members_page` (`api/v1/households.py`), and
  `HouseholdRole('guest')` raises `ValueError`. Measured with one hand-edited row: that
  member's `/auth/me` AND `POST /auth/login` both 500, so they are locked out rather than
  degraded, and `GET /households/{id}/members` 500s for **every housemate** and for site
  admins on Admin > Households. `/home` and `/unscheduled` survive, because
  `member_household_ids` compares in SQL (`role IN (...)`) and never coerces. The 422 at the
  schema layer keeps this unreachable through the API, so it is operator error - but it is not
  contained to whoever holds the row.

  Capabilities: every role completes chores (scheduled and unscheduled), reads the household
  list, and sees **their own** closures on History (undoing them included); deputy adds the
  whole household's History plus Statistics; organiser adds chore and tag management, undoing
  *anybody's* closure, and inviting and setting deputy/helper roles. **Ownership then adds one
  page of its own, Logs** (`api/v1/logs.py`), which is the only surface gated on `admin_id`
  rather than on a rung - see the household-log section. Nine things to keep straight:
  - **`admin_id` and `role` overlap on purpose, and the owner always wins.** Ownership
    stays `households.admin_id`; the owner is by definition an organiser, their role is
    not editable (409 from the member PATCH), and `set_household_admin` *promotes the
    new owner* as part of the transfer. Drop that promotion and handing the household to
    a helper leaves them owning something they cannot manage the chores of, with no way
    to fix it, because the role endpoint refuses to touch the owner's row. What stays
    owner-only is renaming, deleting, removing members and transferring; inviting and
    role-setting are organiser-level (`_get_organised_household`). The one asymmetry: an
    organiser may move people between deputy and helper but may not hand out `organiser`
    or touch a row already holding it, so they cannot grow the set of people who could
    demote them - and cannot demote themselves, which falls out of the same rule rather
    than needing its own check. `update_household_member` orders its checks
    deliberately: the owner's row 409s *before* any caller rule, because "the owner is
    always an organiser" is a property of the target, so every caller gets the same
    actionable answer. `assignableRoles` in `frontend/src/lib/permissions.ts` is the
    frontend's single mirror of all of it, and returning `[]` there is what renders a
    badge; its organiser branch derives its options from `HOUSEHOLD_ROLES` rather than
    listing them, because the backend states the same rule as a negation and a new role
    would otherwise be accepted by the API but missing from an organiser's Select. Note
    invitations are per household, not per inviter: every organiser sees and can revoke
    the whole list, and `MAX_PENDING_INVITATIONS` is a shared budget. That count is a
    read-decide-write with no constraint behind it, and widening the endpoint from one
    inviter to several made the race reachable - 12 parallel POSTs landed 11 invitations
    against a cap of 5 - so `create_invitation` takes
    `pg_advisory_xact_lock(household_id)` first. Transaction-scoped, keyed per household,
    and only ever after `_get_organised_household`. **The suite cannot cover it**: the
    fixtures give each test one connection inside a rolled-back savepoint, so two
    concurrent sessions never exist. Verify by hand with parallel `curl`, like the boot
    migration. `Households`' row action follows the same widening - the pencil is
    `owned || hasRoleIn(..., 'organiser')`, because an eye labelled "View" hid a page
    organisers now have real work on. Setting a role goes through a confirmation, and
    that dialog is **controlled and rendered once for the table**, unlike every other
    AlertDialog in the app: a Select's `onValueChange` is not a trigger click, so there
    is nothing for an `AlertDialogTrigger` to wrap and no per-row uncontrolled dialog to
    use. Cancelling needs no revert because the Select is controlled by `member.role`,
    which never moved.
  - **Reads narrow, writes 403** ("union for nav, scope the data"). Home, Statistics, Logs and
    the chores list each span every household, so they take `member_household_ids(user_id,
    min_role)` (or `owned_household_ids` for Logs) and return *less data* rather than refusing:
    a deputy in one household and a helper in another gets the first one's statistics and never
    learns the second has any. **History is the exception that combines two scopes rather than
    picking one**: an `or_` of the deputy scope and the plain membership scope restricted to
    `completed_by_user_id == caller`, so the same page shows everything in one household and
    only your own rows in another. It is unconditional in the sidebar for that reason - there is
    no rung to gate it on. The `or_` lives in the shared `filters` list so `total` narrows with
    the rows; narrowing only the page query would make the pager offer pages that come back
    empty. Mutations go through `require_role`, which 403s, because the caller can see the
    resource elsewhere and a 404 would be a lie. **`undo_completion` is the one write that
    hand-raises instead**, because its rule is a disjunction (the recorded completer, OR an
    organiser of that household) and `require_role`'s "Only household organisers can do this"
    would deny the deputy who recorded the closure. Its 404 boundary is plain membership, not
    the deputy scope: a helper reaches History for their own rows now, so a 404 on a row they
    can see would be exactly the lie this rule warns about. The owner passes on their membership
    row, which a transfer always promotes - never on `admin_id`, which that endpoint
    deliberately does not read. One documented stretch: a helper targeting a housemate's row
    gets the 403 even though they cannot see that row anywhere, which makes it a weak existence
    oracle inside their own household. Accepted; nothing in the response body is personal data.
    `GET /chores/{id}` is ungated on purpose (the description dialog on Home and
    Unscheduled needs it for helpers), which is why the chores router has both
    `_get_user_chore_or_404` and `_managed_chore_or_error`. The management list has its own
    schema, `ChoreListRead` - a sibling of `ChoreRead` under `ChoreReadBase`, carrying
    `has_description: bool` where the detail read carries the HTML (see the rich text section).
    **Because that detail read is open, `ChoreRead.assignees` and `.current_assignee` are
    `HouseholdMemberRead`, never `UserRead`.** They used to be the latter, which handed a helper their housemates'
    email addresses, and `ChoreRead` was the only route exposing a `UserRead` to a
    household peer at all - which is why `main.py`'s avatar accepted-risk note can now
    leave peers out of the holder set. Keep any new payload a household peer can reach
    off `UserRead`, or that reasoning stops holding. The whole tags router IS gated on
    reads too, because no view a non-organiser reaches offers a tag to pick or filter by
    - but that is about the *surface*, not secrecy: `ChoreRead.tags` still reaches any
    member through the open chore read, so do not restate the gate as "tag names are
    hidden".
  - **`GET /completions/filters` is deliberately NOT role-narrowed.** It also feeds the
    Home and Unscheduled filter bars (`useFilterOptions.ts`), which every role uses, so
    narrowing it would empty those pickers. Three pages now reuse it and narrow client-side:
    Statistics and Logs filter its `households` (by role and by *ownership* respectively);
    History deliberately stopped narrowing at all, since a helper household is now a live
    option that yields the caller's own rows. It hides its whole filter bar instead when the
    caller reaches deputy nowhere, because their own closures are already the entire list. The
    known dead end all three share: the member list spans every household the caller belongs
    to, with no member -> household association to narrow it by, so a person plus a household
    that do not pair yields an empty page. Nothing leaks (those names are on Home already).
  - **`add_member` takes a required role, and the column's `server_default` is
    `helper`.** `household_members` is a Core `Table`, so the `members` relationship
    inserts the two foreign keys only and would leave any bypassing path on the default.
    That default is the weakest role rather than the strongest for exactly that reason.
    `db/seed.py` and `tests/conftest.py` both used the relationship and were converted;
    do not put it back.
  - **`conftest.make_household` defaults every member to `organiser`.** Load-bearing:
    before roles, membership granted everything, so that default is what keeps the
    chores / tags / stats / history suites testing their own subjects instead of several
    hundred assertions about 403s. Role tests pass `roles={user.id: ...}`.
  - **`HouseholdMemberRoleRead` is a subclass, used by the two members endpoints
    alone.** `HouseholdMemberRead` is shared by six other payloads (assignees on Home,
    Unscheduled and the chore reads, History's `completed_by`, the filter options, an
    invitation's `invited_by`), none of which join a membership row, so `role` on the
    base would either leak into all of them or fail validation. `build_members_page`
    selects `household_members.c.role` alongside `User`. Same split on the frontend:
    `HouseholdMemberWithRole`, not a field on `HouseholdMember`.
  - **Every response carrying the signed-in user carries their memberships**, via
    `_me_read` in `api/v1/auth.py`: `/auth/me`, the login response (`LoginResponse.user`
    is `MeRead`) and `/verify-2fa`. Each one is `(household_id, role, owned)` -
    `memberships_for` returns a `Membership` NamedTuple, and `owned` costs no query because
    `Household` is already joined for the `deleted_at` filter. `owned` is a separate fact from
    the ladder rather than a rung on it, and it is the only thing the Logs page is gated on. Login sets the client's auth state directly rather
    than refetching, so without that the first screen after signing in would render the
    minimal nav. The frontend holds them as `memberships` on the auth context (a sibling
    of `impersonating`, same reasoning: not a property of the user account) and reads
    them only through `lib/permissions.ts`. They are **advisory**: the API re-checks on
    every request, so a stale copy shows or hides the wrong nav item until the next
    `/auth/me` and grants nothing.
  - **Anything that changes the caller's OWN memberships must `refresh()`.** The context
    is populated at login and never refetched on its own, so all five handlers that move
    the caller in or out of a household - or change what they hold in one - re-read
    `/auth/me`: `HouseholdCreate` (creating one makes you its organiser), `AcceptInvite`
    (joining makes you a helper), `HouseholdEdit`'s `leave()`, `Households`' delete (a
    soft-deleted household drops out of `memberships_for`), and **both `HouseholdOwnerSelect`
    call sites** (`HouseholdEdit` and its admin twin), since a transfer drops the caller's
    `owned`. Gaining one is the loud direction: a brand-new account creates its first
    household - the documented first step for every new user - and without the re-read still
    sees the no-household sidebar, with every management page bouncing off `RequireRole` until
    they reload by hand. Losing one is quieter but not harmless: the sidebar keeps offering
    what that household granted, and Tags then 404s with nothing on screen able to clear it,
    since no stored filter is at fault. The transfer case is the newest and was missing until
    Logs existed, because until then no nav item moved on a transfer. Each of the five is
    pinned by a test that fails when the `refresh()` is removed. Note `Households.tsx` and both
    edit pages still read ownership from the household row's `admin_id` rather than from
    `owned`: they hold the authoritative value, and Admin > Households renders households the
    operator has no membership in at all. Not duplication to collapse.
  - **`RequireRole` cannot decide anything per household**, only "reaches the role
    somewhere", because the pages behind it span all of them. A page acting on one
    specific household needs its own check where the API would let it get that far:
    `ChoreEdit` does one and leaves for the list otherwise, since `GET /chores/{id}` is
    open to every role, while `TagEdit` needs none because `GET /tags/{id}` 403s by
    itself. History's undo cell is the second instance and the first that decides a *control*
    rather than a redirect: `hasRoleIn(memberships, entry.household.id, 'organiser')`, mirroring
    the API's disjunction row by row. **`RequireOwner` is a third guard, not a rung on this
    one**: ownership is off the ladder, so a pseudo-`min="owner"` would put "owner" into
    `HOUSEHOLD_ROLES`, and from there into a role picker and a PATCH the API rejects. Three
    guards, three different facts - a server-wide flag, a rung somewhere, `admin_id` somewhere. `HouseholdMembersTable` keeps its role props (`viewerUnrestricted`,
    `viewerRole`) separate from `canManage` rather than folding them together, because
    they govern different endpoints; both default to "nobody", which is what keeps a
    deputy or helper's view read-only without passing anything. `viewerUnrestricted` is
    named for the capability rather than for ownership because two different people hold
    it: the household owner, and a site admin on Admin > Households, who reaches the same
    reach through `PATCH /admin/households/{id}/members/{user_id}`. Both member-role
    routes go through the shared `set_member_role`, so the owner-row 409 and the
    disabled-member 404 are written once; `refuse_owner_row` is called separately by the
    user-surface handler as well, because *where* it fires decides whether an organiser
    targeting the owner hears about the target or about themselves. `HouseholdEdit` is a
    three-way page now, not two: owner edits the household, organiser shares the people
    work (roles plus invitations) on a read-only household, deputy and helper read
    everything.
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
- **Single sign-on (OIDC)**: `core/oidc.py` owns the protocol (discovery, the PKCE code
  exchange, ID token verification), `api/v1/oidc.py` owns the policy, and the whole thing
  is env-gated on `oidc_configured()` exactly as email is on `smtp_configured()`. The
  session it opens is an ordinary `auth_tokens` row: nothing downstream can tell an SSO
  session from a password one, deliberately. Thirteen things to keep straight:
  - **Both endpoints are GET and both answer with a redirect, and neither is a style
    choice.** Auth cookies are `SameSite=Lax`, which a browser sends on a cross-site
    top-level *navigation* but not on a cross-site POST, so a `form_post` response mode
    would arrive with no state cookie and fail the browser-binding check every time. GET
    also means `CsrfProtectMiddleware` exempts them on method alone, which is what makes
    the callback reachable: it is a navigation from the provider with no chance to set
    `X-CSRF-Token`. And redirects rather than JSON because the caller is a browser
    mid-navigation, not the `api` wrapper, so a refusal has to land somewhere readable -
    hence `?sso_error=<code>` on the login url.
  - **No nginx or CSP change was needed, and this is why.** The prod CSP is
    `connect-src 'self'; form-action 'self'`, which would block a browser-side token
    exchange or a form post to the provider. A backend-mediated redirect is covered by
    neither directive (CSP does not govern top-level navigations; `navigate-to` was
    dropped from the spec). Do NOT widen the CSP for this, and do not add
    `CORSMiddleware` - `core/csrf.py`'s whole defence rests on there being no CORS.
  - **No frontend auth-context change was needed either.** The callback sets the cookie
    and 302s to the SPA, so the app *cold-boots* and `AuthProvider`'s mount `/auth/me`
    probe picks the session up - already one of the four `claimTableSettings` adoption
    paths. So SSO is not a fifth one, and `AuthContextValue` / `makeAuthValue` are
    untouched. Keep it that way: a callback that returned JSON would need both.
  - **`joserfc`, NOT `authlib.jose`.** They are the same author's new and old JOSE APIs;
    `authlib.jose` emits a deprecation warning pointing at joserfc and is scheduled to go
    away in authlib 2.0, which would silently take ID token verification with it. authlib
    is still used, but only `integrations.httpx_client` for the code exchange - never
    `integrations.starlette_client`, which is the obvious import and the wrong one: it
    keeps `state` and `nonce` in a Starlette session, so adopting it would mean adding
    `SessionMiddleware` and a second signed-cookie mechanism competing with this
    codebase's "random token in an httpOnly cookie, SHA-256 hash in Postgres" pattern.
  - **`oidc_login_states` is a table rather than a fat cookie**, shaped like
    `TwoFactorChallenge`, for three reasons a cookie cannot cover: the nonce and PKCE
    verifier must not be client-controllable; deleting the row on use makes a flow
    single-use, so a captured callback url cannot be replayed; and `expires_at` bounds it
    like every other short-lived token here. The raw token doubles as the `state`
    parameter *and* the `isachore_oidc` cookie value, and requiring the two to match is
    the browser binding - without it an attacker starts a flow and feeds the victim its
    callback url, landing the victim in the attacker's session. Compared with
    `compare_digest`, since the caller controls the query parameter and the cookie is
    httpOnly. `isachore_oidc` is deliberately absent from `_AUTH_COOKIES` in
    `core/csrf.py`, for the same reason `isachore_2fa` is: it authenticates nobody, so it must
    not turn an anonymous request into one that middleware reads as a session. Note listing it
    would not actually break today's endpoints, since that middleware only inspects unsafe
    methods and both are GET - the reason above is the one that survives a change of method.
  - **`_consume_state` commits the delete before the caller talks to the provider**, and that
    is not tidiness. `complete()` makes up to five calls to the provider (discovery, token,
    JWKS, a forced JWKS re-fetch, userinfo), each with its own 10s timeout, so holding the
    transaction across it would park a pooled connection for as long as a degraded provider
    takes to answer - a slow IdP would exhaust the pool and take the rest of the API down, not
    just sign-in. Separately, the claim is a **single `DELETE ... RETURNING`** rather than a
    SELECT then a delete: that gap is a race, and the loser of it would raise `StaleDataError`
    (an unhandled 500) where a clean refusal belongs, which a double-click on a slow callback
    is enough to reach. Neither property is testable under the savepoint fixtures - one
    connection, one rolled-back savepoint, so two concurrent transactions never exist - so
    both rest on reading the code, like the invitation advisory lock and the zone-change race.
  - **`/start` has its own throttle, with its own ceiling.** It is unauthenticated and writes
    a row per call, and the opportunistic sweep only clears rows past their ten-minute TTL, so
    nothing just inserted is eligible: without a bound an anonymous loop grows
    `oidc_login_states` for as long as it runs. Its counter is separate from the callback's
    because it counts *every* start rather than every failure, so `login_ip_max_attempts` (20,
    sized for failures) would break a shared office NAT on a Monday morning;
    `_OIDC_START_MAX_ATTEMPTS` is an order of magnitude above any human sequence. Keeping them
    separate also stops a run of provider errors from spending a legitimate user's budget for
    retrying, which is pinned by its own test.
  - **The identity link is TWO columns, `users.oidc_issuer` and `users.oidc_subject`,
    unique together.** `sub` is only promised unique *per issuer*, so with the subject
    alone an operator repointing `OIDC_ISSUER` at a different provider whose subjects
    happened to collide would match one person onto another's account. With the pair the
    lookup simply misses and falls back to email, which re-links correctly. Postgres
    treats NULLs as distinct, which is what made the constraint safe to add to a populated
    table. Email finds the account on a **first** sign-in only; after that the subject
    does, so changing an address at the provider keeps the account, and the local `email`
    is never overwritten from the provider.

    **The re-link only self-heals when the new provider hands out a different subject.** If it
    reuses the same value under a new issuer the row is simply re-pointed (pinned by
    `test_the_same_subject_from_the_configured_issuer_re_links`); if it hands out a *new*
    subject for somebody already linked, the email match finds a row whose stored subject
    differs and `already_linked` refuses - by design, since that refusal is the account
    takeover guard. There is deliberately no in-app unlink, so recovering a provider
    migration is the SQL in README's single sign-on section. `cli init` clears the link too
    but only for the account it recovers and only during an admin lockout, so it is not that
    tool.
  - **Verification is isachore's own question, answered by `users.confirmed_at`.** The
    provider's `email_verified` claim is not read at all, and `OidcIdentity` has no field for
    it. Two reasons, and the second is what settled it: the account already exists because an
    admin created it, so the provider's job here is to prove who is at the keyboard rather
    than to re-assert something this app already tracks; and the claim varies enough between
    providers to be a poor gate - Authentik's default scope mapping omits it entirely, others
    stringify it, others always send true. Gating on it turned a correctly configured
    Authentik away with advice about verifying an address it had never made a claim about.

    So the exposure is exactly this: anybody who can self-assert an address inside the
    directory can link to and sign in as the local account holding it. Admin-created accounts
    plus a trusted directory is what stands in for the claim. That is a deliberate product
    decision, reaffirmed after being raised. Three narrowings if it ever needs closing,
    cheapest first:
    - **Refuse only when the claim is present and false** (`bool | None`, refuse on `False`).
      Authentik omitting it keeps working, providers that always send true are unaffected, and
      a directory actively reporting an unverified address is caught. The cost is real though:
      it brings back both the tri-state read *and* per-source selection in `build_identity`,
      since a verdict from one mapping must not be paired with the other's address.
    - **Gate the `waiting_confirmation` -> `active` transition** on the claim when present,
      leaving linking alone. The best-targeted of the three, because that transition is the
      one place this app writes `confirmed_at` on the strength of a provider sign-in, and the
      Profile badge then reports it as proved.
    - **Gate linking unconditionally**, and accept that providers omitting the claim stop
      working. What this app did before, and what turned a correct Authentik away.

    `confirmed_at` is surfaced instead, on Profile, as a badge beside the address - shown only
    where the server asks for confirmation at all, since a null means nothing on a server that
    never asks. `MeRead.email_confirmation_required` is what tells a client which of those two
    readings applies; it rides on the me payload rather than /settings because that endpoint
    is admin-only and this is a fact every user's own page needs.
  - **`totp_enabled` is deliberately not consulted in the callback.** The provider owns
    authentication including its own MFA, so re-challenging for a local code asks the same
    person to prove themselves twice for nothing. It reads like an omission, which is why
    it carries a comment there, a test, and a line of copy on `TwoFactorSettings`: without
    that copy, somebody who just enrolled reads an SSO sign-in that never asked for a code
    as a bug. Local 2FA still applies in full to password sign-in.
  - **Audit reuses `login_success` / `login_failed` with an `"oidc"`-prefixed `detail`**,
    rather than new enum members: `audit_events.action` is a native Postgres enum, so a new
    value needs an `ALTER TYPE`, and `cli.py` already sets the precedent of reusing an
    action. Do not add SSO actions without reading that note first.
  - **`OIDC_ONLY` is gated on `oidc_configured()` too, in both places that read it**
    (`login`'s 403 and `/auth/methods`). The flag alone is a total lockout, and while
    `check_startup_config` refuses that combination, **dev is exempt from every startup
    check** - so without the second clause a developer who set the flag and nothing else
    locks themselves out of their own stack with no explanation. There is deliberately no
    admin exemption: an `is_admin` carve-out would tell an anonymous caller whether an
    address belongs to an admin.
  - **`begin` and `complete` are called through the module** (`oidc_core.begin(...)`), for
    the same reason endpoints call `clock.now()`: it leaves
    `monkeypatch.setattr(oidc_core, "complete", ...)` able to reach them, so the whole
    policy is testable with no provider. Importing the names would bind them at import time
    and silently defeat every stub in `tests/test_oidc.py`. The redirect uri is derived
    from `app_base_url` rather than configured, which is also why it is reported on
    **Admin > Server settings**: it is the value an operator has to register with the
    provider and there is nowhere else to read it.
- **Impersonation**: `POST /users/{id}/impersonate` swaps the session cookie to
  the target user and parks the admin's own token in the `isachore_admin_token`
  cookie; `POST /auth/stop-impersonating` restores it. `/auth/me` reports
  `impersonating`; logout ends both sessions.
- **The household log** (`household_log_entries`, `core/household_log.py`, `api/v1/logs.py`,
  `pages/Logs.tsx`): who changed what in one household's chore management, plus who undid a
  closure, read by that household's **owner** alone. Deliberately NOT `audit_events`, which is
  the operator trail for auth / 2FA / admin user management: that one keys its action off a
  native `audit_action` enum, so a new value needs an `ALTER TYPE` (which is why `cli.py`
  reuses `user_updated` rather than adding one), and it carries `ip_address`, which must never
  reach a household surface. Seven things to keep straight:
  - **`action` is a `String(50)` with a `HouseholdLogAction` StrEnum supplying the values**,
    the same pattern as `household_members.role` and `users.status`, so a new action needs no
    migration. `test_the_action_column_holds_every_action` is what actually pins that. The wire
    carries `action` and `changed_fields` as plain **strings**, not the enum and not a Literal
    union: coercing them back would raise on a row a newer release wrote, i.e. an unfilterable
    500 on every page holding one, so the closed set lives on the client
    (`LOG_ACTIONS` / `LOG_FIELDS` in `lib/types.ts`) and `lib/logs.ts` degrades an unknown value
    to a readable form. Those two tuples are hand-mirrors of `HouseholdLogAction` and
    `CHORE_LOG_FIELDS` with nothing checking them, like `HOUSEHOLD_ROLES` and `users.language`:
    keep them in step by hand. The enum still guards the `action` query *parameter*, where a 422
    is right.
  - **Undoing a completion and undoing a skip are two actions, not one with a flag.** They
    read completely differently to whoever is looking, and nothing downstream re-derives which
    it was - the flag is cleared by the reopen itself. **`target_user_id` is the other half of
    that**, and `Logs.tsx` renders it as a muted suffix on the action cell ("Completion undone -
    recorded by Jo Ng"): without it a row says somebody undid something and never whose work
    went, which is the entire reason an undo is logged separately from the closure it erased. A
    suffix rather than a column because only those two of five actions carry a target. The
    filter beside it is the **actor**, hence "Changed by" rather than "Person".
  - **The log holds no reference to the occurrence, and cannot.** `undo_completion` has two
    branches and each defeats a different `ondelete`: reopening nulls the row's title,
    completer and completion time in place, so a surviving FK points at something that no
    longer describes the closure; the older-closure branch hard-deletes the row, so RESTRICT
    would 500 a working feature and CASCADE would let an append-only log erase itself. So the
    handler captures `chore_id`, `title`, `completed_by_user_id` and `skipped` into locals
    **before** the branch and writes from those alone. `chore_id` is `SET NULL` for a related
    reason: CASCADE would let the log delete its own rows, and RESTRICT would break a hard
    household delete, which cascades into `chores` in an order Postgres does not guarantee
    against this table's own CASCADE. Nothing hard-deletes a household today, so that is a
    landmine avoided rather than a live requirement. `chore_title` is the snapshot that keeps a row readable either
    way, exactly as `chore_occurrences.title` does against a rename.
  - **A chore edit records which field names moved, never their values**, in
    `CHORE_LOG_FIELDS` declaration order (so a row is stable and the UI never sorts). The diff
    is two `snapshot_chore` calls on the *same* object, before and after the assignments in
    `update_chore` - never the object against the payload - so every normalisation
    `_normalised_schedule` applies is reflected on both sides and cannot drift. `weekdays` is
    snapshotted as a tuple, which neutralises the ARRAY aliasing footgun by construction, and
    `[]` collapses to `None` so a normalised legacy row reports no phantom change.
    `description` compares the stored strings as they are: both sides are already
    `SanitisedHtml` output, and re-sanitising the older side would hide a real allowlist
    tightening instead of reporting it. A rename records the title the chore **ends** with, so
    its row names something that did not exist a moment earlier while older rows keep the old
    name; the `title` entry in the Changed column is what explains the discontinuity to a reader
    scanning by name. Accepted deliberately - carrying the old title too would be a value, and
    this log records names of fields, never their contents. **The open occurrence's assignee is deliberately
    absent** - it is derived and `_reconcile_open_occurrence` recomputes it on most edits - so
    a PATCH that only moves `current_assignee_id`, or only sets `clear_current_assignee`,
    writes no entry at all. Both are pinned; so is the no-op edit, which writes nothing.
  - **`record_log_entry` only `session.add`s; the caller commits.** Same contract as
    `core/audit.py`'s `record_event`, and it is what makes the 409 path in `update_chore`
    correct for free: the entry is staged *before* the `try`, so the rollback expunges it and a
    retry writes exactly one. Never move it after the commit.
  - **Retention is 90 days, enforced twice.** `LOG_RETENTION` is a module constant, NOT a
    Settings field - a product promise rather than a deployment knob, like
    `MAX_PENDING_INVITATIONS`. The read endpoint applies it as a query predicate *and* a daily
    `prune-logs` scheduler job deletes past it, so the promise holds on a deploy where the job
    has never run and the table still does not grow without bound. `prune_old_log_entries` is unit-tested, but neither suite runs
    `run_prune_logs`'s own session or fires the scheduler: verify those by hand with the CLI
    (see README) after back-dating a row. **The 409 path in `update_chore` is by-hand-only
    too** - the collision needs a genuinely concurrent `POST /complete`, which the savepoint
    fixtures cannot produce, so the "rollback expunges the entry" claim rests on reading the
    code, like the advisory-lock note above.
  - **The impersonator is recorded but never named to the household.** `by_admin: bool` on the
    read schema, the id in the column: the operator may be a stranger there, and the rule
    about keeping household-peer payloads off `UserRead` applies to their identity too. Nothing
    reads that id - it is there for a by-hand query, and `audit_events` is what holds the
    durable impersonation trail, unpruned.
    Both people on a row are `HouseholdMemberRead` (no email), and there is no free-text column
    for a caller to write into - a `detail` field on a surface a housemate reads is where
    personal data creeps in. (`chore_title` is user-authored text, but a copy of something the
    reader already sees on the chore itself.) The writer also emits **no application log line**,
    deliberately unlike `record_event`: a copy there would sit outside the 90-day promise, since
    logs ship off-box under their own retention. That plus the bounded window is the whole
    AVG / ISO 27001 story, and keeping it in one place is what makes it true.
- **Timezones are per household** (`households.timezone`, an IANA name in a `String(64)` with
  the closed set enforced at the schema layer, same pattern as `users.status`). A household is
  a physical place, so the zone belongs to it rather than to a user. The invariant everything
  rests on:

  > **`chore_occurrences.scheduled_for` is local midnight of the day the chore is due, in its
  > household's zone.** So 5 August in Amsterdam is `2026-08-04T22:00Z` in summer and
  > `2026-01-04T23:00Z` in winter, and reads back as local midnight on the 5th either way.

  Answered in UTC, `days_until_due` told someone in Amsterdam at 01:30 that today's chore was
  due tomorrow, because 01:30 local is still yesterday in UTC. Eight things to keep straight:
  - **Two things deliberately do NOT move, and re-anchoring either is a data-corruption bug.**
    `completed_at` is stamped from `clock.now()` when the button is pressed: it is a plain
    instant, correct in every zone, and only the day boundary it is *read against* was ever
    wrong. And an **unscheduled (`manual`) chore's `scheduled_for`** is the moment it became
    available, not a calendar anchor. The timezone migration excludes both; so does
    `reanchor_open_occurrences`.
  - **`chores.start_date` stays a plain `date`.** It records the day the household means to
    start, and `first_occurrence` is the single place that turns it into an instant, in the
    household's zone. That is why the column, the wire type and `ChoreForm`'s Calendar all
    needed no change. Do not "fix" it into a timestamp.
  - **The DST-correct arithmetic is free, and only because the datetimes carry a `ZoneInfo`.**
    Python adds to an aware datetime's wall-clock *fields* and keeps its tzinfo, so
    `dt + timedelta(days=1)` really is "the same local time tomorrow" and `_add_months`'
    `replace()` behaves the same way. Every function in `core/chores.py` therefore converts to
    `tz` first; doing the arithmetic on a UTC-aware value is what would drift by an hour twice
    a year. A step can land on a local time that does not exist (zones whose transition is at
    midnight); `fold=0` resolves it to a real instant on the correct *date*, which is all the
    date-based comparisons read.
  - **Home and Statistics span several households at once, so there is no single day window.**
    Both call `zones_in_scope` (`core/households.py`) and OR one `local_day_bounds` clause per
    distinct zone - seeded with `false()`, which is both the right answer for a user in no
    household and what keeps it off SQLAlchemy's deprecated argument-less `or_()`. Statistics
    additionally buckets each completion by *its* household's local day and seeds its chart
    axis over the union of the per-zone ranges. Two things there are easy to get wrong: the
    per-row zone is read off a **joined `Household.timezone`** rather than a dict keyed from
    `zones`, because the session is READ COMMITTED and a membership changing between the two
    statements would make a subscript 500 the page; and the axis falls back to a UTC window when
    the zone set is empty (`axis_windows`), because a **helper-only** caller reaches deputy
    nowhere and still gets a 200 - without the floor their chart is `[]`, which recharts renders
    as blank space rather than a flat line.
  - **Never `AT TIME ZONE <column>` at runtime.** Postgres carries its own copy of the tz
    database, so a name Python and Postgres do not share raises *inside the query* - a 500 from
    SQL rather than a 422 from a validator. The zone maths is Python's, which is also why
    `local_day_bounds` exists. The timezone migration is the one exception and is safe only
    because every row holds the same hardcoded zone at that point.
  - **`household_zone` falls back to UTC on an unknown name rather than raising**, for the same
    reason the household log's `action` stays a plain string on the wire: it runs on read paths
    spanning every household a user belongs to, so raising would take out My Chores, History and
    Statistics for everyone in a household holding one bad row. Unreachable through the API,
    which validates against `available_timezones()` on write.
  - **Changing a household's zone re-anchors its OPEN slots** (`apply_timezone_change` ->
    `reanchor_open_occurrences`), reinterpreting each wall-clock reading in the new zone so
    "due 5 August" still says 5 August. Done rows genuinely stay put, and that is now a clean win
    rather than a trade, because of the column below.
  - **`chore_occurrences.completed_timezone` snapshots the zone a closure was judged in**, and
    `closure_zone` (`core/occurrences.py`) is the only place its NULL fallback is written down.
    Lateness is a *calendar* judgement - `completed_at`'s local date minus `scheduled_for`'s - so
    read against the household's current zone it moved whenever the household did: a slot at
    22:00Z with a completion at 21:00Z the next day is 0 days late in Amsterdam and 1 in
    Pacific/Niue, which silently re-scored History's badge, `punctuality` and `on_time_rate`.
    Reading both operands in the snapshot makes the answer immutable, exactly as snapshotting
    `title` makes history survive a rename. Four things to keep straight:
    - **Shifting `completed_at` is NOT the alternative, and reviewers keep proposing it.** It is
      the instant the work happened, and it is load-bearing as an absolute: stats windows filter
      on it, `undo_completion` finds the latest closure by `max(completed_at)`, and Home's "done
      today" compares it to real day bounds. Reinterpreting its wall clock produces a *different
      instant*, so the row would claim the work happened at a time it did not - measured at 12
      hours out for an Amsterdam to Kiritimati move.
    - **Re-anchoring the done `scheduled_for` is not the alternative either.** It looks like it
      works on the case you first try and does not generalise: a completion at 23:30 local on its
      due day reads 0 days late in Amsterdam and 1 after the same move, re-anchored or not.
    - **Only historical judgements read the snapshot**: `days_late` (History and stats), the
      stats bucket key, and History's rendering of `completed_at` - which is on the wire as
      `HistoryEntryRead.completed_timezone` for exactly that. A row must not render its timestamp
      in a different zone from the one its lateness was computed in: a closure at 21:00Z reads
      "5 Jul, 23:00 / on time" in Amsterdam and "6 Jul, 11:00 / on time" against a 5 July due date
      once the household moves to Kiritimati. `days_since` on Unscheduled and Home's "done today"
      window are the other side of the line - anchored to *now*, so they stay in the household's
      current zone, and pairing a snapshot operand with a live one compares two calendars.
    - NULL means "not judged yet" (every open row) or "closed before the column existed", where
      the fallback is the household's current zone: the old behaviour, and all the migration's
      backfill can honestly reconstruct. Note the timezone migration re-anchors done rows too (it
      has no `status` filter), which is right there and would be wrong at runtime: one statement
      applying a uniform downward shift to rows all at midnight UTC cannot collide, while
      row-by-row ORM writes shifting *forward* can put one row onto a slot the next has not
      vacated.
    Every candidate goes through `free_slot_from`, because the new instant can land on a slot
    the chore has already completed, and the select takes `FOR UPDATE OF chore_occurrences` so a
    concurrent `POST /complete` cannot flip a row to `done` between the read and the write - the
    one way this could re-date a history row. **`commit_household_update` owns the re-anchor as
    well as the commit**, because that is where a collision can actually be raised: the re-anchor
    writes row by row and `free_slot_from`'s SELECT autoflushes the previous iteration on the way
    past (observed as `['UPDATE', 'SELECT']`, since `async_sessionmaker` leaves `autoflush` on),
    so a `try` around `commit()` alone would let `uq_occurrence_chore_scheduled` escape as a 500
    while the docstring promised a 409. It is the lock rather than the walk that makes both
    branches near-unreachable, so neither is testable here.

    **That lock is not enough on its own, and `_close_occurrence` holds the other half.** A
    `FOR UPDATE` on the re-anchor's side delays a concurrent completion's *write*; it does nothing
    about the read that completion already took. `complete`/`skip` get their chore and occurrence
    from plain selects before `_close_occurrence` runs, and nothing carries a `version_id_col`, so
    a zone change committing in between left the closure computed from a slot and a zone that no
    longer belonged together - silently, since neither raises. Measured on an
    Amsterdam-to-Niue move: the successor anchored 11 hours off the grid and *stayed* there
    (later completions walk from that anchor), and `completed_timezone` was stamped with the old
    zone onto a row whose `scheduled_for` the re-anchor had already moved, reporting 1 day late
    where the answer is 0. So `_close_occurrence` re-reads **both** operands after taking
    `refresh(occ, with_for_update=True)` - the lock first, then the zone by its own select, never
    from `chore.household`. Order matters: whichever transaction takes the row first, the other
    either re-reads what it wrote or finds the row already `done` and skips it.

    Two things follow. A one-row lock rather than `pg_advisory_xact_lock(household_id)`, because
    the row is what a completion already contends on and a household-wide lock would serialise
    housemates completing different chores. And the residual is `undo_completion` reopening a row
    after the re-anchor's select has run, which leaves that row on the old grid until the next
    edit re-seeds it through `_reconcile_open_occurrence` - narrower again, and self-healing, so
    it is documented rather than locked. Both the user PATCH and its admin twin call the
    shared helper. `apply_timezone_change`'s two guards are about work rather than correctness:
    re-anchoring an *unchanged* zone writes nothing (SQLAlchemy issues no UPDATE for an equal
    value, and aware datetimes compare by instant), so what they save is one query per open
    occurrence on a plain rename.
  - **The frontend renders household timestamps in the household's zone**, via the optional
    `timeZone` argument on the three formatters in `lib/format.ts` and `lib/chores.ts`. It is
    carried on `ChoreHouseholdRead`, which is embedded in five payloads, so one field reaches
    Home, Unscheduled, History, the chore reads and the filter options. Without it a slot stored
    at 22:00Z prints "4 Aug" beside a server-computed "Due today" meaning the 5th. Account and
    admin surfaces (a user's `created_at`, an invitation's expiry) deliberately keep the
    viewer's zone: those belong to no household.
- **Who is on the hook now** is `chore_occurrences.assignee_id` on the single open
  occurrence, not a column on the chore; the pool is `chore_assignees` and the
  rotation order is computed, never stored (`app/core/assignment.py`). The API
  honours an explicit `current_assignee_id` for **every** strategy, not just
  `manual` (`_reconcile_open_occurrence`, deliberately ungated). The picker in
  `ChoreForm` therefore shows for `manual` always and for the auto strategies only
  where the page passes `allowAssigneeOverride` (edit does, create does not, so a
  random chore's first assignee stays random), and in both cases only with a
  non-empty pool. The load-bearing part is that `current_assignee_id` stays derived
  against the live pool: that is what lets the payload gate more loosely than the
  render (on the strategy, not also on the pool) and still never submit a stale or
  hidden value, since an empty pool forces `null` either way. For the auto strategies
  an override lasts until the next turn boundary, because completing re-derives
  through `_successor_assignee` — which
  is what the `currentAssigneeTurnHint` copy promises the user, so keep them in
  step. Every live chore has exactly one open occurrence whatever its period, so
  `current_assignee: null` means unassigned/shared and never "nothing left to do".
  **Handing a chore back to the household is its own field, `clear_current_assignee`,
  and cannot be folded into `current_assignee_id: null`.** Null already means "no
  explicit choice", and `_reconcile_open_occurrence` then *keeps* an assignee who is
  still in the pool — which is load-bearing, because `ChoreForm` submits null routinely
  whenever the picker is hidden (empty pool, or an auto strategy on create), so if null
  cleared the assignee then editing a random chore's title would silently unassign it.
  "Nobody" and "no opinion" are two different messages. The clear branch must also come
  **first and stop there** in that function: falling through to the recompute `elif`
  would immediately re-derive somebody from the strategy and undo it. In the form the
  choice is a `UNASSIGNED` sentinel option rather than `value=""`, which Radix reserves
  for "nothing selected" and would render as the placeholder instead.
- **Unscheduled chores** (`repeats: 'manual'`, a *different* field from the `manual`
  assignment strategy) are the chores you do ad hoc: **never due, never overdue,
  repeatable on demand**. Completing one flips its occurrence to `done` and opens a
  fresh one anchored at **the completion timestamp** (`next_occurrence_after`), so it
  stays available forever. That timestamp, not its midnight, because
  `uq_occurrence_chore_scheduled` is per (chore, `scheduled_for`) and a date would
  collide the second time a chore was done in one day. They used to be one-offs that
  terminated on completion; do NOT reintroduce that, and note the migration
  (`3c1f04a7e9d2`) reopens the ones it left dead. Consequences worth knowing:
  - **`chores.start_date` is nullable and NULL for every one of them.** It only ever
    seeded the first slot, which for an unscheduled chore means nothing, so their first
    occurrence opens at creation time instead (`initial_slot`). The schema layer keeps
    this true from both directions (`_normalised_schedule`): the date is silently
    dropped for `manual` and **required** for every other period, the one part of the
    schedule rejected rather than normalised. So a NULL `start_date` and `repeats ==
    manual` are the same fact, and `ChoreForm` hides the field and submits `null`. It does not
    *refill* the date when the period stops being unscheduled: `startDate` is derived
    (`values.start_date || todayISO(timezone)`), so an empty value resolves to today in the
    **household's** zone on its own - which is also what makes it follow a household switch on
    the create page. A date the form was handed, by cloning a scheduled chore, is kept instead.
  - Their `scheduled_for` records **availability, not a deadline**. Nothing may read it
    as one: `days_late` comes back `null` from History, and both `home.py` and `stats.py`
    exclude `repeats == manual` outright. In stats that means counted in
    `completed_in_range` / `completions_over_time` / `per_person` (work done is work
    done) and excluded from `currently_overdue` / `status_breakdown` / `active_chores` /
    `punctuality` / `on_time_rate`. The live snapshot needs only ONE predicate for the
    first three (same query), which also preserves "the three buckets sum to
    `active_chores`"; `punctuality` deliberately no longer sums to
    `completed_in_range`, and `on_time_rate`'s denominator is the scheduled completions
    alone.

    **`most_skipped` is the one entry on that list that needs neither treatment, and the
    reason is worth reading before you "fix" it.** A skip can only be *recorded* against a
    scheduled chore, since `skip_chore` refuses an unscheduled one - so it needs no
    `repeats != manual` predicate the way `punctuality` does. But `update_chore` can switch a
    chore to `manual` afterwards and its existing skipped rows survive that, so a row in the
    ranking CAN belong to a chore that is unscheduled *today*. Those are kept on purpose (the
    skips happened, and the chore is still there to be fixed), which makes this the one place
    a skip figure and `punctuality.skipped` can legitimately disagree: the latter reads
    `repeats` live and drops them. Do not add a predicate to make the two agree - it would
    hide chores from the list exactly when somebody has just reacted to being nagged about
    one by parking it as unscheduled.
  - The view is `GET /api/v1/unscheduled` + `pages/Unscheduled.tsx`, ordered
    **alphabetically** (sorting by slot would be a deadline in disguise) and reporting
    `days_since_last_completion` instead of any due field. Its dot uses the
    `--done-recent/week/stale` tokens, NOT `--due-*`: the scales cross over, since done
    today is green while due today is yellow.
  - **Their slots break three assumptions the grid used to guarantee**, every one of which
    bit once already. The root cause each time: an unscheduled chore anchors its successors
    at completion timestamps, so its done rows sit on **both sides** of its open one, and
    "the open slot is later than every done slot" is no longer true:
    - `undo_completion` finds the latest completion by `max(completed_at)`, NOT
      `max(scheduled_for)`. Slots only run in completion order while they come off a grid;
      switch a not-yet-due chore to unscheduled and its next done row is dated *earlier*
      than the one before it, so ordering by slot reopens the wrong occurrence (resurrecting
      a future slot with a stale assignee while deleting the live open row).
    - `_reconcile_open_occurrence` takes a `was_unscheduled` flag, read in `update_chore`
      *before* the payload overwrites `chore.repeats`. Unscheduled -> recurring must re-seed
      the slot from the new `start_date` rather than `snap_to_slot` it: snapping is the
      identity for every unpinned rule, so the chore would keep its last-completion moment
      and read as overdue by however long ago that was, while the form said "start today".
    - Every re-dated slot goes through `free_slot_from` (`core/occurrences.py`), which walks it
      past any slot the chore has **already completed**. `first_occurrence` and every grid slot
      are both local midnight in the household's zone, so re-dating onto a grid the chore has
      history on can land exactly on a
      done row; `uq_occurrence_chore_scheduled` then fails the commit and `update_chore`
      returns a 409 that retrying can never clear, since the same edit recomputes the same
      occupied slot. "Did it today, parked it as unscheduled, later put it back on a
      schedule" is enough to hit it, because the form pre-fills today's date.
- **Rich text descriptions**: `chores.description` is sanitised HTML in a `Text` column,
  authored in Tiptap v3. `backend/app/core/richtext.py` is the **single definition of the
  format** and the security boundary; the editor's `extensions.ts` and `index.css`'s
  `.rich-text` are downstream of it. Six things to keep straight:
  - **Sanitising happens on write, server-side, and that is not negotiable.** `/api/v1` is a
    JSON API with future non-browser clients, so a browser-side allowlist proves nothing:
    `curl` skips it. `SanitisedHtml` in `schemas/chore.py` puts `max_length` *inside* the
    `Annotated` so the cap runs on raw markup **before** the `AfterValidator` - that ordering
    is what stops a mostly-junk payload buying its way under the limit by being stripped.
    `target="_blank"` and `rel="noopener noreferrer"` are **forced** onto every link
    (nh3's `set_tag_attribute_values`), not merely allowed, so a payload posted with
    `target="_self"` is overridden rather than obeyed. Tightening the allowlist later does
    NOT clean old rows; that needs its own data migration.
  - **Links: the editor's rule is `isAllowedUri`, never Tiptap's `protocols` option.**
    `protocols` only *appends* to a hardcoded ten schemes (http, https, ftp, ftps, mailto, tel,
    callto, sms, cid, xmpp), so passing our three - all already in that list - narrows nothing.
    Left that way the editor accepts a `tel:` or `ftp:` link, renders it, and the server drops
    the href on save with nothing shown to the user: the exact silent formatting loss this
    design exists to prevent. `isAllowedRichTextUri` in `rich-text/format.ts` derives the rule
    from `RICH_TEXT_LINK_PROTOCOLS`, and `sanitise_html` passes `url_relative="deny"` because
    `ALLOWED_SCHEMES` bounds absolute URLs only - nh3 otherwise passes `//evil.example/x`
    straight through. The two sides must keep agreeing: whatever the server strips, the editor
    has to refuse, or the loss is silent again.
  - **"Empty" is not one value in HTML.** Every WYSIWYG emits `<p></p>`, `<p><br></p>` or
    `<p>&nbsp;</p>` for an untouched editor and all three are truthy, which is what makes a
    bare `if description:` wrong. `sanitise_description` collapses them to `NULL`, and
    `RichTextEditor` emits `''` rather than `<p></p>`, so `ChoreForm`'s `|| null` stays
    correct. Two gotchas inside `is_blank`: nh3 re-escapes on the way out, so stripping tags
    off `<p>&nbsp;</p>` yields the literal `&nbsp;` and needs `html.unescape` before
    `.strip()`; and the unescaped form must never be what gets stored.
  - **StarterKit is configured by subtraction, and that list is load-bearing.** `heading`,
    `codeBlock`, `horizontalRule` and `trailingNode` are all off. The first three sit outside
    `ALLOWED_TAGS`, so leaving one on means a user formats a heading, sees it look right,
    saves, and gets a plain paragraph back with no error; `trailingNode` keeps a *real*
    trailing paragraph that serialises, so it would make every document look non-empty.
    `Placeholder` (from `@tiptap/extensions`) is the exception that IS safe to add: it is a
    decoration, not a node, so it cannot touch `getHTML()` or `isEmpty`. Being CSS it is also
    invisible to assistive tech, hence the `aria-placeholder` beside it.
  - Read surfaces: the editor itself, and `DescriptionDialog` opened from the marker icon on
    `ChoreRow` (Home and Unscheduled). **No list sends the HTML**: Home, Unscheduled and the
    chores management list all carry `has_description: bool` instead, and whoever wants the
    markup fetches `GET /chores/{id}`. Only the first two *render* a marker from it; on the
    management list the flag is carried for shape parity, so adding one there later needs no
    API change. So a household's instructions never ride along on the
    landing page, and the worst-case payload of the 100-row management list is not 100 x
    `MAX_RICH_TEXT_LENGTH`. That list goes further than the other two and never *reads* the
    column either: `list_chores` selects a labelled `description IS NOT NULL` and applies
    `defer(Chore.description, raiseload=True)`, so the HTML does not leave Postgres. Note the
    suite cannot prove that part - the fixtures share one session, so an already-loaded chore
    keeps its description whatever the option says; check the compiled SQL if you touch it.
    The one consequence to keep in mind is that `Chores.tsx`'s clone action fetches the source
    chore before navigating, because a clone built from the row would silently lose the
    description. `RichText` is the only `dangerouslySetInnerHTML` outside `ui/chart.tsx`, and
    it is NOT a sanitiser: only ever pass it something the server has already cleaned.
  - `ChoreCreate` and `ChoreEdit` are `lazy()` in `App.tsx` for the same reason Statistics is:
    they are the only routes reaching `ChoreForm`, and that chunk is ~146 kB gzipped. A third page
    rendering `ChoreForm` needs splitting too, or the editor lands back in the main chunk.
- **Frontend auth**: `useAuth()` from `src/auth/useAuth.ts`; API calls through the
  `api` wrapper in `src/lib/api.ts` (throws `ApiError`). Protected routes wrap in
  `RequireAuth` / `RequireAdmin` (`src/components/`); authenticated pages render
  under the `TopBar`.
  - **`RequireAuth` renders `<Outlet key={user.id} />`, and that key is load-bearing.**
    Switching identity (impersonation starting or stopping) has to throw the page away,
    because *nothing else would*: `refresh()` updates the context and `claimTableSettings`
    clears the remembered filters, but no page's load effect depends on the auth context -
    `useServerTable`'s fetch deliberately does not, `useFilterOptions` has `[]` deps, and
    Home and Unscheduled lazy-initialise `assigneeIds` from `user.id` exactly once. Without
    it an admin leaving an impersonated session keeps that person's rows on screen. The key
    is `user.id`, NOT the user object: `refresh()` also runs after a profile save, which
    must not remount. Both directions are pinned in `RequireAuth.test.tsx`. What makes the
    remount actually clean is an ordering in `AuthProvider`: all four adoption paths call
    `claimTableSettings(me.id)` *synchronously* immediately before `setUser(me)`
    (`AuthProvider.tsx:54,106,137,150`). `useServerTable` reads `localStorage` in a lazy
    `useState` initialiser during the mount render, before any effect, so moving that clear
    into an effect would hand the remounted page the impersonated user's stored filters for
    one fetch. Keep it synchronous and keep it first. Note the URL
    query string is deliberately NOT rewritten, so a filter from the impersonated session
    stays in the address bar; every list endpoint scopes through `member_household_ids`, so
    it yields an empty page rather than someone else's data.
- **A Radix Checkbox inside a form swallows Enter**, deliberately (WAI-ARIA says Space
  toggles a checkbox), which is stricter than the native `<input type="checkbox">` it stands
  in for: there, Enter submits. `Login.tsx` hands the key back, and if a second form ever
  needs the same thing, copy all four clauses rather than the first one.
  `preventDefault()` runs first because Radix's `composeEventHandlers` runs the consumer's
  handler before its own and skips its own once the default is prevented, so that single
  call both frees the key and keeps Enter from toggling the box. Then `requestSubmit()`,
  never the submit handler directly, so constraint validation still runs. And `requestSubmit()`
  consults no button, so unlike implicit submission it is NOT stopped by a disabled submit
  button: without `e.repeat` and the submitting flag, a held Enter auto-repeats a burst of
  requests. Three other forms have the same shape and are deliberately untouched
  (`ChoreForm`, `admin/ServerSettings`, `users/UserForm` - the last is the one where the
  checkbox is the final control before submit). Extract a `lib/` helper if a second one
  adopts it; one caller does not earn the indirection.
- **Readable 422s**: `lib/validationError.ts` turns pydantic's `detail` *list* into one
  sentence, and `handle()` in `api.ts` calls it whenever `detail` is not a string. Every
  hand-raised `HTTPException` carries a string and is shown verbatim; only pydantic sends
  the list, which used to fall through to `res.statusText` ("Unprocessable Content"). It
  keys off the stable `type` discriminator rather than the English `msg`, through closed
  `const` tuples (`VALIDATION_TYPES`, `FIELD_NAMES`) so the dynamic `errors.validation.*` /
  `errors.fields.*` keys typecheck. Three things not to undo: `value_error` is deliberately
  absent from `VALIDATION_TYPES`, because our own validators write better English than any
  generic (it is unwrapped instead, and `EmailStr` is the one special case); `ctx` is passed
  under i18next's `replace` so a pydantic context key can never land as an i18next option
  (`count` would silently switch on pluralisation); and the wire shape stays the *array*,
  since `/api/v1` has future non-browser clients - do NOT add a backend
  `RequestValidationError` handler that flattens `detail` to a string. Translation goes
  through the `i18n` singleton, not a captured `t`: `api.ts` has no React context.

  **Open, and not settled by the above:** pydantic's stock handler echoes the rejected value
  back under `input`, so a password below `min_length=8` comes back in the response body in
  plaintext (`POST /confirm/{token}`, `PATCH /users/{id}`, the profile password change).
  `formatValidationDetail` never reads `input`, so nothing leaks in-app - it is a wire and
  log-capture exposure, and one worth an AVG/ISO 27001 look. Stripping that one key in a
  `RequestValidationError` handler would keep the array contract intact, so the rule above
  does not rule it out. It predates this work and has not been decided either way.
- **Design tokens** (colours, fonts, radii, shadows) live ONLY in
  `frontend/src/index.css`, never hardcode hex in components. They are split by
  role: theme-invariant tokens (fonts, shadows, brand radii) under `@theme`; the
  runtime colour vars under `:root` / `.dark`; the utility mappings (shadcn's
  `--color-*` names and the legacy isachore aliases) under `@theme inline`.
  Tailwind v4 is CSS-first: there is NO `tailwind.config.js` and none should be
  added.
- **Brand artwork**: the logo is a traced whiteboard drawing of a cat, living in
  `frontend/src/components/brand/` as `BrandMark` (the head knocked out of a
  `bg-primary` tile) and `BrandCaption` (the handwritten "Do task!"). The mark is in
  the sidebar header and on Login; the caption is on Login ONLY, because at the width
  the sidebar header allows it shrinks to an illegible smudge (it is nearly 2:1, so
  always size it by width). The path data in `paths.ts` and in `public/favicon.svg`
  is machine-traced from a photo of the drawing, and the two carry the same artwork
  under the same `MARK_VIEWBOX`: never hand-edit either, and if the artwork is ever
  re-traced, replace both together or the tab icon stops matching the app. The
  tracing pipeline is not kept anywhere; treat the committed paths as the artwork.
  The favicon is the only place the teal is hardcoded, carrying its own
  `prefers-color-scheme` block because a browser tab cannot read the app theme;
  everything in-app goes through `--primary` and so tracks the user's accent. Note
  the sidebar's brand `<Link>` needs its own `aria-label`: in icon mode the wordmark
  is `display:none`, which also drops it from the accessibility tree.
- **PWA**: installable to a phone home screen. `public/manifest.webmanifest`,
  `public/sw.js` and the four PNG icons; `src/pwa.ts` does the registration,
  called from `main.tsx`. Like `theme-init.js`, the two `public/` files are
  outside eslint/tsc (`eslint.config.js` only matches `**/*.{ts,tsx}`), so
  `src/pwaManifest.test.ts` is what guards them. Five things not to undo:
  - **Registration is `import.meta.env.PROD`-only.** A worker in dev intercepts
    the requests Vite's HMR needs and you get stale modules with no clue why. It
    also registers immediately when `document.readyState === 'complete'` rather
    than only on `load`: `main.tsx` is a deferred module, so `load` may already
    have fired, and waiting for it would mean never registering.
  - **`sw.js` must never cache `/api/`** (nor anything non-GET). Those responses
    are authenticated household data and the app has no offline write model, so
    caching them would put personal data on the device for nothing. It also means
    logging out leaves nothing behind. Bump `CACHE` when editing the worker, but
    note that does not prune anything on an ordinary deploy: the worker is
    byte-identical across them, so none activates and each deploy's hashed
    `/assets/` accumulate, which is left to the browser's storage eviction.
    `src/serviceWorker.test.ts` runs the worker in a `node:vm` sandbox against a
    fake `self` rather than grepping its source, so these rules are enforced;
    only a 200, non-redirected, `text/html` navigation may become the shell (a
    502 from the proxy mid-deploy resolves normally and would otherwise be pinned
    as the offline shell). When adding a rule there, **delete it and check the
    test actually fails**: a request shape matching no branch (say a `no-cors`
    `/api/` GET) falls through whether or not the guard exists, so a test built
    on one asserts the fall-through and pins nothing. Give it a shape that
    reaches a branch which does intercept.
  - **The maskable icon needs MORE padding than the favicon, not less.** Android
    crops it to the launcher's shape and only guarantees the inner ~80%, so it is
    a full-bleed teal square with the head at ~75% width, while the `any` icons
    keep the tight rounded-tile crop. iOS ignores manifest icons entirely and
    uses `apple-touch-icon.png`, which must be opaque (transparency renders
    black) and square (iOS applies its own squircle).
  - **nginx (`nginx-common.conf`) uses `expires -1` for `/sw.js`, not
    `add_header Cache-Control`**: nginx *replaces* inherited `add_header`
    directives instead of merging, so an `add_header` there silently drops the
    CSP and the four other security headers from that response. For the same
    reason the manifest's type comes from `default_type` in its own `location`,
    not a `types` block, which would replace the whole inherited MIME map.
    Without it the manifest is `application/octet-stream`, and `nosniff` then
    makes the browser reject it and the app is not installable.
  - **HTTPS is required**, so this only works in the tls/traefik modes or behind
    a TLS-terminating proxy. No CSP change was needed: `worker-src` and
    `manifest-src` both fall back to `default-src 'self'`.
- **Server-driven tables**: every list view is `DataTable` + `useServerTable`
  (`src/components/data-table/`), TanStack Table in fully manual mode with the
  fetching inside the hook. A column's `id`/`accessorKey` IS the server sort key, so
  it has to match that endpoint's whitelist (`CHORE_SORT_COLUMNS` and friends) or
  sorting breaks silently. Four things not to undo:
  - **State lives in the URL**, and with a `storageKey` also in `localStorage` under
    `isachore-table-<key>` (eight keys; `household-members` is deliberately shared by
    both household edit pages). Storage is read ONCE at mount and what comes back
    *becomes* that mount's defaults, which is the whole trick: it buys "URL wins over
    storage, storage wins over the page's own defaults" with no extra branch and no
    mount-time URL rewrite (which would cost a second fetch and a flicker).
    `deriveState` and `applyOwnedParams` must keep comparing against that same
    `defaults`: each encodes "the default", one as the fallback and one as what to
    omit from the URL, and they have to agree or a value equal to it resolves two
    ways.
  - **The page number is never stored**, only page size / sort / filters, so every
    arrival starts at page 1. A stored page can be out of range after deletions and
    nothing clamps it.
  - **`setSearchParams` does not compose within a tick**: react-router hands the
    updater the current render's params (its own docs say multiple calls "will not
    build on the prior value"), so two `setFilter` calls in one tick both start from
    the same place and the last silently wins. Change several filters through
    `setFilters`. Each setter's early-return guard is also what keeps `loading`
    honest, since `mutate` flips it true and with no URL change there is no request
    and so no `.finally` to flip it back: a test for one of those guards must assert
    `loading`, or it pins nothing.
  - **Stored settings are untrusted**, validated per field (a bad value falls back on
    its own, not all-or-nothing), and a 400/422 response clears that table's key so a
    stored sort the server no longer accepts cannot wedge a page forever. 404 does
    NOT clear, which is why `Tags` prunes a dead `household_id` itself once its
    household list loads: `list_tags` 404s for a household you are not in, and its
    selector is hidden below two households, so nothing on screen could clear it.
    `Chores`, `History` and `Logs` prune too (via latest-value refs, so the options are not
    refetched), though they merely return an empty page. Two wrinkles worth copying if a
    fourth page joins them: History's prune runs on the options request's **failure** path as
    well, because its hidden-bar branch reads no payload and a helper would otherwise keep
    filters applied with no Select on screen to clear them; and `Logs` prunes its `action`
    filter with no network at all, in the same `setFilters` call, since that option list is a
    closed const of ours rather than something a request can teach us. `clearTableSettings()` runs
    on logout because the saved filters name colleagues and households; theme and
    language deliberately survive, being the browser's preferences rather than one
    account's data.
- Import routing from `react-router` (v8), never `react-router-dom`.
- **UI components**: shadcn/ui (radix-nova) live in `frontend/src/components/ui/`,
  config in `components.json`. Import via the `@/` alias and compose classes with
  `cn()` (`@/lib/utils`). Add with `printf 'n\n' | npx shadcn@latest add <name>`
  from `frontend/` (see Gotchas for the `n`). Several primitives are brand
  customised (Button, Input/Textarea, Select trigger, Label + Table headers,
  Monday-first Calendar): keep using them rather than raw HTML, and when one needs
  brand radius/sizing, edit the component itself rather than fighting it with
  per-call classes (see Gotchas).

  **`chart.tsx` is modified too, and for reasons that are not cosmetic**, so it does
  not belong on that list and needs its own note. Two local extensions, neither
  upstream: `ChartStyle`'s `safeId` / `CSS_IDENT` / `SAFE_COLOR` are the sanitiser
  around its `dangerouslySetInnerHTML` (the reason the CSP keeps
  `style-src 'unsafe-inline'`), and `ChartTooltipContent`'s opt-in `hideZero` drops
  zero-valued series from the rows, which a stacked chart needs because recharts
  sends one payload entry per series whatever the value. Losing the first is a
  security regression, so treat re-pulling this file as the higher-risk case, not
  the lower one. Both are pinned by `ui/chart.test.tsx`, and `hideZero` also fails
  `tsc` through its `Statistics.tsx` call site, so a stock overwrite cannot reach
  `main` - but it lands as a CI failure whose cause is several steps from the
  command that caused it, which is exactly why the Gotcha below names it.
- **Theme / dark mode**: `ThemeProvider` + `useTheme()` in `frontend/src/theme/`
  (context/provider/hook split, same rule as `src/auth/`). Light mode is the teal
  brand; dark is derived. The picker is the Profile page's **Appearance** section
  (Catppuccin flavour + accent, saved optimistically with rollback, like
  language), NOT `TopBar`. Toasts: `toast.success(...)` from `sonner`, a single
  `<Toaster />` in `main.tsx`. Feedback pattern: success -> toast, errors ->
  inline text.

  **On a list page that caveat needs help, because "inline" there means a banner above
  the filter bar, and a row action failing on row 90 of 100 reports itself entirely
  off-screen.** The answer is not a toast, which forks the convention and would leave two
  actions on one page behaving differently; it is to make the banner reach the user:
  `role="alert"` on the paragraph, plus `scrollIntoView({ block: 'nearest' })` in an
  effect keyed on the error (a no-op when it is already visible, and setState-free so it
  is exempt from the no-setState-in-effect rule). `Chores.tsx` does this, because clone is
  the one row action that can fail on the way *out* rather than from inside a confirmation
  dialog the user is already looking at. The same banner sits on `Tags`, `Households`,
  `History`, `Home`, `Unscheduled` and both admin tables, all with row actions that can
  fail, and none of them do this yet - lift the ref-plus-effect if you touch one, or sweep
  the lot into a shared component. A form's inline error needs none of this: it sits
  beside the button that was just pressed.
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
    names, the 14 accent colour names, and the handwritten `BrandCaption`
    ("Do task!") since it is artwork rather than a string.
  - Gotcha: a handler closure captures the render-time `t`, so a toast fired right
    after switching language would show the OLD language. The Profile
    language-save success toast reads via the `i18n` singleton (`i18n.t(...)`) so
    it confirms in the just-selected language; rollback/error paths keep the
    closure `t`.
- Pages in `frontend/src/pages/`, one component per route.

## Verification

Tests live in `backend/tests/` (pytest) and alongside the code as
`frontend/src/**/*.test.{ts,tsx}` (vitest). Mirror the existing patterns; cover
the negative paths (401/403/400/404/409), not just the happy one.

- **A test for one clause of a compound condition must satisfy every other
  clause**, or it asserts a fall-through and pins nothing. This has now cost real
  work three times: the `sw.js` note below (a request shape matching no branch
  falls through whether or not the guard exists), `useServerTable`'s early-return
  guards (no URL change means no refetch either way, so only asserting `loading`
  catches a missing guard), and the chore form's assignee picker (a test that
  switched strategy with an *empty* assignee pool proved nothing about the
  strategy gate, since the empty pool hides the picker by itself). When adding a
  test for a guard, delete the guard and watch the test fail.

  Make that four times. The rich text toolbar's `useEditorState` took three
  attempts to pin, because the obvious tests all pass without it: Tiptap v3's React
  binding is non-reactive, so `editor.isActive()` read from render is stale, but the
  staleness is invisible whenever the **document** changes, since `onUpdate` makes the
  caller re-render and recompute the stale read by accident. Asserting `aria-pressed`
  after an edit proves nothing; toggling a mark at a collapsed caret fires `onUpdate`
  too. Only a pure selection move is document-free, and jsdom refuses arrow keys
  outright ("Not implemented. The result of this interaction is unreliable."), so the
  test drives `setTextSelection` through a harness that owns the editor.

- **Contenteditable is the one thing jsdom cannot drive**, which is why
  `src/test/richTextEditorMock.tsx` exists and is the **only** `vi.mock` in the repo.
  Page tests about a *form* swap the editor for a textarea with the same contract
  (same accessible name via `labelledBy`, value in, string out), which is what keeps
  `getByLabelText('Description')` and `toHaveValue(...)` working. The real editor is
  covered in `RichTextEditor.test.tsx`, which works around jsdom by driving commands
  instead of keys; it needs `Range.prototype.getClientRects`,
  `getBoundingClientRect` and `document.elementFromPoint` stubbed in `test/setup.ts`
  (ProseMirror hit-tests a click through the last one and jsdom throws), and it
  focuses the editable rather than clicking into it.

- **Backend**: `docker compose exec backend uv run pytest` (in the container so
  `db` resolves). Fixtures spin up a throwaway `isachore_test` DB and roll each
  test back via a SAVEPOINT; build cases with `client` / `make_user` /
  `auth_client` from `tests/conftest.py`. Note the schema comes from
  `Base.metadata.create_all`, so **pytest never executes a migration**: a broken
  chain passes both suites. `ci.yml`'s "Migrations build an empty database" step is
  the only guard. After touching `alembic/`, run it by hand against a scratch DB:
  `docker compose exec db psql -U isachore -d postgres -c 'CREATE DATABASE scratch'`
  then `docker compose exec -e DATABASE_URL=postgresql+asyncpg://isachore:<pw>@db:5432/scratch backend alembic upgrade head`. Redis is faked with `fakeredis` (the
  `fake_redis` fixture overrides `get_redis`); tune the login throttle per-test by
  monkeypatching `settings.login_*`. Coverage: add
  `--cov=app --cov-report=term-missing --cov-report=html` (report at
  `backend/htmlcov/`).
- **Single sign-on is tested in two halves, and needs an autouse reset.** `_reset_oidc`
  in `conftest.py` clears the OIDC settings and `oidc_core.reset_caches()` before every
  test, mirroring `_reset_smtp` / `_reset_app_key` and for the same reason: pytest runs
  inside the dev container with `env_file: .env`, so uncommenting the OIDC block to try the
  flow by hand would otherwise turn the button on for every test and make
  `POST /auth/login` 403. The opt-in `oidc` fixture configures a provider, over https so that
  a case pinning a non-dev environment cannot trip the plaintext-issuer refusal (the
  startup-check tests build their own config, since they call `check_startup_config()`
  directly). The cache clear is the other half - discovery documents are memoised per issuer,
  and one test's must not be served to the next.
  - The **policy** half stubs `oidc_core.begin` / `oidc_core.complete`, so no provider is
    involved. The **verification** half does the opposite: real RSA keys, real signed
    tokens, real `_verify_id_token`, stubbing only the key fetch. Do not collapse them -
    without the second, every signature check in the feature is mocked out, and that
    function is the only thing between a stranger and a session.
  - **Every guard reachable from a test was mutation-checked** (delete it, watch a test fail):
    the state cookie comparison, the
    issuer half of the identity lookup, the `already_linked` takeover guard, the
    disabled-account refusal, the open-redirect guard on `return_to` including its length
    clause, the algorithm allowlist and its non-list guard, the non-object claims guard, both
    `azp` rules, `build_identity`'s same-source selection, the identity length guard, the
    provider-name normalisation, both throttles, `clear_login_throttle`'s prefixes, the
    confirmation-token revocation, and `OIDC_ONLY`'s second clause. The exception, and it is
    the interesting one: **`_client()` is never executed by either suite**, so it is the one
    place PKCE is actually requested from authlib and an argument rename there would ship
    green. That is a by-hand check, like the boot migration.

    **The mutation has to be as narrow as the guard, and getting that wrong hid two holes
    here.** Replacing `if not state or not cookie or not compare_digest(state, cookie)` with
    `if not state` fails a test, so the guard looks pinned - but it deleted *three* clauses,
    and the test that failed only needed the first. Dropping the `compare_digest` alone left
    the whole suite green, because the one test aimed at it deleted the cookie (satisfying
    `not cookie` instead) and the other passed a state matching no row (satisfying the
    lookup). Same story for `User.oidc_issuer == identity.issuer`. Both now have a test that
    satisfies every *other* clause deliberately: two concurrent flows for the comparison, and
    a same-subject-different-issuer collision for the lookup. When you mutation-check
    something, change exactly one clause.

    One guard did NOT survive the check and was removed rather than kept: a `.catch` that
    reset `methods` to password-only on a failed probe in `Login.tsx`. It was unobservable,
    because the pre-load state already read as password-only, so the fallback is now the
    `useState` default and there is no branch to pin. Seeding that default is what the tests
    actually hold.
  - **The dev stack ships no identity provider, deliberately** - trying the flow by hand
    means pointing `.env` at a real one. When you do, the trap that costs the most time is
    that the browser and the backend must reach it at the *same* url, or `iss` disagrees
    with `OIDC_ISSUER` and every sign-in fails verification with a message that does not
    say so. `localhost` cannot be that url: inside the backend container it is the backend.
    Check it before debugging anything else - fetch
    `<issuer>/.well-known/openid-configuration` from the host and from inside the backend
    container and compare `issuer`; they must be byte-identical.
- **Pin the clock with `app.core.clock.now`, and patch the module attribute.** The endpoints
  call `clock.now()` rather than importing the name precisely so `monkeypatch.setattr(clock,
  "now", ...)` reaches them; `from app.core.clock import now` in a caller would defeat it. The
  pure helpers in `core/chores.py` take `now` as a parameter and need no seam.
  `tests/test_timezones.py` is where day-boundary behaviour lives, and it carries two
  conventions worth copying: extreme zones (`Pacific/Kiritimati` +14, `Pacific/Niue` -11) over
  plausible ones, because they straddle UTC and so fail loudly if a zone is dropped; and every
  household fixture defaulting to `timezone="UTC"`, which is what keeps several hundred
  pre-timezone due assertions elsewhere in the suite meaning what they used to.

  **Two traps this cost real time on, both instances of the "satisfy every other clause" rule
  above.** First, the obvious regression test for the reported bug pins *nothing*: asserting
  "at 01:30 in Amsterdam the chore reads as due today" passes even with the comparison reverted
  to UTC, because the slot sits at 22:00Z and the clock at 23:30Z, so both shift by the same two
  hours and the difference between two dates survives. A zone only changes the answer where
  exactly *one* operand crosses midnight - 23:00 local is such a moment, and
  `test_home_uses_the_household_day_late_in_the_evening` is the test that actually fails when
  the zone is dropped. Second, `end - start` on two aware datetimes **sharing a tzinfo** ignores
  the zone entirely and subtracts wall-clock fields, so "this DST day is 25 hours long" is a
  constant 24 unless both sides are `.astimezone(UTC)`'d first.
- **`chore_occurrences.updated_at` has its own revision** (`c8d5e21a473f`), deliberately not
  bundled with the timezone work even though `d7a3f81c62b4` already rewrites that table: an
  operator rolling the timezone feature back should not have to drop an unrelated column to do
  it. It is added nullable, backfilled from `created_at`, then set NOT NULL with a `now()`
  default - three statements rather than one `ADD COLUMN ... NOT NULL DEFAULT now()`, because
  `now()` is volatile and so forfeits Postgres's metadata-only fast path, making that one-liner
  two full table rewrites instead of one.
- **The zone-change / completion race is by-hand-only, and there is a way to drive it.** The
  savepoint fixtures give each test one connection inside a rolled-back savepoint, so two
  concurrent transactions never exist - the same limit as `create_invitation`'s advisory lock. To
  check it for real, write a throwaway script that builds its own household, chore and open
  occurrence, then `asyncio.gather`s two `async_session_factory()` sessions: one calling
  `apply_timezone_change` and sleeping before it commits, the other calling `_close_occurrence`
  partway through that sleep. Assert `completed_timezone` matches the household's zone afterwards
  and that the successor sits on local midnight. Run it against the reverted code first - it must
  fail - and have it clean up after itself so the dev database is left as it was.

  What *is* reachable here is the half that makes the fix work: both operands are read after the
  lock rather than taken from the preloaded objects. `update(...)` with
  `execution_options(synchronize_session=False)` stands in for the concurrent transaction, and
  that option is load-bearing - the default ORM-enabled UPDATE writes the new value onto the
  loaded object too, so the test would pass on the old code. Both tests assert the object is
  still stale before closing, for exactly that reason.
- **`chore_occurrences.updated_at` cannot be observed moving under the fixtures.** Both its
  defaults are SQL `now()`, which is `transaction_timestamp()` and so frozen for the whole
  savepoint-wrapped test; in production each request is its own transaction. The suite pins the
  column's configuration instead, and the elapsed behaviour is a by-hand check (complete a
  chore on the dev stack, then compare the two columns).
- **The boot migration is shell, so neither suite reaches it.** After touching
  `backend/docker-entrypoint.sh` or either `ENTRYPOINT`, verify by hand:
  `docker compose down -v && docker compose up -d --build backend`, then
  `docker compose logs backend | grep entrypoint:` and
  `docker compose exec db psql -U isachore -d isachore -c 'SELECT version_num FROM alembic_version'`
  (non-empty). Check both other paths too, which are the ones easy to break:
  `docker compose run --rm -e RUN_MIGRATIONS=false backend uvicorn --version` must
  log the skip (the gate matches, then `--version` exits at once), and after
  `docker compose stop db`,
  `docker compose run --rm --no-deps backend python -m app.cli generate-key` must
  still print a key with no database at all. Note the opt-out only reaches the
  container through `.env`: the backend block has just `env_file`, so a bare
  `RUN_MIGRATIONS=false docker compose up` is silently ignored.
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
- **The Dockerfiles own the toolchain versions.** CI installs python, uv and node
  on the runner rather than running the suites inside the images, but it `sed`s the
  versions out of `docker/*.Dockerfile` instead of restating them, so a base-image
  bump reaches CI on its own. Do not reintroduce a literal pin in `ci.yml`: it used
  to have them, and a Dependabot bump to `python:3.14-slim` left CI testing 3.13
  while the published image shipped 3.14. `backend/.python-version` is the one
  remaining mirror, since uv obeys it and a mismatch means `uv run` finds no
  interpreter inside the image; CI asserts it matches.
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
  an eslint override for `src/components/ui/**` permits that, so leave their *export*
  shape alone (this is about what a file exports, not a ban on editing `ui/**` - see
  UI components above for the primitives that are deliberately modified).
- Adding a shadcn component re-pulls its registry deps and offers to overwrite files
  it thinks it owns, `button.tsx` and `chart.tsx` among them: always decline
  (`printf 'n\n' | npx shadcn@latest add <name>`), then double-install if
  `package.json` changed (host + `docker compose exec frontend npm install`). The
  two decline for different reasons and `chart.tsx` is the one to be careful about:
  `button.tsx` holds brand styling, while `chart.tsx` holds the CSS sanitiser around
  its `dangerouslySetInnerHTML` plus the `hideZero` tooltip behaviour (see UI
  components above). `ui/chart.test.tsx` and `tsc` both fail if either is dropped,
  so it cannot merge, but the failure reads nothing like "you accepted an overwrite":
  reflexively hitting `y` here costs an afternoon. The radix-nova style ships
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
