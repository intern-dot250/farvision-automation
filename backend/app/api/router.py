from fastapi import APIRouter

from app.api.v1 import automation, health, history, sheets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(sheets.router)
api_router.include_router(automation.router)
api_router.include_router(history.router)
