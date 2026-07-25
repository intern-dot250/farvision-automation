from fastapi import APIRouter

from app.core.config import get_settings
from app.core.constants import Tags

router = APIRouter(tags=[Tags.HEALTH])


@router.get("/health", summary="Health check")
def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }
