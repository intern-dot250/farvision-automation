import secrets

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.constants import Tags
from app.schemas.auth import VerifyPasswordRequest, VerifyPasswordResponse
from app.services import app_config_repository

router = APIRouter(prefix="/auth", tags=[Tags.AUTH])


@router.post(
    "/verify-password",
    response_model=VerifyPasswordResponse,
    summary="Check a candidate dashboard password - called server-side only, by the frontend's /api/login route",
)
def verify_password(body: VerifyPasswordRequest) -> VerifyPasswordResponse:
    stored_hash = app_config_repository.get_password_hash()

    if stored_hash is None:
        # No row yet (first request after this feature's first deploy) -
        # fall back once to the static ACCESS_PASSWORD env var so today's
        # password keeps working through the cutover, and seed app_config
        # from it on a successful match so every later check is DB-driven.
        legacy_password = get_settings().ACCESS_PASSWORD
        if legacy_password and secrets.compare_digest(body.password, legacy_password):
            app_config_repository.seed_password_if_empty(legacy_password)
            return VerifyPasswordResponse(valid=True)
        return VerifyPasswordResponse(valid=False)

    return VerifyPasswordResponse(valid=app_config_repository.verify_password(body.password, stored_hash))
