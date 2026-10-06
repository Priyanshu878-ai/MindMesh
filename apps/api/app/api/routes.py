from fastapi import APIRouter

from app.api.health import router as health_router

api_router = APIRouter()

# Include feature routers under the centralized API router
api_router.include_router(health_router, tags=["Health"])
