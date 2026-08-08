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
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin_households,
    admin_settings,
    admin_users,
    auth,
    chores,
    completions,
    confirmations,
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

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(oidc.router, prefix="/auth/oidc", tags=["auth"])
api_router.include_router(confirmations.router, prefix="/confirm", tags=["confirm"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(two_factor.router, prefix="/profile/2fa", tags=["two-factor"])
api_router.include_router(home.router, prefix="/home", tags=["home"])
api_router.include_router(unscheduled.router, prefix="/unscheduled", tags=["unscheduled"])
api_router.include_router(households.router, prefix="/households", tags=["households"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(chores.router, prefix="/chores", tags=["chores"])
api_router.include_router(completions.router, prefix="/completions", tags=["completions"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])

api_router.include_router(admin_users.router, prefix="/admin/users", tags=["admin-users"])
api_router.include_router(admin_settings.router, prefix="/admin/settings", tags=["admin-settings"])
api_router.include_router(
    admin_households.router, prefix="/admin/households", tags=["admin-households"]
)
