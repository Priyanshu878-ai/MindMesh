from fastapi import APIRouter

from app.core.settings import settings


router = APIRouter()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
    }