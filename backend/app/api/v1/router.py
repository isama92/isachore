from fastapi import APIRouter

from app.api.v1 import auth, chores, health, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chores.router, prefix="/chores", tags=["chores"])
