import gspread
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.automation_engine import RunResult
from app.services.statement_parser import SheetCandidates

client = TestClient(app)

_VALID_URL = "https://docs.google.com/spreadsheets/d/1fBwkpGZU2M9BTsJjpwKyTIYIZra1J43hlVt2PlQ0d9Q/edit"


# --- POST /automation/google-sheet-tabs ---


def test_google_sheet_tabs_returns_included_and_ignored():
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.title = "RecieptPayment-Upload"

    with patch(
        "app.api.v1.automation.sheets_client.open_sheet", return_value=mock_spreadsheet
    ), patch(
        "app.api.v1.automation.sheets_client.list_worksheet_titles",
        return_value=["YES Rera 0377", "Index"],
    ), patch(
        "app.api.v1.automation.statement_parser.list_candidate_sheets_from_google",
        return_value=SheetCandidates(included=["YES Rera 0377"], ignored=["Index"]),
    ):
        response = client.post("/api/v1/automation/google-sheet-tabs", json={"url": _VALID_URL})

    assert response.status_code == 200
    assert response.json() == {
        "spreadsheet_id": "1fBwkpGZU2M9BTsJjpwKyTIYIZra1J43hlVt2PlQ0d9Q",
        "spreadsheet_title": "RecieptPayment-Upload",
        "sheets": ["YES Rera 0377"],
        "total_sheets": 2,
        "ignored_sheets": ["Index"],
        "approval_columns": [],
    }


def test_google_sheet_tabs_rejects_invalid_url():
    response = client.post("/api/v1/automation/google-sheet-tabs", json={"url": "not a url"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Please enter a valid Google Sheets URL."


def test_google_sheet_tabs_reports_inaccessible_sheet():
    with patch(
        "app.api.v1.automation.sheets_client.open_sheet",
        side_effect=gspread.exceptions.SpreadsheetNotFound("nope"),
    ):
        response = client.post("/api/v1/automation/google-sheet-tabs", json={"url": _VALID_URL})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unable to access this Google Sheet. Please check the sheet permissions."


def test_google_sheet_tabs_reports_no_sheets_found():
    mock_spreadsheet = MagicMock()

    with patch(
        "app.api.v1.automation.sheets_client.open_sheet", return_value=mock_spreadsheet
    ), patch(
        "app.api.v1.automation.sheets_client.list_worksheet_titles", return_value=[]
    ):
        response = client.post("/api/v1/automation/google-sheet-tabs", json={"url": _VALID_URL})

    assert response.status_code == 400
    assert response.json()["detail"] == "No sheets were found in this spreadsheet."


def test_google_sheet_tabs_reports_no_transaction_sheets():
    mock_spreadsheet = MagicMock()

    with patch(
        "app.api.v1.automation.sheets_client.open_sheet", return_value=mock_spreadsheet
    ), patch(
        "app.api.v1.automation.sheets_client.list_worksheet_titles",
        return_value=["Master", "Backup"],
    ), patch(
        "app.api.v1.automation.statement_parser.list_candidate_sheets_from_google",
        return_value=SheetCandidates(included=[], ignored=["Master", "Backup"]),
    ):
        response = client.post("/api/v1/automation/google-sheet-tabs", json={"url": _VALID_URL})

    assert response.status_code == 400
    assert response.json()["detail"] == "No sheets containing transaction data were found."


# --- POST /automation/run-google-sheet-stream ---


def _fake_stream(dry_run, rows):
    total = len(rows)
    for i in range(total):
        yield {"type": "progress", "stage": "classifying", "processed": i + 1, "total": total}
    yield {
        "type": "result",
        "result": RunResult(
            run_id="test-run",
            dry_run=dry_run,
            total_transactions=total,
            routed_deposit_withdrawal=0,
            routed_receipt_payment=total,
            needs_review=0,
            duplicates_skipped=0,
            skipped_internal_credit=0,
            skipped_collection=0,
            transactions=[],
        ),
    }


def test_run_google_sheet_stream_emits_progress_then_result():
    fake_rows = [
        {
            "SL#": "1", "TXN DATE": "22-Jul-2026", "DESCRIPTION": "test",
            "REFERENCE": "REF1", "DEBITS": "1000", "CREDITS": "", "source_sheet": "YES Rera 0377",
        },
    ]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream", side_effect=_fake_stream
    ), patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs", return_value=fake_rows
    ) as mock_parse:
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=true",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["YES Rera 0377"]},
        )

    assert response.status_code == 200
    mock_parse.assert_called_once_with("sheet-id", ["YES Rera 0377"])
    lines = [__import__("json").loads(line) for line in response.text.strip().split("\n")]
    result_events = [e for e in lines if e["type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["total_transactions"] == 1


def test_run_google_sheet_stream_requires_at_least_one_sheet():
    response = client.post(
        "/api/v1/automation/run-google-sheet-stream?dry_run=true",
        json={"spreadsheet_id": "sheet-id", "sheet_names": []},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Please select at least one sheet to process."


def test_run_google_sheet_stream_reports_inaccessible_sheet():
    with patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs",
        side_effect=gspread.exceptions.APIError(
            MagicMock(status_code=403, json=lambda: {"error": {"code": 403, "message": "forbidden", "status": "PERMISSION_DENIED"}})
        ),
    ):
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=true",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["Tab1"]},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unable to access this Google Sheet. Please check the sheet permissions."


def test_run_google_sheet_stream_filters_by_approval_column_and_writes_status_back():
    fake_rows = [{"REFERENCE": "REF1", "APPROVAL 1": "yes", "source_sheet": "Tab A", "_source_row_number": 2}]
    approved = fake_rows
    not_approved = [{"REFERENCE": "REF2", "source_sheet": "Tab A", "_source_row_number": 3}]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream", side_effect=_fake_stream
    ), patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs", return_value=fake_rows
    ), patch(
        "app.api.v1.automation.statement_parser.split_rows_by_approval",
        return_value=(approved, not_approved),
    ) as mock_split, patch(
        "app.api.v1.automation.automation_engine.write_farvision_status_back_for_run"
    ) as mock_write_back:
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=false",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["Tab A"], "approval_columns": ["APPROVAL 1"]},
        )

    assert response.status_code == 200
    mock_split.assert_called_once_with(fake_rows, ["APPROVAL 1"])
    mock_write_back.assert_called_once()
    call_args = mock_write_back.call_args.args
    assert call_args[0] == "sheet-id"
    assert call_args[2] == not_approved


