# Households, roles and the household log

## Nothing provisions a household

Not `POST /admin/users`, not `cli init`, not confirming an account. A new user — the
bootstrap admin included — starts a member of none and creates their own through
`POST /households` (open to any authenticated user) or accepts an invitation.

Do not reintroduce an automatic one anywhere, including the confirmation flow. It was
removed because it left every account owning a household it never asked for. `seed` is the
exception, building its own solo plus shared households, and is the only remaining consumer
of `personal_household_name` (`app/core/households.py`).

**Zero households is a normal, reachable state** — the state every fresh install and every
new account begins in. Nothing may assume a user has any household, let alone exactly one,
and leaving or deleting the last one is allowed.

`Households` has a first-run empty state. The three pages carrying `noHouseholds` copy do so
for two different reasons, so do not treat them as one guard:

| Page | Why |
|---|---|
| `Tags` | Its list call omits `household_id` and so hits `get_current_household` (`api/deps.py`), which 404s for a member of none — the only endpoint that hard-fails. |
| `ChoreCreate`, `TagCreate` | Their forms have no `household_id` to submit at all. |

Everything else (Home, Chores, History, Statistics, Logs) scopes through
`member_household_ids` (or `owned_household_ids`) and simply returns nothing. The
`noHouseholds` states are unreachable through the *sidebar* — a member of none reaches no
role, so `RequireRole` sends them to Home — but are kept because the guard is client-side
and the URLs still work.

**Do not seed a household in a migration:** `households.admin_id` is NOT NULL, so a
household cannot exist before its owner, and an owner-less row is what used to make
`alembic upgrade head` unrunnable on an empty database.

## The role ladder

`household_members.role` is a `varchar(30)` with a `HouseholdRole` StrEnum on the backend
only (`models/household.py`) — the same String-column pattern as `users.status`, so adding a
role needs no migration.

organiser > deputy > helper. `_ROLE_LADDER` / `roles_at_least` in `app/core/households.py`
is the ONLY place that ordering is written down on the backend; on the frontend it is the
order of the `HOUSEHOLD_ROLES` tuple in `lib/types.ts` (strongest first), which
`lib/permissions.ts` derives its ranks from. A role added to the enum but missing from
`_ROLE_LADDER` satisfies no predicate at all, which `test_every_role_is_on_the_ladder` pins.

**"No migration" is about ADDING a role. Removing a rung needs a data migration before the
deploy**, and the two failure modes are nothing alike:

- **Off the ladder** fails quietly, as above.
- **Not in the enum at all** fails hard. Three places coerce the raw string:
  `role_in_household` and `memberships_for` (`core/households.py`), and
  `build_members_page` (`api/v1/households.py`); `HouseholdRole('guest')` raises
  `ValueError`. Measured with one hand-edited row: that member's `/auth/me` **and**
  `POST /auth/login` both 500, so they are locked out rather than degraded, and
  `GET /households/{id}/members` 500s for **every housemate** and for site admins on
  Admin > Households. `/home` and `/unscheduled` survive, because `member_household_ids`
  compares in SQL (`role IN (...)`) and never coerces.

The 422 at the schema layer keeps this unreachable through the API, so it is operator error
— but it is not contained to whoever holds the row.

### Capabilities

| Capability | helper | deputy | organiser | owner |
|---|:--:|:--:|:--:|:--:|
| Complete chores (scheduled and unscheduled) | ✓ | ✓ | ✓ | ✓ |
| Read the household list | ✓ | ✓ | ✓ | ✓ |
| See and undo **their own** closures on History | ✓ | ✓ | ✓ | ✓ |
| The whole household's History, plus Statistics | | ✓ | ✓ | ✓ |
| Chore and tag management | | | ✓ | ✓ |
| Undo *anybody's* closure | | | ✓ | ✓ |
| Invite, and set deputy/helper roles | | | ✓ | ✓ |
| Rename, delete, remove members, transfer | | | | ✓ |
| Logs | | | | ✓ |

Ownership is **not** a rung: Logs (`api/v1/logs.py`) is the only surface gated on `admin_id`
rather than on the ladder.

## Ownership and role overlap on purpose; the owner always wins

Ownership stays `households.admin_id`. The owner is by definition an organiser: their role
is not editable (409 from the member PATCH), and `set_household_admin` *promotes the new
owner* as part of the transfer. Drop that promotion and handing the household to a helper
leaves them owning something they cannot manage the chores of, with no way to fix it,
because the role endpoint refuses to touch the owner's row.

