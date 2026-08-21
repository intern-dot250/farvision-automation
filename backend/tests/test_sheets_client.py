"""Tests for sheets_client.append_records value coercion."""

import json
from unittest.mock import MagicMock, patch

import gspread
import pytest

from app.services import sheets_client


def _api_error(status_code):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"error": {"code": status_code, "message": "boom"}}
    return gspread.exceptions.APIError(response)


def test_request_with_retry_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(sheets_client.time, "sleep", lambda seconds: None)
    calls = {"count": 0}

    def fake_original(self, method, endpoint, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise _api_error(429)
        return "ok"

    monkeypatch.setattr(sheets_client, "_original_http_client_request", fake_original)

    result = sheets_client._request_with_retry(MagicMock(), "get", "https://example.com")

    assert result == "ok"
    assert calls["count"] == 3


def test_request_with_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(sheets_client.time, "sleep", lambda seconds: None)

    def always_429(self, method, endpoint, *args, **kwargs):
        raise _api_error(429)

    monkeypatch.setattr(sheets_client, "_original_http_client_request", always_429)

    with pytest.raises(gspread.exceptions.APIError):
        sheets_client._request_with_retry(MagicMock(), "get", "https://example.com")


def test_request_with_retry_never_retries_non_429_errors(monkeypatch):
    with patch.object(sheets_client, "time") as mock_time:
        def not_found(self, method, endpoint, *args, **kwargs):
            raise _api_error(404)

        monkeypatch.setattr(sheets_client, "_original_http_client_request", not_found)

        with pytest.raises(gspread.exceptions.APIError):
            sheets_client._request_with_retry(MagicMock(), "get", "https://example.com")

    mock_time.sleep.assert_not_called()


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


def test_column_letter():
    assert sheets_client._column_letter(1) == "A"
    assert sheets_client._column_letter(8) == "H"
    assert sheets_client._column_letter(26) == "Z"
    assert sheets_client._column_letter(27) == "AA"
    assert sheets_client._column_letter(28) == "AB"


def test_append_records_coerces_amount_columns_to_int(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Debit Amount", "Credit Amount"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.append_records("sheet1", "LedgerDetails", [
        {"Link Ref Code": "1", "Debit Amount": 150000, "Credit Amount": ""}
    ])

    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == 150000
    assert isinstance(rows[0][1], int)
    assert rows[0][2] == ""


def test_append_records_applies_number_format_to_amount_columns(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Debit Amount", "Credit Amount"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.append_records("sheet1", "LedgerDetails", [
        {"Link Ref Code": "1", "Debit Amount": 150000, "Credit Amount": ""}
    ])

    format_calls = {call.args[0]: call.args[1] for call in mock_ws.format.call_args_list}
    assert format_calls["B2:B"] == {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}
    assert format_calls["C2:C"] == {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}


def test_append_records_skips_number_format_for_unrelated_tabs(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Narration": "test"}
    ])
    mock_ws.format.assert_not_called()


def test_append_records_uses_raw_input_mode(monkeypatch):
    # RAW (not USER_ENTERED) so Sheets never "smart parses" a comma-grouped
    # amount string into a number and reintroduces the column's inherited
    # decimal format - see append_records' docstring.
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Narration": "test"}
    ])
    assert mock_ws.append_rows.call_args.kwargs["value_input_option"] == "RAW"


