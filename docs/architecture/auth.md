# Authentication

## Sessions

DB-backed opaque tokens (`auth_tokens` table, SHA-256 hashed), sent as an httpOnly
`isachore_token` cookie or `Authorization: Bearer`.

**No self-registration:** admins create users; the first admin comes from the `init` CLI.
Passwords are hashed with Argon2 (pwdlib). Protect endpoints by reusing `CurrentUser` /
`AdminUser` from `app/api/deps.py`.

Users may never demote or deactivate themselves. Note that self-guard is the ONLY floor:
nothing counts admins, so admins can disable each other down to zero active ones.

### User lifecycle

`users.status` is a `UserStatus` StrEnum (`waiting_confirmation` / `active` / `disabled`),
stored as a plain String with the closed set enforced at the schema layer — like theme,
accent and language — plus a `confirmed_at` timestamp.

Only `active` users can log in or be impersonated. Deactivation is a soft delete
(`status=disabled`). Login and impersonation gate on `status == UserStatus.active`.

### Admin lockout recovery (I2)

`init` no-ops only while an *active* admin exists. With none, it takes over the account named
by `--email` (promote, re-activate, reset password, clear 2FA, revoke sessions and
confirmation links) or creates a fresh admin if that email is unknown.

Any new "restore access" step belongs in `_restore_admin`, which mirrors the revocations
`update_user` / `reset_two_factor` do for the same changes; forgetting one leaves a stale way
in.

It cannot help while an admin row is active but unusable (2FA lost, password forgotten): that
needs a direct DB edit first.

## CSRF

`CsrfProtectMiddleware` (`app/core/csrf.py`, global, outermost) rejects unsafe-method requests
(POST/PATCH/PUT/DELETE) that carry an auth cookie (`isachore_token` /
`isachore_admin_token`) but lack a non-empty `X-CSRF-Token` header, with 403.

It is a custom-header defence in depth over `SameSite=Lax`, sound because there is no CORS.
`Authorization: Bearer` requests and public pre-auth flows (no cookie) are exempt. The
frontend `api` wrapper adds the header automatically, so app code needs no changes.

## Impersonation

`POST /admin/users/{id}/impersonate` swaps the session cookie to the target user and parks the
admin's own token in the `isachore_admin_token` cookie; `POST /auth/stop-impersonating`
restores it. `/auth/me` reports `impersonating`; logout ends both sessions.

**`POST /auth/stop-impersonating` takes no user dependency at all** — not `AdminUser`, not even
`CurrentUser` — and authenticates off the parked `isachore_admin_token` cookie, with the
`is_admin` check done inline against *that* cookie's identity. It has to: during impersonation
the active session belongs to the impersonated user, who is usually not an admin, so an
`AdminUser` gate would turn away the only caller it exists for. Its sole frontend caller,
`TopBar.tsx`, renders for every authenticated user. This is why it sits outside `/api/v1/admin`
and why `auth.stopImpersonating` stays where it is in `lib/endpoints.ts`.

## Email confirmation

Server-wide `app_settings.require_confirmation` (single-row table, `get_app_settings`) toggles
it. When on, creating a user emails a `confirmation_tokens` link (same hashed-opaque-token
pattern as auth tokens); the public `/api/v1/confirm/{token}` GET/POST sets the password, flips
to `active` + `confirmed_at`, and auto-logs-in.