Owner-only: renaming, deleting, removing members, transferring. Organiser-level: inviting
and role-setting (`_get_organised_household`).

**The one asymmetry:** an organiser may move people between deputy and helper but may not
hand out `organiser` or touch a row already holding it. So they cannot grow the set of
people who could demote them, and cannot demote themselves — which falls out of the same
rule rather than needing its own check.

`update_household_member` orders its checks deliberately: the owner's row 409s *before* any
caller rule, because "the owner is always an organiser" is a property of the target, so
every caller gets the same actionable answer.

`assignableRoles` in `frontend/src/lib/permissions.ts` is the frontend's single mirror of
all of it; returning `[]` there is what renders a badge. Its organiser branch derives its
options from `HOUSEHOLD_ROLES` rather than listing them, because the backend states the same
rule as a negation and a new role would otherwise be accepted by the API but missing from an
organiser's Select.

### Invitations are per household, not per inviter

Every organiser sees and can revoke the whole list, and `MAX_PENDING_INVITATIONS` is a
shared budget. That count is a read-decide-write with no constraint behind it, and widening
the endpoint from one inviter to several made the race reachable — **12 parallel POSTs
landed 11 invitations against a cap of 5**. So `create_invitation` takes
`pg_advisory_xact_lock(household_id)` first: transaction-scoped, keyed per household, and
only ever after `_get_organised_household`.

**The suite cannot cover it.** The fixtures give each test one connection inside a
rolled-back savepoint, so two concurrent sessions never exist. Verify by hand with parallel
`curl`, like the boot migration.

`Households`' row action follows the same widening — the pencil is
`owned || hasRoleIn(..., 'organiser')`, because an eye labelled "View" hid a page organisers
now have real work on.

Setting a role goes through a confirmation, and that dialog is **controlled and rendered
once for the table**, unlike every other AlertDialog in the app: a Select's `onValueChange`
is not a trigger click, so there is nothing for an `AlertDialogTrigger` to wrap and no
per-row uncontrolled dialog to use. Cancelling needs no revert because the Select is
controlled by `member.role`, which never moved.

## Reads narrow, writes 403

"Union for nav, scope the data." Home, Statistics, Logs and the chores list each span every
household, so they take `member_household_ids(user_id, min_role)` (or `owned_household_ids`
for Logs) and return *less data* rather than refusing: a deputy in one household and a
helper in another gets the first one's statistics and never learns the second has any.

**History is the exception that combines two scopes rather than picking one:** an `or_` of
the deputy scope and the plain membership scope restricted to
`completed_by_user_id == caller`, so the same page shows everything in one household and
only your own rows in another. It is unconditional in the sidebar for that reason — there is
no rung to gate it on. The `or_` lives in the shared `filters` list so `total` narrows with
the rows; narrowing only the page query would make the pager offer pages that come back
empty.

Mutations go through `require_role`, which 403s, because the caller can see the resource
elsewhere and a 404 would be a lie.

**`undo_completion` is the one write that hand-raises instead**, because its rule is a
disjunction (the recorded completer, OR an organiser of that household) and `require_role`'s
"Only household organisers can do this" would deny the deputy who recorded the closure. Its
404 boundary is plain membership, not the deputy scope: a helper reaches History for their
own rows, so a 404 on a row they can see would be exactly the lie this rule warns about. The
owner passes on their membership row, which a transfer always promotes — never on `admin_id`,
which that endpoint deliberately does not read.

One documented stretch: a helper targeting a housemate's row gets the 403 even though they
cannot see that row anywhere, which makes it a weak existence oracle inside their own
household. Accepted; nothing in the response body is personal data.

`GET /chores/{id}` is ungated on purpose (the description dialog on Home and Unscheduled
needs it for helpers), which is why the chores router has both `_get_user_chore_or_404` and
`_managed_chore_or_error`.

**Because that detail read is open, `ChoreRead.assignees` and `.current_assignee` are
`HouseholdMemberRead`, never `UserRead`.** They used to be the latter, which handed a helper
their housemates' email addresses; `ChoreRead` was the only route exposing a `UserRead` to a
household peer at all, which is why `main.py`'s avatar accepted-risk note can now leave peers
out of the holder set. Keep any new payload a household peer can reach off `UserRead`, or
that reasoning stops holding.

