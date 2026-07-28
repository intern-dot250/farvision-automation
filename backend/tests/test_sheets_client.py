"""Tests for sheets_client.append_records value coercion."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

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


def test_append_records_coerces_document_date_to_date(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Document Date": "22/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][1] == date(2026, 7, 22)
    assert isinstance(rows[0][1], date)


def test_append_records_coerces_invoice_date_to_date(monkeypatch):
    mock_ws = _setup_mocks(monkeypatch)
    sheets_client.append_records("sheet1", "Sheet1", [
        {"Link Ref Code": "1", "Invoice Date": "06/07/2026", "Narration": "test"}
    ])
    rows = mock_ws.append_rows.call_args.args[0]
    assert rows[0][2] == date(2026, 7, 6)


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
