"""Tests for sheets_client.append_records value coercion."""

import json
from unittest.mock import MagicMock

from app.services import sheets_client


def _make_mock_ws():
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = [
        "Link Ref Code",
        "Document Date",
        "Invoice Date",
        "Detail Link Ref Code",
        "Narration",
    ]
    return mock_ws


def _setup_mocks(monkeypatch):
    mock_ws = _make_mock_ws()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)
    return mock_ws


def test_append_records_coerces_link_ref_code_to_int(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "42", "Document Date": "01/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][0] == 42
    assert isinstance(rows[0][0], int)


def test_append_records_coerces_document_date_to_iso_string(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "22/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == "2026-07-22"
    assert isinstance(rows[0][1], str)


def test_append_records_coerces_invoice_date_to_iso_string(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Invoice Date": "06/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][2] == "2026-07-06"


def test_append_records_output_is_json_serializable(monkeypatch):
    # Regression test: a native `date` object previously crashed gspread's
    # real HTTP request with "Object of type date is not JSON serializable" -
    # the mock in other tests wouldn't catch that, since it never attempts
    # to serialize anything. This does.
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {
            "Link Ref Code": "1",
            "Document Date": "22/07/2026",
            "Invoice Date": "06/07/2026",
            "Detail Link Ref Code": "1",
            "Narration": "test",
        }
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    json.dumps(rows)


def test_append_records_keeps_text_columns_as_strings(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "01/07/2026", "Narration": "hello"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][4] == "hello"
    assert isinstance(rows[0][4], str)


def test_append_records_skips_invalid_date_values(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == ""


def test_append_records_empty_list_returns_early(monkeypatch):
    mock_ws = _make_mock_ws()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)
    sheets_client.append_records("sheet1", "Sheet1", [])
    mock_ws.append_rows.assert_not_called()


def test_count_data_rows_excludes_header(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.col_values.return_value = ["Link Ref Code", "1", "2", "3"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.count_data_rows("sheet1", "Sheet1") == 3


def test_count_data_rows_header_only_returns_zero(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.col_values.return_value = ["Link Ref Code"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.count_data_rows("sheet1", "Sheet1") == 0


def test_get_column_values_returns_non_empty_values(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Business Unit"]
    mock_ws.col_values.return_value = ["Link Ref Code", "1", "2", "", "3"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.get_column_values("sheet1", "Sheet1", "Link Ref Code")

    assert result == {"1", "2", "3"}


def test_get_column_values_missing_column_returns_empty_set(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Business Unit"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.get_column_values("sheet1", "Sheet1", "Link Ref Code")

    assert result == set()


class _FakeSettings:
    RECEIPT_PAYMENT_SHEET_ID = "rp-sheet-id"
    DEPOSIT_WITHDRAWAL_SHEET_ID = "dw-sheet-id"


def _mock_ws_with_empty_header():
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = []
    return mock_ws


def test_append_records_restores_missing_header_for_receipt_payment_ledger_details(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.append_records(
        "rp-sheet-id", "LedgerDetails", [{"Link Ref Code": "1", "Account Head": "RAKIBA BIBI"}]
    )

    mock_ws.update.assert_called_once()
    _, kwargs = mock_ws.update.call_args
    written_header = kwargs["values"][0]
    assert written_header == sheets_client._RECEIPT_PAYMENT_HEADERS["LedgerDetails"]
    assert len(written_header) == 31
    mock_ws.append_rows.assert_called_once()


def test_append_records_restores_missing_header_for_deposit_withdrawal_ledger_details(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.append_records(
        "dw-sheet-id", "LedgerDetails", [{"Link Ref Code": "1", "Account Head": "Internal Transfer"}]
    )

    mock_ws.update.assert_called_once()
    _, kwargs = mock_ws.update.call_args
    written_header = kwargs["values"][0]
    assert written_header == sheets_client._DEPOSIT_WITHDRAWAL_HEADERS["LedgerDetails"]
    assert len(written_header) == 14
    mock_ws.append_rows.assert_called_once()


def test_append_records_does_not_touch_header_when_already_present(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _make_mock_ws()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.append_records("rp-sheet-id", "LedgerDetails", [{"Link Ref Code": "1", "Narration": "test"}])

    mock_ws.update.assert_not_called()


def test_append_records_raises_for_unknown_sheet_with_missing_header(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    try:
        sheets_client.append_records("some-other-sheet-id", "MysteryTab", [{"Link Ref Code": "1"}])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "MysteryTab" in str(exc)
    mock_ws.append_rows.assert_not_called()
