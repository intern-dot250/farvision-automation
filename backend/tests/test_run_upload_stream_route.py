import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.automation_engine import RunResult

client = TestClient(app)


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
            transactions=[],
        ),
    }


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
    lines = [json.loads(line) for line in response.text.strip().split("\n")]

    progress_events = [e for e in lines if e["type"] == "progress"]
    result_events = [e for e in lines if e["type"] == "result"]

    assert len(progress_events) == 2
    assert progress_events[-1]["processed"] == 2
    assert progress_events[-1]["total"] == 2
    assert len(result_events) == 1
    assert result_events[0]["total_transactions"] == 2
    assert result_events[0]["routed_receipt_payment"] == 2
