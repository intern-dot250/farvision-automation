from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _FakeSettings:
    INTERNAL_API_SECRET = "test-secret"


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
    # INTERNAL_API_SECRET isn't configured (empty string) - never treat that as
    # "no check needed"; every request must be rejected in that state.
    class _NoPassword:
        INTERNAL_API_SECRET = ""

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


def test_clear_sheet_surfaces_real_error_as_json_instead_of_opaque_500():
    # Previously an unhandled exception here fell through to Starlette's
    # debug-mode HTML error page, which the frontend can't parse - it just
    # showed "status 500" with no indication of what actually failed (e.g.
    # a Google Sheets API rate limit). Must come back as clean JSON with
    # the real exception message in `detail`.
    with patch("app.api.v1.automation.get_settings", return_value=_FakeSettings()), patch(
        "app.api.v1.automation.automation_engine.clear_destination_data",
        side_effect=RuntimeError("Quota exceeded for quota metric 'Read requests'"),
    ):
        response = client.post(
            "/api/v1/automation/clear-sheet?target=both",
            headers={"X-Internal-Secret": "test-secret"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert "Quota exceeded" in response.json()["detail"]


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
