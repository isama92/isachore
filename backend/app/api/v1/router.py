from fastapi import APIRouter

from app.api.v1 import (
    admin_households,
    auth,
    chores,
    confirmations,
    health,
    households,
    invitations,
    profile,
    server_settings,
    tags,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(confirmations.router, prefix="/confirm", tags=["confirm"])
api_router.include_router(server_settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(households.router, prefix="/households", tags=["households"])
api_router.include_router(
    admin_households.router, prefix="/admin/households", tags=["admin-households"]
)
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(chores.router, prefix="/chores", tags=["chores"])