The whole tags router is gated on reads too, because no view a non-organiser reaches offers a
tag to pick or filter by — but that is about the *surface*, not secrecy: `ChoreRead.tags`
still reaches any member through the open chore read, so do not restate the gate as "tag
names are hidden".

### `GET /completions/filters` is deliberately not role-narrowed

It also feeds the Home and Unscheduled filter bars (`useFilterOptions.ts`), which every role
uses, so narrowing it would empty those pickers. Three pages reuse it and narrow
client-side: Statistics and Logs filter its `households` (by role and by *ownership*
respectively); History deliberately stopped narrowing at all, since a helper household is
now a live option that yields the caller's own rows. History hides its whole filter bar
instead when the caller reaches deputy nowhere, since their own closures are already the
entire list.

The known dead end all three share: the member list spans every household the caller belongs
to, with no member -> household association to narrow it by, so a person plus a household
that do not pair yields an empty page. Nothing leaks — those names are on Home already.

**Never read a filter's value as a proxy for how much is in scope.** Every household
`Select` renders only *above one option* (`options.households.length > 1` on Statistics, the
same on Tags), so for the single-household user the control never renders and its filter
state can never leave `''`. A conditional written as "is a household selected?" answers "no"
forever for exactly the people it was meant to help. Statistics' most-skipped card shipped
this bug: it hid the per-row household line when a household was picked, which for a deputy
of one household meant the same name on every row. The fix is to ask the *data*
(`new Set(rows.map(r => r.household_name)).size > 1`), which needs no filter, no options
list, and also covers a deputy of three households where only one has rows.

## Members

**`add_member` takes a required role, and the column's `server_default` is `helper`.**
`household_members` is a Core `Table`, so the `members` relationship inserts the two foreign
keys only and would leave any bypassing path on the default. That default is the weakest role
for exactly that reason. `db/seed.py` and `tests/conftest.py` both used the relationship and
were converted; do not put it back.

**`conftest.make_household` defaults every member to `organiser`.** Load-bearing: before
roles, membership granted everything, so that default keeps the chores / tags / stats /
history suites testing their own subjects instead of several hundred assertions about 403s.
Role tests pass `roles={user.id: ...}`.

**`HouseholdMemberRoleRead` is a subclass, used by the two members endpoints alone.**
`HouseholdMemberRead` is shared by six other payloads (assignees on Home, Unscheduled and the
chore reads, History's `completed_by`, the filter options, an invitation's `invited_by`), none
of which join a membership row, so `role` on the base would either leak into all of them or
fail validation. `build_members_page` selects `household_members.c.role` alongside `User`.
Same split on the frontend: `HouseholdMemberWithRole`, not a field on `HouseholdMember`.

Note "dropped from the pool" is narrower than "left the household": `remove_member` deletes
the `household_members` row alone and prunes no `chore_assignees`, so somebody who leaves
stays in `chore.assignees` and keeps being picked. Pre-existing and out of scope.

## Memberships on the auth context

**Every response carrying the signed-in user carries their memberships**, via `_me_read` in
`api/v1/auth.py`: `/auth/me`, the login response (`LoginResponse.user` is `MeRead`) and
`/verify-2fa`. Each is `(household_id, role, owned)` — `memberships_for` returns a
`Membership` NamedTuple, and `owned` costs no query because `Household` is already joined for
the `deleted_at` filter. `owned` is a separate fact from the ladder rather than a rung on it,
and is the only thing Logs is gated on.

Login sets the client's auth state directly rather than refetching, so without this the first
screen after signing in would render the minimal nav. The frontend holds them as `memberships`
on the auth context (a sibling of `impersonating`, same reasoning: not a property of the user
account) and reads them only through `lib/permissions.ts`. They are **advisory**: the API
re-checks every request, so a stale copy shows or hides the wrong nav item until the next
`/auth/me` and grants nothing.

### Anything changing the caller's OWN memberships must `refresh()`

The context is populated at login and never refetched on its own, so all five handlers that
move the caller in or out of a household — or change what they hold in one — re-read
`/auth/me`:

1. `HouseholdCreate` (creating one makes you its organiser)
2. `AcceptInvite` (joining makes you a helper)
3. `HouseholdEdit`'s `leave()`
4. `Households`' delete (a soft-deleted household drops out of `memberships_for`)
5. **Both `HouseholdOwnerSelect` call sites** (`HouseholdEdit` and its admin twin), since a
   transfer drops the caller's `owned`

