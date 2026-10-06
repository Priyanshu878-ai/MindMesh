from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.routes import api_router
from app.core.settings import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered codebase intelligence platform",
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Centralized API v1 router
app.include_router(api_router, prefix=settings.api_v1_prefix)

# Backward-compatible root health endpoint
app.include_router(health_router)