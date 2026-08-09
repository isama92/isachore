"""Every route the API exposes, and the one rule about where they live.

**A route gated on `AdminUser` answers under `/admin`.** All 20 of them do, which is
what lets a path be read as a statement about who it serves rather than only about what
it returns. The three admin routers are grouped at the bottom for the same reason.

Two near-misses that deliberately stay outside `/admin`, both easy to "fix" wrongly:

- `POST /auth/stop-impersonating` takes no user dependency at all and is authenticated
  by the parked admin cookie, checked inline. It has to be: during impersonation the
  active session belongs to the impersonated user, who is usually not an admin, so an
  `AdminUser` gate would turn away the only caller it exists for.
- `/logs` reads like an operator surface but is `CurrentUser`-gated and scoped by
  household *ownership*, not by `is_admin`.

**The `responses=` on each call is what documents the gate.** `Depends` carries none of its
own, so an `include_router` block (from `app/api/responses.py`, merged into every route in
that router, route-level winning) is the only place a 401 or a 403 reaches the OpenAPI
document. Which block a router takes therefore has to match how it is actually gated, and two
routers below are **mixed** - `auth` and `invitations` each hold public routes alongside gated
ones - so they take nothing here and declare per route instead. Adding a public route to a
router that carries a block, or a gated one to those two, is how this quietly starts lying.
"""

from fastapi import APIRouter

from app.api.responses import FORBIDDEN_ADMIN, UNAUTHORISED
from app.api.v1 import (
    admin_households,
    admin_settings,
    admin_users,
    auth,
    chores,
    completions,
    confirmations,
    docs,
    health,
    home,
    households,
    invitations,
    logs,
    oidc,
    profile,
    stats,
    tags,
    two_factor,
    unscheduled,
)

_ADMIN_GATED = UNAUTHORISED | FORBIDDEN_ADMIN

api_router = APIRouter()

# Public: no session is needed to reach any route in these.
api_router.include_router(health.router, tags=["health"])
# The vendored ReDoc bundle, ungated on purpose: public JavaScript, and the *page* that loads
# it is what nginx gates. Out of the schema, so it adds no operation. Its sibling route (the
# page) is mounted at the app root instead - see api/v1/docs.py for why that matters.
api_router.include_router(docs.asset_router, prefix="/docs")
api_router.include_router(oidc.router, prefix="/auth/oidc", tags=["auth"])
api_router.include_router(confirmations.router, prefix="/confirm", tags=["confirm"])

# Mixed, so no block here: see the module docstring.
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])

# Every route below needs a session, so the 401 is uniform and belongs on the call. The 403
# is NOT: the four household-scoped routers each mix routes that call `require_role` with
# routes open to any member, so the 403 blocks are declared per route inside them. Declaring
# one here instead would put a role 403 on `POST /households` (open to any authenticated
# user), `GET /completions/filters` (deliberately not role-narrowed) and `GET /chores/{id}`
# (deliberately open to every role) - 12 of those 28 operations, a spec lying the other way.
#
# Two 403 blocks, not one, because `households` also holds three ownership-gated routes and
# ownership is off the role ladder: FORBIDDEN_OWNER says a promotion will not help, which is
# the opposite of what FORBIDDEN_ROLE says. Note that "cannot 403" above means cannot raise
# a *gate* 403; CsrfProtectMiddleware answers 403 on any cookie-authenticated unsafe method
# missing X-CSRF-Token, which is most of the mutations here. That one is transport rather
# than route, so it is documented once in main.py's API_DESCRIPTION and nowhere per route.
api_router.include_router(
    profile.router, prefix="/profile", tags=["profile"], responses=UNAUTHORISED
)
api_router.include_router(
    two_factor.router, prefix="/profile/2fa", tags=["two-factor"], responses=UNAUTHORISED
)
api_router.include_router(home.router, prefix="/home", tags=["home"], responses=UNAUTHORISED)
api_router.include_router(
    unscheduled.router, prefix="/unscheduled", tags=["unscheduled"], responses=UNAUTHORISED
)
api_router.include_router(stats.router, prefix="/stats", tags=["stats"], responses=UNAUTHORISED)
api_router.include_router(logs.router, prefix="/logs", tags=["logs"], responses=UNAUTHORISED)
api_router.include_router(
    households.router, prefix="/households", tags=["households"], responses=UNAUTHORISED
)
api_router.include_router(tags.router, prefix="/tags", tags=["tags"], responses=UNAUTHORISED)
api_router.include_router(chores.router, prefix="/chores", tags=["chores"], responses=UNAUTHORISED)
api_router.include_router(
    completions.router, prefix="/completions", tags=["completions"], responses=UNAUTHORISED
)

api_router.include_router(
    admin_users.router, prefix="/admin/users", tags=["admin-users"], responses=_ADMIN_GATED
)
api_router.include_router(
    admin_settings.router,
    prefix="/admin/settings",
    tags=["admin-settings"],
    responses=_ADMIN_GATED,
)
api_router.include_router(
    admin_households.router,
    prefix="/admin/households",
    tags=["admin-households"],
    responses=_ADMIN_GATED,
)