Gaining one is the loud direction: a brand-new account creates its first household — the
documented first step for every new user — and without the re-read still sees the
no-household sidebar, with every management page bouncing off `RequireRole` until they
reload by hand. Losing one is quieter but not harmless: the sidebar keeps offering what that
household granted, and Tags then 404s with nothing on screen able to clear it, since no
stored filter is at fault. The transfer case was missing until Logs existed, because until
then no nav item moved on a transfer.

Each of the five is pinned by a test that fails when the `refresh()` is removed.

`Households.tsx` and both edit pages still read ownership from the household row's `admin_id`
rather than from `owned`: they hold the authoritative value, and Admin > Households renders
households the operator has no membership in at all. Not duplication to collapse.

## The three guards

`RequireRole` **cannot decide anything per household**, only "reaches the role somewhere",
because the pages behind it span all of them. A page acting on one specific household needs
its own check where the API would let it get that far:

- `ChoreEdit` does one and leaves for the list otherwise, since `GET /chores/{id}` is open to
  every role.
- `TagEdit` needs none, because `GET /tags/{id}` 403s by itself.
- History's undo cell is the first that decides a *control* rather than a redirect:
  `hasRoleIn(memberships, entry.household.id, 'organiser')`, mirroring the API's disjunction
  row by row.

**`RequireOwner` is a third guard, not a rung on this one.** Ownership is off the ladder, so
a pseudo-`min="owner"` would put "owner" into `HOUSEHOLD_ROLES`, and from there into a role
picker and a PATCH the API rejects. Three guards, three different facts: a server-wide flag,
a rung somewhere, `admin_id` somewhere.

`HouseholdMembersTable` keeps its role props (`viewerUnrestricted`, `viewerRole`) separate
from `canManage` rather than folding them together, because they govern different endpoints.
Both default to "nobody", which keeps a deputy or helper's view read-only without passing
anything. `viewerUnrestricted` is named for the capability rather than for ownership because
two different people hold it: the household owner, and a site admin on Admin > Households,
who reaches the same reach through `PATCH /admin/households/{id}/members/{user_id}`.

Both member-role routes go through the shared `set_member_role`, so the owner-row 409 and the
disabled-member 404 are written once. `refuse_owner_row` is called separately by the
user-surface handler as well, because *where* it fires decides whether an organiser targeting
the owner hears about the target or about themselves.

`HouseholdEdit` is a three-way page: owner edits the household, organiser shares the people
work (roles plus invitations) on a read-only household, deputy and helper read everything.

## The household log

`household_log_entries`, `core/household_log.py`, `api/v1/logs.py`, `pages/Logs.tsx`: who
changed what in one household's chore management, plus who undid a closure, read by that
household's **owner** alone.

Deliberately NOT `audit_events`, which is the operator trail for auth / 2FA / admin user
management: that one keys its action off a native `audit_action` enum, so a new value needs
an `ALTER TYPE` (which is why `cli.py` reuses `user_updated` rather than adding one), and it
carries `ip_address`, which must never reach a household surface.

### The wire carries strings, not enums

`action` is a `String(50)` with a `HouseholdLogAction` StrEnum supplying the values — the
same pattern as `household_members.role` and `users.status`, so a new action needs no
migration. `test_the_action_column_holds_every_action` is what pins that.

`action` and `changed_fields` go over the wire as plain **strings**, not the enum and not a
Literal union: coercing them back would raise on a row a newer release wrote, i.e. an
unfilterable 500 on every page holding one. The closed set lives on the client (`LOG_ACTIONS`
/ `LOG_FIELDS` in `lib/types.ts`) and `lib/logs.ts` degrades an unknown value to a readable
form. Those two tuples are hand-mirrors of `HouseholdLogAction` and `CHORE_LOG_FIELDS` with
nothing checking them, like `HOUSEHOLD_ROLES` and `users.language`: keep them in step by
hand. The enum still guards the `action` query *parameter*, where a 422 is right.

### Undo is two actions, not one with a flag

Undoing a completion and undoing a skip read completely differently to whoever is looking,
and nothing downstream re-derives which it was — the flag is cleared by the reopen itself.

