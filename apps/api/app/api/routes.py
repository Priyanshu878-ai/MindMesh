from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.projects import router as projects_router

api_router = APIRouter()

# Include feature routers under the centralized API router
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(projects_router, prefix="/projects", tags=["Projects"])
