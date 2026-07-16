from fastapi import APIRouter

from app.api.v1 import auth, chores, health, households, tags, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(households.router, prefix="/households", tags=["households"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(chores.router, prefix="/chores", tags=["chores"])
