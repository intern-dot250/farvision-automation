from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _FakeSettings:
    ACCESS_PASSWORD = "test-secret"


def test_clear_sheet_rejects_missing_secret():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()):
        response = client.post("/api/v1/automation/clear-sheet?target=both")

    assert response.status_code == 401


def test_clear_sheet_rejects_wrong_secret():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()):
        response = client.post(
            "/api/v1/automation/clear-sheet?target=both",
            headers={"X-Internal-Secret": "wrong-value"},
        )

    assert response.status_code == 401


def test_clear_sheet_rejects_unset_access_password():
    # ACCESS_PASSWORD isn't configured (empty string) - never treat that as
    # "no check needed"; every request must be rejected in that state.
    class _NoPassword:
        ACCESS_PASSWORD = ""

    with patch("app.api.v1.automation.get_settings", return_value=_NoPassword()):
        response = client.post(
            "/api/v1/automation/clear-sheet?target=both",
            headers={"X-Internal-Secret": ""},
        )

    assert response.status_code == 401


def test_clear_sheet_rejects_unknown_target():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()):
        response = client.post(
            "/api/v1/automation/clear-sheet?target=everything",
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 400


def test_clear_sheet_receipt_payment_target():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()), patch(
        "app.api.v1.automation.automation_engine.clear_destination_data",
        return_value=[{"sheet": "Receipt / Payment", "tabs_cleared": ["ReceiptPayment", "LedgerDetails"]}],
    ) as mock_clear:
        response = client.post(
            "/api/v1/automation/clear-sheet?target=receipt_payment",
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 200
    mock_clear.assert_called_once_with("receipt_payment")
    body = response.json()
    assert body["target"] == "receipt_payment"
    assert body["sheets_cleared"] == [
        {"sheet": "Receipt / Payment", "tabs_cleared": ["ReceiptPayment", "LedgerDetails"]}
    ]


def test_clear_sheet_deposit_withdrawal_target():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()), patch(
        "app.api.v1.automation.automation_engine.clear_destination_data",
        return_value=[{"sheet": "Deposit / Withdrawal", "tabs_cleared": ["DepositWithdrawal"]}],
    ) as mock_clear:
        response = client.post(
            "/api/v1/automation/clear-sheet?target=deposit_withdrawal",
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 200
    mock_clear.assert_called_once_with("deposit_withdrawal")


def test_clear_sheet_both_target():
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()), patch(
        "app.api.v1.automation.automation_engine.clear_destination_data",
        return_value=[
            {"sheet": "Receipt / Payment", "tabs_cleared": ["ReceiptPayment"]},
            {"sheet": "Deposit / Withdrawal", "tabs_cleared": ["DepositWithdrawal"]},
        ],
    ) as mock_clear:
        response = client.post(
            "/api/v1/automation/clear-sheet?target=both",
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 200
    mock_clear.assert_called_once_with("both")
    assert len(response.json()["sheets_cleared"]) == 2