def test_append_records_keeps_document_date_as_ddmmyyyy_string(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "22/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == "22/07/2026"
    assert isinstance(rows[0][1], str)


def test_append_records_keeps_invoice_date_as_ddmmyyyy_string(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Invoice Date": "06/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][2] == "06/07/2026"


def test_append_records_document_date_and_invoice_date_stay_in_same_format(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "01/05/2026", "Invoice Date": "01/05/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == rows[0][2] == "01/05/2026"


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


def test_get_columns_returns_row_aligned_tuples(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Payee Name", "Account Head", "Parent Account Head"]
    mock_ws.col_values.side_effect = [
        ["Payee Name", "Rajesh Kumar", "Mukesh Kumar"],
        ["Account Head", "Rajesh Kumar", "Mukesh Kumar"],
        ["Parent Account Head", "SUNDRY CREDITORS - OTHER", "SUNDRY CREDITORS - CONTRACTORS"],
    ]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.get_columns("sheet1", "LedgerDetails", ["Payee Name", "Account Head", "Parent Account Head"])

    assert result == [
        ("Rajesh Kumar", "Rajesh Kumar", "SUNDRY CREDITORS - OTHER"),
        ("Mukesh Kumar", "Mukesh Kumar", "SUNDRY CREDITORS - CONTRACTORS"),
    ]


def test_get_columns_missing_column_returns_empty_list(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Payee Name"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.get_columns("sheet1", "LedgerDetails", ["Payee Name", "Account Head"])

    assert result == []


def test_find_row_number_finds_last_matching_row(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    mock_ws.col_values.return_value = ["Link Ref Code", "1", "2", "3"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.find_row_number("sheet1", "LedgerDetails", "Link Ref Code", 3) == 4
    assert sheets_client.find_row_number("sheet1", "LedgerDetails", "Link Ref Code", 99) is None


def test_find_row_number_missing_column_returns_none(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Business Unit"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.find_row_number("sheet1", "LedgerDetails", "Link Ref Code", 3) is None


def test_find_row_numbers_bulk_resolves_many_values_from_one_column_read(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    mock_ws.col_values.return_value = ["Link Ref Code", "1", "2", "3", "4"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.find_row_numbers_bulk("sheet1", "LedgerDetails", "Link Ref Code", [2, 4, 99])

    assert result == {"2": 3, "4": 5}
    # One column read total, regardless of how many values were requested.
    mock_ws.col_values.assert_called_once()


def test_find_row_numbers_bulk_last_match_wins(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    mock_ws.col_values.return_value = ["Link Ref Code", "5", "5", "5"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.find_row_numbers_bulk("sheet1", "LedgerDetails", "Link Ref Code", [5])

    assert result == {"5": 4}


def test_find_row_numbers_bulk_missing_column_returns_empty_dict(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Business Unit"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.find_row_numbers_bulk("sheet1", "LedgerDetails", "Link Ref Code", [1]) == {}


def test_find_row_numbers_bulk_empty_values_returns_empty_dict_without_api_call(monkeypatch):
    mock_ws = MagicMock()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.find_row_numbers_bulk("sheet1", "LedgerDetails", "Link Ref Code", []) == {}
    mock_ws.col_values.assert_not_called()


def test_batch_apply_cell_flags_issues_one_batch_update_for_many_rows(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.id = 123
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    mock_spreadsheet = MagicMock()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.batch_apply_cell_flags(
        "sheet1", "LedgerDetails",
        [
            {"row_number": 5, "column": "Account Head", "dropdown_values": ["A", "B"], "note_text": "note1"},
            {"row_number": 6, "column": "Account Head", "dropdown_values": ["C"], "note_text": "note2"},
            {"row_number": 5, "column": "Parent Account Head", "formula": "=A1"},
        ],
    )

    mock_spreadsheet.batch_update.assert_called_once()
    requests = mock_spreadsheet.batch_update.call_args.args[0]["requests"]
    # 2 dropdowns + 2 notes + 1 formula = 5 requests, all in a single call.
    assert len(requests) == 5
    validation_requests = [r for r in requests if "setDataValidation" in r]
    note_requests = [r for r in requests if "updateCells" in r and r["updateCells"]["fields"] == "note"]
    formula_requests = [r for r in requests if "updateCells" in r and r["updateCells"]["fields"] == "userEnteredValue"]
    assert len(validation_requests) == 2
    assert len(note_requests) == 2
    assert len(formula_requests) == 1
    assert formula_requests[0]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]["formulaValue"] == "=A1"


def test_batch_apply_cell_flags_skips_unknown_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.id = 123
    mock_ws.row_values.return_value = ["Link Ref Code"]
    mock_spreadsheet = MagicMock()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.batch_apply_cell_flags(
        "sheet1", "LedgerDetails",
        [{"row_number": 5, "column": "Account Head", "dropdown_values": ["A"]}],
    )

    mock_spreadsheet.batch_update.assert_not_called()


def test_batch_apply_cell_flags_empty_list_is_a_no_op(monkeypatch):
    mock_spreadsheet = MagicMock()
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.batch_apply_cell_flags("sheet1", "LedgerDetails", [])

    mock_spreadsheet.batch_update.assert_not_called()


def test_add_dropdown_validation_calls_gspread_with_correct_range(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.add_dropdown_validation(
        "sheet1", "LedgerDetails", 7, "Parent Account Head", ["A", "B"]
    )

    mock_ws.add_validation.assert_called_once()
    args, kwargs = mock_ws.add_validation.call_args
    assert args[0] == "C7:C7"
    assert list(args[2]) == ["A", "B"]
    assert kwargs["showCustomUi"] is True


def test_add_dropdown_validation_no_op_for_unknown_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.add_dropdown_validation("sheet1", "LedgerDetails", 7, "Parent Account Head", ["A", "B"])

    mock_ws.add_validation.assert_not_called()


def test_add_cell_note_calls_gspread_with_correct_cell(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.add_cell_note("sheet1", "LedgerDetails", 7, "Account Head", "Verify Parent Account Head matches.")

    mock_ws.insert_note.assert_called_once_with("B7", "Verify Parent Account Head matches.")


def test_add_cell_note_no_op_for_unknown_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.add_cell_note("sheet1", "LedgerDetails", 7, "Account Head", "note")

    mock_ws.insert_note.assert_not_called()


def test_column_letter_for_returns_the_letter_for_a_known_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.column_letter_for("sheet1", "LedgerDetails", "Parent Account Head") == "C"


def test_column_letter_for_returns_none_for_unknown_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    assert sheets_client.column_letter_for("sheet1", "LedgerDetails", "Account Head") is None


def test_set_cell_formula_writes_with_user_entered_input_option(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.set_cell_formula("sheet1", "LedgerDetails", 7, "Parent Account Head", "=A1")

    mock_ws.update.assert_called_once_with(range_name="C7", values=[["=A1"]], value_input_option="USER_ENTERED")


def test_set_cell_formula_no_op_for_unknown_column(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.set_cell_formula("sheet1", "LedgerDetails", 7, "Parent Account Head", "=A1")

    mock_ws.update.assert_not_called()


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


def test_read_all_records_restores_missing_header_for_receipt_payment(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    mock_ws.get_all_records.return_value = []
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.read_all_records("rp-sheet-id", "ReceiptPayment")

    mock_ws.update.assert_called_once()
    _, kwargs = mock_ws.update.call_args
    assert kwargs["values"][0] == sheets_client._RECEIPT_PAYMENT_HEADERS["ReceiptPayment"]
    mock_ws.get_all_records.assert_called_once()
    assert result == []


def test_read_all_records_restores_missing_header_for_deposit_withdrawal(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    mock_ws.get_all_records.return_value = []
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.read_all_records("dw-sheet-id", "DepositWithdrawal")

    mock_ws.update.assert_called_once()
    _, kwargs = mock_ws.update.call_args
    assert kwargs["values"][0] == sheets_client._DEPOSIT_WITHDRAWAL_HEADERS["DepositWithdrawal"]
    assert result == []


def test_read_all_records_does_not_touch_header_when_already_present(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _make_mock_ws()
    mock_ws.get_all_records.return_value = [{"Link Ref Code": "1"}]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    result = sheets_client.read_all_records("rp-sheet-id", "ReceiptPayment")

    mock_ws.update.assert_not_called()
    assert result == [{"Link Ref Code": "1"}]


def _make_mock_worksheet(title: str, col_count: int = 25, sheet_id: int = 111):
    ws = MagicMock()
    ws.title = title
    ws.col_count = col_count
    ws.id = sheet_id
    return ws


def test_clear_all_tabs_skips_info_tab(monkeypatch):
    info_ws = _make_mock_worksheet("Info")
    data_ws = _make_mock_worksheet("ReceiptPayment")
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [info_ws, data_ws]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    cleared = sheets_client.clear_all_tabs("sheet1")

    info_ws.batch_clear.assert_not_called()
    data_ws.batch_clear.assert_called_once_with(["A2:Y"])
    assert cleared == ["ReceiptPayment"]


def test_clear_all_tabs_clears_every_non_info_tab(monkeypatch):
    ws1 = _make_mock_worksheet("ReceiptPayment", col_count=9)
    ws2 = _make_mock_worksheet("LedgerDetails", col_count=31)
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [ws1, ws2]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    cleared = sheets_client.clear_all_tabs("sheet1")

    ws1.batch_clear.assert_called_once_with(["A2:I"])
    ws2.batch_clear.assert_called_once_with(["A2:AE"])
    assert cleared == ["ReceiptPayment", "LedgerDetails"]


def test_clear_all_tabs_never_touches_header_row(monkeypatch):
    # The cleared range always starts at row 2 - row 1 (the header) is
    # structurally excluded from every batch_clear call.
    ws = _make_mock_worksheet("ReceiptPayment", col_count=5)
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [ws]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.clear_all_tabs("sheet1")

    cleared_range = ws.batch_clear.call_args.args[0][0]
    assert cleared_range.startswith("A2:")


def test_clear_all_tabs_also_clears_data_validation(monkeypatch):
    # values.batchClear only erases cell values, never validation metadata -
    # a leftover dropdown from a previous run must not survive a clear and
    # silently misapply to unrelated future data.
    ws1 = _make_mock_worksheet("ReceiptPayment", col_count=9, sheet_id=111)
    ws2 = _make_mock_worksheet("LedgerDetails", col_count=31, sheet_id=222)
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [ws1, ws2]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.clear_all_tabs("sheet1")

    mock_spreadsheet.batch_update.assert_called_once()
    requests = mock_spreadsheet.batch_update.call_args.args[0]["requests"]
    validation_requests = [r for r in requests if "setDataValidation" in r]
    assert len(validation_requests) == 2
    for request, sheet_id, col_count in zip(validation_requests, (111, 222), (9, 31)):
        validation_range = request["setDataValidation"]["range"]
        assert validation_range["sheetId"] == sheet_id
        assert validation_range["startRowIndex"] == 1
        assert validation_range["startColumnIndex"] == 0
        assert validation_range["endColumnIndex"] == col_count
        assert "rule" not in request["setDataValidation"]


def test_clear_all_tabs_also_clears_cell_notes(monkeypatch):
    # A cell note (e.g. the ambiguous-Account-Head verification note) is
    # separate metadata from both values and validation - values.batchClear
    # and the setDataValidation clear above don't touch it, so it must be
    # cleared explicitly or it survives a "Clear Sheet Data" and silently
    # sits on whatever unrelated transaction a later run writes into that
    # same row.
    ws1 = _make_mock_worksheet("ReceiptPayment", col_count=9, sheet_id=111)
    ws2 = _make_mock_worksheet("LedgerDetails", col_count=31, sheet_id=222)
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [ws1, ws2]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.clear_all_tabs("sheet1")

    requests = mock_spreadsheet.batch_update.call_args.args[0]["requests"]
    note_requests = [r for r in requests if "repeatCell" in r]
    assert len(note_requests) == 2
    for request, sheet_id, col_count in zip(note_requests, (111, 222), (9, 31)):
        repeat_cell = request["repeatCell"]
        assert repeat_cell["fields"] == "note"
        assert repeat_cell["cell"] == {}
        note_range = repeat_cell["range"]
        assert note_range["sheetId"] == sheet_id
        assert note_range["startRowIndex"] == 1
        assert note_range["startColumnIndex"] == 0
        assert note_range["endColumnIndex"] == col_count


def test_clear_all_tabs_skips_validation_clear_for_info_only_spreadsheet(monkeypatch):
    info_ws = _make_mock_worksheet("Info")
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheets.return_value = [info_ws]
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.clear_all_tabs("sheet1")

    mock_spreadsheet.batch_update.assert_not_called()


def test_read_all_records_raises_for_unknown_sheet_with_missing_header(monkeypatch):
    monkeypatch.setattr(sheets_client, "get_settings", lambda: _FakeSettings())
    mock_ws = _mock_ws_with_empty_header()
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    try:
        sheets_client.read_all_records("some-other-sheet-id", "MysteryTab")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "MysteryTab" in str(exc)
    mock_ws.get_all_records.assert_not_called()


def test_get_worksheet_only_opens_the_spreadsheet_once_per_process(monkeypatch):
    sheets_client._get_worksheet_cached.cache_clear()
    mock_ws = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_ws
    open_calls = []
    monkeypatch.setattr(
        sheets_client, "open_sheet", lambda sid: (open_calls.append(sid), mock_spreadsheet)[1]
    )

    sheets_client.get_worksheet("sheet1", "LedgerDetails")
    sheets_client.get_worksheet("sheet1", "LedgerDetails")
    sheets_client.get_worksheet("sheet1", "LedgerDetails")

    assert mock_spreadsheet.worksheet.call_count == 1
    sheets_client._get_worksheet_cached.cache_clear()


def test_clear_worksheet_cache_forces_a_re_fetch(monkeypatch):
    sheets_client._get_worksheet_cached.cache_clear()
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = MagicMock()
    monkeypatch.setattr(sheets_client, "open_sheet", lambda sid: mock_spreadsheet)

    sheets_client.get_worksheet("sheet1", "LedgerDetails")
    sheets_client.clear_worksheet_cache()
    sheets_client.get_worksheet("sheet1", "LedgerDetails")

    assert mock_spreadsheet.worksheet.call_count == 2


def test_header_is_only_fetched_once_across_multiple_helper_calls(monkeypatch):
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Link Ref Code", "Account Head", "Parent Account Head"]
    monkeypatch.setattr(sheets_client, "get_worksheet", lambda sid, wn: mock_ws)

    sheets_client.find_row_number("sheet1", "LedgerDetails", "Account Head", "X")
    sheets_client.add_dropdown_validation("sheet1", "LedgerDetails", 5, "Account Head", ["A", "B"])
    sheets_client.add_cell_note("sheet1", "LedgerDetails", 5, "Account Head", "note")
    sheets_client.set_cell_formula("sheet1", "LedgerDetails", 5, "Parent Account Head", "=1")
    sheets_client.column_letter_for("sheet1", "LedgerDetails", "Account Head")

    assert mock_ws.row_values.call_count == 1


def test_header_cache_is_per_worksheet(monkeypatch):
    ledger_ws = MagicMock()
    ledger_ws.row_values.return_value = ["Link Ref Code", "Account Head"]
    receipt_ws = MagicMock()
    receipt_ws.row_values.return_value = ["Link Ref Code", "Narration"]

    def _get_worksheet(sid, wn):
        return ledger_ws if wn == "LedgerDetails" else receipt_ws

    monkeypatch.setattr(sheets_client, "get_worksheet", _get_worksheet)

    assert sheets_client.column_letter_for("sheet1", "LedgerDetails", "Account Head") == "B"
    assert sheets_client.column_letter_for("sheet1", "ReceiptPayment", "Narration") == "B"
    assert sheets_client.column_letter_for("sheet1", "ReceiptPayment", "Account Head") is None
