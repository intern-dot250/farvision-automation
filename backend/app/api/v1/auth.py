import hmac
import secrets

from fastapi import APIRouter, Header, HTTPException

from app.core.config import get_settings
from app.core.constants import Tags
from app.schemas.auth import (
    SetPasswordRequest,
    SetPasswordResponse,
    VerifyPasswordRequest,
    VerifyPasswordResponse,
)
from app.services import app_config_repository

router = APIRouter(prefix="/auth", tags=[Tags.AUTH])


def _verify_internal_secret(x_internal_secret: str | None) -> None:
    """Same guard as automation.py's /clear-sheet - checked against the
    static INTERNAL_API_SECRET shared between this API and the frontend's
    own server-side routes, never exposed to the browser."""
    expected = get_settings().INTERNAL_API_SECRET
    if not expected or not x_internal_secret or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid internal secret")


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


@router.post(
    "/set-password",
    response_model=SetPasswordResponse,
    summary="Change the dashboard password - called only by the frontend's session-gated /api/change-password route",
)
def set_password(body: SetPasswordRequest, x_internal_secret: str | None = Header(default=None)) -> SetPasswordResponse:
    _verify_internal_secret(x_internal_secret)
    app_config_repository.set_password(body.new_password)
    return SetPasswordResponse(success=True)