**`target_user_id` is the other half of that.** `Logs.tsx` renders it as a muted suffix on
the action cell ("Completion undone - recorded by Jo Ng"): without it a row says somebody
undid something and never whose work went, which is the entire reason an undo is logged
separately from the closure it erased. A suffix rather than a column because only those two
of five actions carry a target. The filter beside it is the **actor**, hence "Changed by"
rather than "Person".

### The log holds no reference to the occurrence, and cannot

`undo_completion` has two branches and each defeats a different `ondelete`: reopening nulls
the row's title, completer and completion time in place, so a surviving FK points at
something that no longer describes the closure; the older-closure branch hard-deletes the
row, so RESTRICT would 500 a working feature and CASCADE would let an append-only log erase
itself.

So the handler captures `chore_id`, `title`, `completed_by_user_id` and `skipped` into locals
**before** the branch and writes from those alone. `chore_id` is `SET NULL` for a related
reason: CASCADE would let the log delete its own rows, and RESTRICT would break a hard
household delete, which cascades into `chores` in an order Postgres does not guarantee
against this table's own CASCADE. Nothing hard-deletes a household today, so that is a
landmine avoided rather than a live requirement. `chore_title` is the snapshot that keeps a
row readable either way, exactly as `chore_occurrences.title` does against a rename.

### A chore edit records field names, never values

In `CHORE_LOG_FIELDS` declaration order, so a row is stable and the UI never sorts. The diff
is two `snapshot_chore` calls on the *same* object, before and after the assignments in
`update_chore` — never the object against the payload — so every normalisation
`_normalised_schedule` applies is reflected on both sides and cannot drift.

- `weekdays` is snapshotted as a tuple, neutralising the ARRAY aliasing footgun by
  construction, and `[]` collapses to `None` so a normalised legacy row reports no phantom
  change.
- `description` compares the stored strings as they are: both sides are already
  `SanitisedHtml` output, and re-sanitising the older side would hide a real allowlist
  tightening instead of reporting it.
- A rename records the title the chore **ends** with, so its row names something that did not
  exist a moment earlier while older rows keep the old name. The `title` entry in the Changed
  column explains the discontinuity to a reader scanning by name. Carrying the old title too
  would be a value, and this log records names of fields, never their contents.
- **The open occurrence's assignee is deliberately absent** — it is derived, and
  `_reconcile_open_occurrence` recomputes it on most edits — so a PATCH that only moves
  `current_assignee_id`, or only sets `clear_current_assignee`, writes no entry at all. Both
  are pinned; so is the no-op edit, which writes nothing.

### Writing and retention

**`record_log_entry` only `session.add`s; the caller commits.** Same contract as
`core/audit.py`'s `record_event`, and it is what makes the 409 path in `update_chore` correct
for free: the entry is staged *before* the `try`, so the rollback expunges it and a retry
writes exactly one. Never move it after the commit.

**Retention is 90 days, enforced twice.** `LOG_RETENTION` is a module constant, NOT a
Settings field — a product promise rather than a deployment knob, like
`MAX_PENDING_INVITATIONS`. The read endpoint applies it as a query predicate *and* a daily
`prune-logs` scheduler job deletes past it, so the promise holds on a deploy where the job
has never run and the table still does not grow without bound.

`prune_old_log_entries` is unit-tested, but neither suite runs `run_prune_logs`'s own session
or fires the scheduler: verify by hand with the CLI after back-dating a row. **The 409 path in
`update_chore` is by-hand-only too** — the collision needs a genuinely concurrent
`POST /complete`, which the savepoint fixtures cannot produce, so "the rollback expunges the
entry" rests on reading the code.

### The impersonator is recorded but never named to the household

`by_admin: bool` on the read schema, the id in the column: the operator may be a stranger
there, and the rule about keeping household-peer payloads off `UserRead` applies to their
identity too. Nothing reads that id — it is there for a by-hand query, and `audit_events`
holds the durable impersonation trail, unpruned.

Both people on a row are `HouseholdMemberRead` (no email), and there is no free-text column
for a caller to write into: a `detail` field on a surface a housemate reads is where personal
data creeps in. (`chore_title` is user-authored text, but a copy of something the reader
already sees on the chore itself.)

The writer emits **no application log line**, deliberately unlike `record_event`: a copy there
would sit outside the 90-day promise, since logs ship off-box under their own retention. That
plus the bounded window is the whole AVG / ISO 27001 story, and keeping it in one place is
what makes it true.
