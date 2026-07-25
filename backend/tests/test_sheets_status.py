from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_sheets_status_reports_connection_per_sheet():
    with patch("app.api.v1.sheets.sheets_client.list_worksheet_titles") as mock_list:
        mock_list.return_value = ["Sheet1"]

        response = client.get("/api/v1/sheets/status")

    assert response.status_code == 200
    body = response.json()
    assert len(body["sheets"]) == 3
    assert all(sheet["connected"] for sheet in body["sheets"])


def test_sheets_status_reports_failure_per_sheet():
    with patch("app.api.v1.sheets.sheets_client.list_worksheet_titles") as mock_list:
        mock_list.side_effect = Exception("permission denied")

        response = client.get("/api/v1/sheets/status")

    assert response.status_code == 200
    body = response.json()
    assert all(not sheet["connected"] for sheet in body["sheets"])
    assert all(sheet["error"] == "permission denied" for sheet in body["sheets"])
