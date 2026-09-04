import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send_password_reset_email(reset_url: str) -> None:
    """Sends the reset link to the single fixed recipient configured via
    PASSWORD_RESET_RECIPIENT_EMAIL - there's no per-user email to look up,
    since this app has exactly one shared dashboard password. Uses Gmail's
    SMTP server with an App Password (stdlib smtplib, no new dependency) -
    no domain verification needed, unlike a transactional-email API's
    sandbox mode. Raises on failure; the caller (the /auth/forgot-password
    route) is responsible for deciding how to surface that to the client."""
    settings = get_settings()

    message = EmailMessage()
    message["Subject"] = "Farvision Automation - Password Reset"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = settings.PASSWORD_RESET_RECIPIENT_EMAIL
    message.set_content(
        "A password reset was requested for the Farvision Automation dashboard.\n\n"
        f"Reset link: {reset_url}\n\n"
        "This link expires in 30 minutes. If you didn't request this, you can ignore this email."
    )
    message.add_alternative(
        "<p>A password reset was requested for the Farvision Automation dashboard.</p>"
        f'<p><a href="{reset_url}">Click here to set a new password</a></p>'
        "<p>This link expires in 30 minutes. If you didn't request this, you can ignore this email.</p>",
        subtype="html",
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
