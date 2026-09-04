import logging
import secrets

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.constants import Tags
from app.schemas.auth import (
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyPasswordRequest,
    VerifyPasswordResponse,
)
from app.services import app_config_repository, email_client

router = APIRouter(prefix="/auth", tags=[Tags.AUTH])
logger = logging.getLogger(__name__)


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
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Email a password-reset link to the fixed configured recipient",
)
def forgot_password() -> ForgotPasswordResponse:
    if app_config_repository.has_active_reset_token():
        # A reset link is already outstanding and unexpired - avoid spamming
        # another email on repeated clicks. Still report success so this
        # never leaks timing/state information to an unauthenticated caller.
        return ForgotPasswordResponse(sent=True)

    settings = get_settings()
    if not settings.PASSWORD_RESET_RECIPIENT_EMAIL or not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="Password reset is not configured.")

    token = app_config_repository.create_reset_token()
    reset_url = f"{settings.PASSWORD_RESET_BASE_URL}/reset-password?token={token}"

    try:
        email_client.send_password_reset_email(reset_url)
    except Exception as exc:
        logger.error(f"Failed to send password reset email: {exc}")
        raise HTTPException(status_code=500, detail="Failed to send reset email. Please try again.") from exc

    return ForgotPasswordResponse(sent=True)


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    summary="Set a new dashboard password using a token from the emailed reset link",
)
def reset_password(body: ResetPasswordRequest) -> ResetPasswordResponse:
    if not app_config_repository.consume_reset_token(body.token):
        raise HTTPException(status_code=400, detail="Invalid or expired link")

    app_config_repository.set_password(body.new_password)
    return ResetPasswordResponse(success=True)
