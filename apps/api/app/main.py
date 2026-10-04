from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.settings import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered codebase intelligence platform",
)

app.include_router(health_router)