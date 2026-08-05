from fastapi import APIRouter

from app.api.v1 import (
    admin_households,
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
    server_settings,
    stats,
    tags,
    two_factor,
    unscheduled,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(oidc.router, prefix="/auth/oidc", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(confirmations.router, prefix="/confirm", tags=["confirm"])
api_router.include_router(server_settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(two_factor.router, prefix="/profile/2fa", tags=["two-factor"])
api_router.include_router(home.router, prefix="/home", tags=["home"])
api_router.include_router(unscheduled.router, prefix="/unscheduled", tags=["unscheduled"])
api_router.include_router(households.router, prefix="/households", tags=["households"])
api_router.include_router(
    admin_households.router, prefix="/admin/households", tags=["admin-households"]
)
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(chores.router, prefix="/chores", tags=["chores"])
api_router.include_router(completions.router, prefix="/completions", tags=["completions"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
