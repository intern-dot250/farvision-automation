from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _FakeSettings:
    ACCESS_PASSWORD = "legacy-secret"
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587
    SMTP_USERNAME = "sender@gmail.com"
    SMTP_PASSWORD = "app-password"
    SMTP_FROM_EMAIL = "sender@gmail.com"
    PASSWORD_RESET_RECIPIENT_EMAIL = "nycjain@gmail.com"
    PASSWORD_RESET_BASE_URL = "https://fv.tallstone.in"


def test_verify_password_true_when_matches_stored_hash():
    with patch("app.api.v1.auth.app_config_repository.get_password_hash", return_value="stored-hash"), patch(
        "app.api.v1.auth.app_config_repository.verify_password", return_value=True
    ):
        response = client.post("/api/v1/auth/verify-password", json={"password": "correct"})

    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_verify_password_false_when_no_match():
    with patch("app.api.v1.auth.app_config_repository.get_password_hash", return_value="stored-hash"), patch(
        "app.api.v1.auth.app_config_repository.verify_password", return_value=False
    ):
        response = client.post("/api/v1/auth/verify-password", json={"password": "wrong"})

    assert response.status_code == 200
    assert response.json() == {"valid": False}


def test_verify_password_falls_back_to_legacy_access_password_and_seeds():
    with patch("app.api.v1.auth.app_config_repository.get_password_hash", return_value=None), patch(
        "app.api.v1.auth.app_config_repository.seed_password_if_empty"
    ) as mock_seed, patch("app.api.v1.auth.get_settings", return_value=_FakeSettings()):
        response = client.post("/api/v1/auth/verify-password", json={"password": "legacy-secret"})

    assert response.status_code == 200
    assert response.json() == {"valid": True}
    mock_seed.assert_called_once_with("legacy-secret")


def test_verify_password_no_row_and_wrong_legacy_password_fails():
    with patch("app.api.v1.auth.app_config_repository.get_password_hash", return_value=None), patch(
        "app.api.v1.auth.get_settings", return_value=_FakeSettings()
    ):
        response = client.post("/api/v1/auth/verify-password", json={"password": "not-it"})

    assert response.status_code == 200
    assert response.json() == {"valid": False}


def test_forgot_password_sends_email_and_creates_token():
    with patch("app.api.v1.auth.app_config_repository.has_active_reset_token", return_value=False), patch(
        "app.api.v1.auth.app_config_repository.create_reset_token", return_value="raw-token"
    ), patch("app.api.v1.auth.get_settings", return_value=_FakeSettings()), patch(
        "app.api.v1.auth.email_client.send_password_reset_email"
    ) as mock_send:
        response = client.post("/api/v1/auth/forgot-password")

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    mock_send.assert_called_once()
    assert "raw-token" in mock_send.call_args[0][0]


def test_forgot_password_skips_new_email_when_token_already_active():
    with patch("app.api.v1.auth.app_config_repository.has_active_reset_token", return_value=True), patch(
        "app.api.v1.auth.email_client.send_password_reset_email"
    ) as mock_send:
        response = client.post("/api/v1/auth/forgot-password")

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    mock_send.assert_not_called()


def test_forgot_password_returns_500_when_not_configured():
    class _Unconfigured:
        SMTP_USERNAME = ""
        SMTP_PASSWORD = ""
        PASSWORD_RESET_RECIPIENT_EMAIL = ""

    with patch("app.api.v1.auth.app_config_repository.has_active_reset_token", return_value=False), patch(
        "app.api.v1.auth.get_settings", return_value=_Unconfigured()
    ):
        response = client.post("/api/v1/auth/forgot-password")

    assert response.status_code == 500


def test_reset_password_succeeds_with_valid_token():
    with patch("app.api.v1.auth.app_config_repository.consume_reset_token", return_value=True), patch(
        "app.api.v1.auth.app_config_repository.set_password"
    ) as mock_set:
        response = client.post(
            "/api/v1/auth/reset-password", json={"token": "valid-token", "new_password": "new-password-123"}
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    mock_set.assert_called_once_with("new-password-123")


def test_reset_password_rejects_invalid_or_expired_token():
    with patch("app.api.v1.auth.app_config_repository.consume_reset_token", return_value=False):
        response = client.post(
            "/api/v1/auth/reset-password", json={"token": "bad-token", "new_password": "new-password-123"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired link"


def test_reset_password_rejects_short_password():
    response = client.post("/api/v1/auth/reset-password", json={"token": "valid-token", "new_password": "short"})

    assert response.status_code == 422
