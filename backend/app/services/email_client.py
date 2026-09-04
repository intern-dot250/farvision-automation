import httpx

from app.core.config import get_settings

RESEND_API_URL = "https://api.resend.com/emails"


def send_password_reset_email(reset_url: str) -> None:
    """Sends the reset link to the single fixed recipient configured via
    PASSWORD_RESET_RECIPIENT_EMAIL - there's no per-user email to look up,
    since this app has exactly one shared dashboard password. Raises on
    failure; the caller (the /auth/forgot-password route) is responsible for
    deciding how to surface that to the client."""
    settings = get_settings()
    response = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={
            "from": settings.RESEND_FROM_EMAIL,
            "to": [settings.PASSWORD_RESET_RECIPIENT_EMAIL],
            "subject": "Farvision Automation - Password Reset",
            "html": (
                "<p>A password reset was requested for the Farvision Automation dashboard.</p>"
                f'<p><a href="{reset_url}">Click here to set a new password</a></p>'
                "<p>This link expires in 30 minutes. If you didn't request this, you can ignore this email.</p>"
            ),
        },
        timeout=15.0,
    )
    response.raise_for_status()