SMTP is env-only (`app/core/config.py`, optional at boot; `smtp_configured()` in
`app/core/email.py`); enabling confirmation or the test-email button needs it. Emails are
English-only (the backend has no i18n). Server settings live under `/api/v1/admin/settings`
and the **Admin > Server settings** page. Dev SMTP goes to the mailpit compose service
(http://localhost:8025).

## Single sign-on (OIDC)

`core/oidc.py` owns the protocol (discovery, the PKCE code exchange, ID token verification),
`api/v1/oidc.py` owns the policy, and the whole thing is env-gated on `oidc_configured()`
exactly as email is on `smtp_configured()`.

The session it opens is an ordinary `auth_tokens` row: nothing downstream can tell an SSO
session from a password one, deliberately.

### Both endpoints are GET and both answer with a redirect

Neither is a style choice. Auth cookies are `SameSite=Lax`, which a browser sends on a
cross-site top-level *navigation* but not on a cross-site POST, so a `form_post` response mode
would arrive with no state cookie and fail the browser-binding check every time.

GET also means `CsrfProtectMiddleware` exempts them on method alone, which is what makes the
callback reachable: it is a navigation from the provider with no chance to set `X-CSRF-Token`.

Redirects rather than JSON because the caller is a browser mid-navigation, not the `api`
wrapper, so a refusal has to land somewhere readable — hence `?sso_error=<code>` on the login
url.

### No nginx, CSP or auth-context change was needed

The prod CSP is `connect-src 'self'; form-action 'self'`, which would block a browser-side
token exchange or a form post to the provider. A backend-mediated redirect is covered by
neither directive (CSP does not govern top-level navigations; `navigate-to` was dropped from
the spec). Do NOT widen the CSP for this, and do not add `CORSMiddleware` — `core/csrf.py`'s
whole defence rests on there being no CORS.

The callback sets the cookie and 302s to the SPA, so the app *cold-boots* and `AuthProvider`'s
mount `/auth/me` probe picks the session up — already one of the four `claimTableSettings`
adoption paths. So SSO is not a fifth one, and `AuthContextValue` / `makeAuthValue` are
untouched. Keep it that way: a callback returning JSON would need both.

### `joserfc`, NOT `authlib.jose`

They are the same author's new and old JOSE APIs; `authlib.jose` emits a deprecation warning
pointing at joserfc and is scheduled to go away in authlib 2.0, which would silently take ID
token verification with it.

authlib is still used, but only `integrations.httpx_client` for the code exchange — never
`integrations.starlette_client`, which is the obvious import and the wrong one: it keeps
`state` and `nonce` in a Starlette session, so adopting it would mean adding
`SessionMiddleware` and a second signed-cookie mechanism competing with this codebase's
"random token in an httpOnly cookie, SHA-256 hash in Postgres" pattern.

### `oidc_login_states` is a table, not a fat cookie

Shaped like `TwoFactorChallenge`, for three reasons a cookie cannot cover: the nonce and PKCE
verifier must not be client-controllable; deleting the row on use makes a flow single-use, so
a captured callback url cannot be replayed; and `expires_at` bounds it like every other
short-lived token here.

The raw token doubles as the `state` parameter *and* the `isachore_oidc` cookie value, and
requiring the two to match is the browser binding — without it an attacker starts a flow and
feeds the victim its callback url, landing the victim in the attacker's session. Compared with
`compare_digest`, since the caller controls the query parameter and the cookie is httpOnly.

`isachore_oidc` is deliberately absent from `_AUTH_COOKIES` in `core/csrf.py`, for the same
reason `isachore_2fa` is: it authenticates nobody, so it must not turn an anonymous request
into one that middleware reads as a session. Note listing it would not actually break today's
endpoints, since that middleware only inspects unsafe methods and both are GET — the reason
above is the one that survives a change of method.

### `_consume_state` commits the delete before talking to the provider

Not tidiness. `complete()` makes up to five calls to the provider (discovery, token, JWKS, a
forced JWKS re-fetch, userinfo), each with its own 10s timeout, so holding the transaction
across it would park a pooled connection for as long as a degraded provider takes to answer —
a slow IdP would exhaust the pool and take the rest of the API down, not just sign-in.

Separately, the claim is a **single `DELETE ... RETURNING`** rather than a SELECT then a
delete: that gap is a race, and the loser would raise `StaleDataError` (an unhandled 500)
where a clean refusal belongs, which a double-click on a slow callback is enough to reach.

Neither property is testable under the savepoint fixtures, so both rest on reading the code,
like the invitation advisory lock and the zone-change race.

### `/start` has its own throttle, with its own ceiling

It is unauthenticated and writes a row per call, and the opportunistic sweep only clears rows
past their ten-minute TTL, so nothing just inserted is eligible: without a bound an anonymous
loop grows `oidc_login_states` for as long as it runs.

Its counter is separate from the callback's because it counts *every* start rather than every
failure, so `login_ip_max_attempts` (20, sized for failures) would break a shared office NAT on
a Monday morning; `_OIDC_START_MAX_ATTEMPTS` is an order of magnitude above any human sequence.
Keeping them separate also stops a run of provider errors from spending a legitimate user's
budget for retrying, which is pinned by its own test.

### The identity link is TWO columns

`users.oidc_issuer` and `users.oidc_subject`, unique together. `sub` is only promised unique
*per issuer*, so with the subject alone an operator repointing `OIDC_ISSUER` at a different
provider whose subjects happened to collide would match one person onto another's account.
With the pair the lookup simply misses and falls back to email, which re-links correctly.
Postgres treats NULLs as distinct, which is what made the constraint safe to add to a populated
table.

Email finds the account on a **first** sign-in only; after that the subject does, so changing an
address at the provider keeps the account, and the local `email` is never overwritten from the
provider.

**The re-link only self-heals when the new provider hands out a different subject.** If it
reuses the same value under a new issuer the row is simply re-pointed (pinned by
`test_the_same_subject_from_the_configured_issuer_re_links`); if it hands out a *new* subject
for somebody already linked, the email match finds a row whose stored subject differs and
`already_linked` refuses — by design, since that refusal is the account takeover guard.

There is deliberately no in-app unlink, so recovering a provider migration is the SQL in
README's single sign-on section. `cli init` clears the link too, but only for the account it
recovers and only during an admin lockout, so it is not that tool.

### Verification is isachore's own question

Answered by `users.confirmed_at`. The provider's `email_verified` claim is not read at all, and
`OidcIdentity` has no field for it. Two reasons, and the second settled it: the account already
exists because an admin created it, so the provider's job here is to prove who is at the
keyboard rather than to re-assert something this app already tracks; and the claim varies
enough between providers to be a poor gate — Authentik's default scope mapping omits it
entirely, others stringify it, others always send true. Gating on it turned a correctly
configured Authentik away with advice about verifying an address it had never made a claim
about.

So the exposure is exactly this: anybody who can self-assert an address inside the directory
can link to and sign in as the local account holding it. Admin-created accounts plus a trusted
directory is what stands in for the claim. A deliberate product decision, reaffirmed after
being raised.

Three narrowings if it ever needs closing, cheapest first:

1. **Refuse only when the claim is present and false** (`bool | None`, refuse on `False`).
   Authentik omitting it keeps working, providers that always send true are unaffected, and a
   directory actively reporting an unverified address is caught. The cost is real: it brings
   back both the tri-state read *and* per-source selection in `build_identity`, since a verdict
   from one mapping must not be paired with the other's address.
2. **Gate the `waiting_confirmation` -> `active` transition** on the claim when present,
   leaving linking alone. The best-targeted of the three, because that transition is the one
   place this app writes `confirmed_at` on the strength of a provider sign-in, and the Profile
   badge then reports it as proved.
3. **Gate linking unconditionally**, and accept that providers omitting the claim stop working.
   What this app did before, and what turned a correct Authentik away.

`confirmed_at` is surfaced instead, on Profile, as a badge beside the address — shown only where
the server asks for confirmation at all, since a null means nothing on a server that never asks.
`MeRead.email_confirmation_required` tells a client which of those two readings applies; it rides
on the me payload rather than `/admin/settings` because that endpoint is admin-only and this is a
fact every user's own page needs.

### `totp_enabled` is deliberately not consulted in the callback

The provider owns authentication including its own MFA, so re-challenging for a local code asks
the same person to prove themselves twice for nothing. It reads like an omission, which is why
it carries a comment there, a test, and a line of copy on `TwoFactorSettings`: without that copy,
somebody who just enrolled reads an SSO sign-in that never asked for a code as a bug. Local 2FA
still applies in full to password sign-in.

### Audit, and `OIDC_ONLY`

Audit reuses `login_success` / `login_failed` with an `"oidc"`-prefixed `detail`, rather than new
enum members: `audit_events.action` is a native Postgres enum, so a new value needs an
`ALTER TYPE`, and `cli.py` already sets the precedent of reusing an action. Do not add SSO
actions without reading that note first.

**`OIDC_ONLY` is gated on `oidc_configured()` too, in both places that read it** (`login`'s 403
and `/auth/methods`). The flag alone is a total lockout, and while `check_startup_config` refuses
that combination, **dev is exempt from every startup check** — so without the second clause a
developer who set the flag and nothing else locks themselves out of their own stack with no
explanation. There is deliberately no admin exemption: an `is_admin` carve-out would tell an
anonymous caller whether an address belongs to an admin.

### The module seam

`begin` and `complete` are called through the module (`oidc_core.begin(...)`), for the same
reason endpoints call `clock.now()`: it leaves `monkeypatch.setattr(oidc_core, "complete", ...)`
able to reach them, so the whole policy is testable with no provider. Importing the names would
bind them at import time and silently defeat every stub in `tests/test_oidc.py`.

The redirect uri is derived from `app_base_url` rather than configured, which is also why it is
reported on **Admin > Server settings**: it is the value an operator has to register with the
provider and there is nowhere else to read it.

### Open-redirect guards

`safeReturnPath` (`lib/routes.ts`) and `_safe_return_to` (`api/v1/oidc.py`) guard the same idea
and are **NOT the same function**, which is the part to keep straight.

Both refuse a post-sign-in destination that is not our own origin — the SPA's `?next=`, the
backend's SSO `return_to` — and both discard rather than correct. But the frontend one asks the
WHATWG URL parser and returns the NORMALISED path, because a string rule is holed against its
sink: the parser strips ASCII tab, LF and CR *before* parsing, so `/%09/evil.example` satisfies
"one leading slash, no `//`, no backslash" and `location.replace` then lands on
`https://evil.example`. That shipped once.

The backend keeps the string rule and is safe only because Starlette percent-encodes the
`Location` header — safe by accident rather than by design. So do not treat either as proof of
the other, and do not "simplify" the frontend one back into a character check. The frontend needs
its own guard at all because the SPA is static: nothing server-side sees `?next=` before the
browser acts on it.

## Testing SSO

**Two halves, plus an autouse reset.** `_reset_oidc` in `conftest.py` clears the OIDC settings
and calls `oidc_core.reset_caches()` before every test, mirroring `_reset_smtp` /
`_reset_app_key` and for the same reason: pytest runs inside the dev container with
`env_file: .env`, so uncommenting the OIDC block to try the flow by hand would otherwise turn
the button on for every test and make `POST /auth/login` 403.

The opt-in `oidc` fixture configures a provider over https, so a case pinning a non-dev
environment cannot trip the plaintext-issuer refusal (the startup-check tests build their own
config, since they call `check_startup_config()` directly). The cache clear is the other half —
discovery documents are memoised per issuer, and one test's must not be served to the next.

- The **policy** half stubs `oidc_core.begin` / `oidc_core.complete`, so no provider is involved.
- The **verification** half does the opposite: real RSA keys, real signed tokens, real
  `_verify_id_token`, stubbing only the key fetch.

Do not collapse them — without the second, every signature check in the feature is mocked out,
and that function is the only thing between a stranger and a session.

**Every guard reachable from a test was mutation-checked** (delete it, watch a test fail): the
state cookie comparison, the issuer half of the identity lookup, the `already_linked` takeover
guard, the disabled-account refusal, the open-redirect guard on `return_to` including its length
clause, the algorithm allowlist and its non-list guard, the non-object claims guard, both `azp`
rules, `build_identity`'s same-source selection, the identity length guard, the provider-name
normalisation, both throttles, `clear_login_throttle`'s prefixes, the confirmation-token
revocation, and `OIDC_ONLY`'s second clause.

The exception, and it is the interesting one: **`_client()` is never executed by either suite**,
so it is the one place PKCE is actually requested from authlib and an argument rename there would
ship green. That is a by-hand check, like the boot migration.

**The mutation has to be as narrow as the guard, and getting that wrong hid two holes here.**
Replacing `if not state or not cookie or not compare_digest(state, cookie)` with `if not state`
fails a test, so the guard looks pinned — but it deleted *three* clauses, and the test that failed
only needed the first. Dropping the `compare_digest` alone left the whole suite green, because the
one test aimed at it deleted the cookie (satisfying `not cookie` instead) and the other passed a
state matching no row (satisfying the lookup). Same story for
`User.oidc_issuer == identity.issuer`. Both now have a test that satisfies every *other* clause
deliberately: two concurrent flows for the comparison, and a same-subject-different-issuer
collision for the lookup.

One guard did NOT survive the check and was removed rather than kept: a `.catch` that reset
`methods` to password-only on a failed probe in `Login.tsx`. It was unobservable, because the
pre-load state already read as password-only, so the fallback is now the `useState` default and
there is no branch to pin. Seeding that default is what the tests actually hold.

**The dev stack ships no identity provider, deliberately** — trying the flow by hand means
pointing `.env` at a real one. When you do, the trap that costs the most time is that the browser
and the backend must reach it at the *same* url, or `iss` disagrees with `OIDC_ISSUER` and every
sign-in fails verification with a message that does not say so. `localhost` cannot be that url:
inside the backend container it is the backend. Check it before debugging anything else — fetch
`<issuer>/.well-known/openid-configuration` from the host and from inside the backend container
and compare `issuer`; they must be byte-identical.
