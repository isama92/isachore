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
    (Home, Chores, History, Statistics) scopes through `member_household_ids` and
    simply returns nothing. Note the `noHouseholds` states are now unreachable through
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

  Capabilities: every role completes chores (scheduled and unscheduled) and reads
  the household list; deputy adds History and Statistics; organiser adds chore and tag
  management, plus inviting and setting deputy/helper roles. Nine things to keep
  straight:
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
  - **Reads narrow, writes 403** ("union for nav, scope the data"). Home, History,
    Statistics and the chores list each span every household, so they take
    `member_household_ids(user_id, min_role)` and return *less data* rather than
    refusing: a deputy in one household and a helper in another gets the first one's
    history and never learns the second has any. Mutations go through `require_role`,
    which 403s, because the caller can see the resource elsewhere and a 404 would be a
    lie. `GET /chores/{id}` is ungated on purpose (the description dialog on Home and
    Unscheduled needs it for helpers), which is why the chores router has both
    `_get_user_chore_or_404` and `_managed_chore_or_error`. **Because that read is open,
    `ChoreRead.assignees` and `.current_assignee` are `HouseholdMemberRead`, never
    `UserRead`.** They used to be the latter, which handed a helper their housemates'
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
    narrowing it would empty the pickers on the one page a helper does have. History and
    Statistics filter its `households` client-side instead.
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
    is `MeRead`) and `/verify-2fa`. Login sets the client's auth state directly rather
    than refetching, so without that the first screen after signing in would render the
    minimal nav. The frontend holds them as `memberships` on the auth context (a sibling
    of `impersonating`, same reasoning: not a property of the user account) and reads
    them only through `lib/permissions.ts`. They are **advisory**: the API re-checks on
    every request, so a stale copy shows or hides the wrong nav item until the next
    `/auth/me` and grants nothing.
  - **Anything that changes the caller's OWN memberships must `refresh()`.** The context
    is populated at login and never refetched on its own, so all four handlers that move
    the caller in or out of a household re-read `/auth/me`: `HouseholdCreate` (creating
    one makes you its organiser), `AcceptInvite` (joining makes you a helper),
    `HouseholdEdit`'s `leave()` and `Households`' delete (a soft-deleted household drops
    out of `memberships_for`). Gaining one is the loud direction: a brand-new account
    creates its first household - the documented first step for every new user - and
    without the re-read still sees the no-household sidebar, with every management page
    bouncing off `RequireRole` until they reload by hand. Losing one is quieter but not
    harmless: the sidebar keeps offering what that household granted, and Tags then 404s
    with nothing on screen able to clear it, since no stored filter is at fault. Each of
    the four is pinned by a test that fails when the `refresh()` is removed.
  - **`RequireRole` cannot decide anything per household**, only "reaches the role
    somewhere", because the pages behind it span all of them. A page acting on one
    specific household needs its own check where the API would let it get that far:
    `ChoreEdit` does one and leaves for the list otherwise, since `GET /chores/{id}` is
    open to every role, while `TagEdit` needs none because `GET /tags/{id}` 403s by
    itself. `HouseholdMembersTable` keeps its role props (`viewerUnrestricted`,
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
- **Impersonation**: `POST /users/{id}/impersonate` swaps the session cookie to
  the target user and parks the admin's own token in the `isachore_admin_token`
  cookie; `POST /auth/stop-impersonating` restores it. `/auth/me` reports
  `impersonating`; logout ends both sessions.
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
    occurrence opens at creation time instead (`_initial_slot`). The schema layer keeps
    this true from both directions (`_normalised_schedule`): the date is silently
    dropped for `manual` and **required** for every other period, the one part of the
    schedule rejected rather than normalised. So a NULL `start_date` and `repeats ==
    manual` are the same fact, and `ChoreForm` hides the field, submits `null`, and
    refills it with today when the period stops being unscheduled.
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
    - Every re-dated slot goes through `_free_slot_from`, which walks it past any slot the
      chore has **already completed**. `first_occurrence` and every grid slot are both
      midnight UTC, so re-dating onto a grid the chore has history on can land exactly on a
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
    `ChoreRow` (Home and Unscheduled). Those two lists carry `has_description: bool`, **not**
    the HTML - the dialog fetches `GET /chores/{id}` on open, so a household's instructions
    never ride along on the landing page. `RichText` is the only
    `dangerouslySetInnerHTML` outside `ui/chart.tsx`, and it is NOT a sanitiser: only ever
    pass it something the server has already cleaned.
  - `ChoreCreate` and `ChoreEdit` are `lazy()` in `App.tsx` for the same reason Statistics is:
    they are the only routes reaching `ChoreForm`, and that chunk is ~146 kB gzipped. A third page
    rendering `ChoreForm` needs splitting too, or the editor lands back in the main chunk.
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
    `isachore-table-<key>` (seven keys; `household-members` is deliberately shared by
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
    `Chores` and `History` prune too (via latest-value refs, so the options are not
    refetched), though they merely return an empty page. `clearTableSettings()` runs
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
- **Theme / dark mode**: `ThemeProvider` + `useTheme()` in `frontend/src/theme/`
  (context/provider/hook split, same rule as `src/auth/`). Light mode is the teal
  brand; dark is derived. The picker is the Profile page's **Appearance** section
  (Catppuccin flavour + accent, saved optimistically with rollback, like
  language), NOT `TopBar`. Toasts: `toast.success(...)` from `sonner`, a single
  `<Toaster />` in `main.tsx`. Feedback pattern: success -> toast, errors ->
  inline text.
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
