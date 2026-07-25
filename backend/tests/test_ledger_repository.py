from unittest.mock import MagicMock, patch

from app.services import ledger_repository


def test_is_already_processed_batch_returns_matched_refs():
    mock_response = MagicMock()
    mock_response.data = [
        {"reference": "YESME123"},
        {"reference": "YESME456"},
    ]

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.in_.return_value.execute.return_value = (
        mock_response
    )

    with patch("app.services.ledger_repository.supabase_client.get_client", return_value=mock_client):
        result = ledger_repository.is_already_processed_batch(["YESME123", "YESME456", "YESME789"])

    assert result == {"YESME123", "YESME456"}


def test_is_already_processed_batch_returns_empty_set_for_no_matches():
    mock_response = MagicMock()
    mock_response.data = []

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.in_.return_value.execute.return_value = (
        mock_response
    )

    with patch("app.services.ledger_repository.supabase_client.get_client", return_value=mock_client):
        result = ledger_repository.is_already_processed_batch(["YESME123", "YESME456"])

    assert result == set()


def test_is_already_processed_batch_returns_empty_set_for_empty_input():
    result = ledger_repository.is_already_processed_batch([])
    assert result == set()


def test_mark_processed_inserts_expected_row():
    mock_client = MagicMock()

    with patch("app.services.ledger_repository.supabase_client.get_client", return_value=mock_client):
        ledger_repository.mark_processed(
            reference="YESME123",
            sl_no="336",
            description="test",
            head="Contractor",
            destination="receipt_payment",
            link_ref_code=5,
        )

    mock_client.table.assert_called_with("processed_transactions")
    insert_args = mock_client.table.return_value.insert.call_args[0][0]
    assert insert_args["reference"] == "YESME123"
    assert insert_args["link_ref_code"] == 5
