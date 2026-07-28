from unittest.mock import MagicMock, patch

from app.services import history_repository


def test_list_runs_merges_started_and_completed_rows():
    mock_response = MagicMock()
    mock_response.data = [
        {
            "run_id": "run-1",
            "message": "Automation run started",
            "created_at": "2026-07-25T10:00:00Z",
            "context": {"dry_run": False},
        },
        {
            "run_id": "run-1",
            "message": "Automation run completed",
            "created_at": "2026-07-25T10:00:05Z",
            "context": {
                "routed_receipt_payment": 10,
                "routed_deposit_withdrawal": 2,
                "needs_review": 1,
                "duplicates_skipped": 0,
            },
        },
    ]

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.in_.return_value.order.return_value.execute.return_value = (
        mock_response
    )

    with patch("app.services.history_repository.supabase_client.get_client", return_value=mock_client):
        runs = history_repository.list_runs()

    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == "run-1"
    assert run["dry_run"] is False
    assert run["routed_receipt_payment"] == 10
    assert run["needs_review"] == 1


def test_get_stats_aggregates_counts():
    mock_client = MagicMock()

    def make_count(value):
        result = MagicMock()
        result.count = value
        query = MagicMock()
        query.execute.return_value = result
        query.eq.return_value = query
        return query

    mock_client.table.return_value.select.side_effect = [
        make_count(15),
        make_count(11),
        make_count(3),
    ]

    with patch("app.services.history_repository.supabase_client.get_client", return_value=mock_client):
        stats = history_repository.get_stats()

    assert stats["total_processed"] == 15
    assert stats["total_receipt_payment"] == 11
    assert stats["total_deposit_withdrawal"] == 3
