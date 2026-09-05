from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _FakeSettings:
    ACCESS_PASSWORD = "legacy-secret"


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


class _InternalSecretSettings:
    INTERNAL_API_SECRET = "test-secret"


def test_set_password_rejects_missing_secret():
    response = client.post("/api/v1/auth/set-password", json={"new_password": "new-password-123"})

    assert response.status_code == 401


def test_set_password_rejects_wrong_secret():
    with patch("app.api.v1.auth.get_settings", return_value=_InternalSecretSettings()):
        response = client.post(
            "/api/v1/auth/set-password",
            json={"new_password": "new-password-123"},
            headers={"X-Internal-Secret": "wrong-value"},
        )

    assert response.status_code == 401


def test_set_password_rejects_short_password():
    with patch("app.api.v1.auth.get_settings", return_value=_InternalSecretSettings()):
        response = client.post(
            "/api/v1/auth/set-password",
            json={"new_password": "short"},
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 422


def test_set_password_succeeds_with_valid_secret():
    with patch("app.api.v1.auth.get_settings", return_value=_InternalSecretSettings()), patch(
        "app.api.v1.auth.app_config_repository.set_password"
    ) as mock_set:
        response = client.post(
            "/api/v1/auth/set-password",
            json={"new_password": "new-password-123"},
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    mock_set.assert_called_once_with("new-password-123")
