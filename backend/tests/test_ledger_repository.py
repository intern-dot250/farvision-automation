from unittest.mock import MagicMock, patch

from app.services import ledger_repository


def test_log_audit_inserts_expected_row():
    mock_client = MagicMock()

    with patch("app.services.ledger_repository.supabase_client.get_client", return_value=mock_client):
        ledger_repository.log_audit("run-1", "info", "test message", {"key": "value"})

    mock_client.table.assert_called_with("audit_log")
    insert_args = mock_client.table.return_value.insert.call_args[0][0]
    assert insert_args["run_id"] == "run-1"
    assert insert_args["level"] == "info"
    assert insert_args["message"] == "test message"
    assert insert_args["context"] == {"key": "value"}


def test_log_audit_swallows_supabase_failure():
    # Supabase being unreachable (paused project, rotated key, ...) must
    # never propagate out of log_audit - callers throughout automation_engine
    # rely on this being a safe, best-effort call.
    with patch(
        "app.services.ledger_repository.supabase_client.get_client",
        side_effect=Exception("connection refused"),
    ):
        ledger_repository.log_audit("run-1", "error", "test message", {"key": "value"})