def test_run_google_sheet_stream_dry_run_does_not_write_status_back():
    fake_rows = [{"REFERENCE": "REF1", "APPROVAL 1": "yes", "source_sheet": "Tab A", "_source_row_number": 2}]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream", side_effect=_fake_stream
    ), patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs", return_value=fake_rows
    ), patch(
        "app.api.v1.automation.statement_parser.split_rows_by_approval",
        return_value=(fake_rows, []),
    ), patch(
        "app.api.v1.automation.automation_engine.write_farvision_status_back_for_run"
    ) as mock_write_back:
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=true",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["Tab A"], "approval_columns": ["APPROVAL 1"]},
        )

    assert response.status_code == 200
    mock_write_back.assert_not_called()


def test_run_google_sheet_stream_no_approval_column_skips_gating_entirely():
    fake_rows = [{"REFERENCE": "REF1", "source_sheet": "Tab A"}]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream", side_effect=_fake_stream
    ), patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs", return_value=fake_rows
    ), patch(
        "app.api.v1.automation.statement_parser.split_rows_by_approval"
    ) as mock_split, patch(
        "app.api.v1.automation.automation_engine.write_farvision_status_back_for_run"
    ) as mock_write_back:
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=false",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["Tab A"]},
        )

    assert response.status_code == 200
    mock_split.assert_not_called()
    mock_write_back.assert_not_called()


def test_run_google_sheet_stream_surfaces_missing_header_as_400():
    with patch(
        "app.api.v1.automation.statement_parser.parse_google_sheet_tabs",
        side_effect=ValueError("Sheet 'Index' is missing required columns: TXN DATE"),
    ):
        response = client.post(
            "/api/v1/automation/run-google-sheet-stream?dry_run=true",
            json={"spreadsheet_id": "sheet-id", "sheet_names": ["Index"]},
        )

    assert response.status_code == 400
    assert "missing required columns" in response.json()["detail"]
