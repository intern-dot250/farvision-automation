import io
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services.automation_engine import RunResult

client = TestClient(app)


def _build_xlsx(sheets: dict[str, list[dict]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


def test_run_upload_stream_emits_progress_then_result():
    csv_content = (
        "SL#,TXN DATE,DESCRIPTION,REFERENCE,DEBITS,CREDITS\n"
        "1,22-Jul-2026,test,REF1,1000,\n"
        "2,22-Jul-2026,test,REF2,500,\n"
    ).encode()

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream",
        side_effect=_fake_stream,
    ):
        response = client.post(
            "/api/v1/automation/run-upload-stream?dry_run=true",
            files={"file": ("statement.csv", csv_content, "text/csv")},
        )

    assert response.status_code == 200
    lines = [__import__("json").loads(line) for line in response.text.strip().split("\n")]

    progress_events = [e for e in lines if e["type"] == "progress"]
    result_events = [e for e in lines if e["type"] == "result"]

    assert len(progress_events) == 2
    assert progress_events[-1]["processed"] == 2
    assert progress_events[-1]["total"] == 2
    assert len(result_events) == 1
    assert result_events[0]["total_transactions"] == 2
    assert result_events[0]["routed_receipt_payment"] == 2


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


def test_run_upload_stream_passes_sheet_names_to_parser():
    """The route handler forwards sheet_names to parse_statement_file."""

    fake_rows = [
        {
            "SL#": "1",
            "TXN DATE": "22-Jul-2026",
            "DESCRIPTION": "test",
            "REFERENCE": "REF1",
            "DEBITS": "1000",
            "CREDITS": "",
        },
    ]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream",
        side_effect=_fake_stream,
    ), patch(
        "app.api.v1.automation.statement_parser.parse_statement_file",
        return_value=fake_rows,
    ) as mock_parse:
        content = _build_xlsx({
            "YES Rera 0377": [
                {
                    "SL#": "1", "TXN DATE": "22-Jul-2026",
                    "DESCRIPTION": "test",
                    "REFERENCE": "REF1", "DEBITS": "1000", "CREDITS": "",
                }
            ],
        })

        # Build multipart body with repeated sheet_names fields
        response = client.post(
            "/api/v1/automation/run-upload-stream?dry_run=true",
            data={"sheet_names": ["YES Rera 0377", "YES IDW 0490"]},
            files={"file": ("statement.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    call_kwargs = mock_parse.call_args.kwargs
    assert call_kwargs["sheet_names"] == ["YES Rera 0377", "YES IDW 0490"]


def test_run_upload_stream_gates_rows_by_approval_columns():
    fake_rows = [
        {"SL#": "1", "REFERENCE": "REF1", "Auth MB": "Yes"},
        {"SL#": "2", "REFERENCE": "REF2", "Auth MB": "No"},
    ]
    approved_rows = [fake_rows[0]]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream",
        side_effect=_fake_stream,
    ) as mock_run, patch(
        "app.api.v1.automation.statement_parser.parse_statement_file", return_value=fake_rows
    ), patch(
        "app.api.v1.automation.statement_parser.split_rows_by_approval",
        return_value=(approved_rows, [fake_rows[1]]),
    ) as mock_split:
        content = _build_xlsx({"YES Master 0264": fake_rows})
        response = client.post(
            "/api/v1/automation/run-upload-stream?dry_run=true",
            data={"approval_columns": ["Auth MB"]},
            files={"file": ("statement.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    mock_split.assert_called_once_with(fake_rows, ["Auth MB"])
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["rows"] == approved_rows


def test_run_upload_stream_skips_gating_when_no_approval_columns_given():
    fake_rows = [{"SL#": "1", "REFERENCE": "REF1"}]

    with patch(
        "app.api.v1.automation.automation_engine.run_automation_stream",
        side_effect=_fake_stream,
    ) as mock_run, patch(
        "app.api.v1.automation.statement_parser.parse_statement_file", return_value=fake_rows
    ), patch(
        "app.api.v1.automation.statement_parser.split_rows_by_approval"
    ) as mock_split:
        content = _build_xlsx({"YES Master 0264": fake_rows})
        response = client.post(
            "/api/v1/automation/run-upload-stream?dry_run=true",
            files={"file": ("statement.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    mock_split.assert_not_called()
    assert mock_run.call_args.kwargs["rows"] == fake_rows
