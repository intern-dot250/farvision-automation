import io

import pandas as pd
import pytest

from app.services.statement_parser import parse_statement_file


def test_parses_csv_with_required_columns():
    csv_content = (
        "SL#,TXN DATE,DESCRIPTION,REFERENCE,DEBITS,CREDITS\n"
        "1,22-Jul-2026,YIB-NEFT-REF1-Some Payee-SBIN0007204-Contractor-STATE BANK OF INDIA,REF1,1000,\n"
    ).encode()

    rows = parse_statement_file("statement.csv", csv_content)

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"
    assert rows[0]["DEBITS"] == "1000"


def test_parses_xlsx_with_required_columns():
    df = pd.DataFrame(
        [
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Some Payee-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]
    )
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    content = buffer.getvalue()

    rows = parse_statement_file("statement.xlsx", content)

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


def test_missing_required_column_raises_value_error():
    csv_content = "SL#,DESCRIPTION\n1,test\n".encode()

    with pytest.raises(ValueError, match="missing required columns"):
        parse_statement_file("statement.csv", csv_content)


def test_blank_cells_become_empty_strings():
    csv_content = (
        "TXN DATE,DESCRIPTION,REFERENCE,DEBITS,CREDITS,HEAD\n"
        "22-Jul-2026,desc,REF1,1000,,\n"
    ).encode()

    rows = parse_statement_file("statement.csv", csv_content)

    assert rows[0]["CREDITS"] == ""
    assert rows[0]["HEAD"] == ""


def _two_sheet_workbook() -> bytes:
    df = pd.DataFrame(
        [
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Some Payee-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        df.to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([{"unrelated": "no transaction columns here"}]).to_excel(
            writer, sheet_name="Index", index=False
        )
    return buffer.getvalue()


def test_sheet_name_lookup_is_case_and_whitespace_insensitive():
    content = _two_sheet_workbook()

    rows = parse_statement_file("statement.xlsx", content, sheet_name="  yes   rera 0377  ")

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


def test_unknown_sheet_name_lists_available_sheets():
    content = _two_sheet_workbook()

    with pytest.raises(ValueError, match="not found in uploaded file"):
        parse_statement_file("statement.xlsx", content, sheet_name="Nonexistent Tab")
