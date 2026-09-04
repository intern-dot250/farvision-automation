import io
from unittest.mock import patch

import pandas as pd
import pytest

from app.services.statement_parser import (
    FARVISION_STATUS_COLUMN,
    list_candidate_sheets,
    list_candidate_sheets_from_google,
    parse_google_sheet_tabs,
    parse_statement_file,
    split_rows_by_approval,
)


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


def test_fully_blank_rows_are_dropped():
    csv_content = (
        "SL#,TXN DATE,DESCRIPTION,REFERENCE,DEBITS,CREDITS\n"
        "1,22-Jul-2026,YIB-NEFT-REF1-Some Payee-SBIN0007204-Contractor-STATE BANK OF INDIA,REF1,1000,\n"
        ",,,,,\n"
        "2,23-Jul-2026,YIB-NEFT-REF2-Other Payee-SBIN0007204-Contractor-STATE BANK OF INDIA,REF2,500,\n"
    ).encode()

    rows = parse_statement_file("statement.csv", csv_content)

    assert len(rows) == 2
    assert [r["SL#"] for r in rows] == ["1", "2"]


def test_brought_forward_rows_are_dropped():
    csv_content = (
        "SL#,TXN DATE,DESCRIPTION,REFERENCE,DEBITS,CREDITS\n"
        "1,01-Apr-2026,B/F,,,\n"
        "2,22-Jul-2026,YIB-NEFT-REF1-Some Payee-SBIN0007204-Contractor-STATE BANK OF INDIA,REF1,1000,\n"
        "3,23-Jul-2026,b/f balance carried forward,,,\n"
    ).encode()

    rows = parse_statement_file("statement.csv", csv_content)

    assert len(rows) == 1
    assert rows[0]["SL#"] == "2"


def test_fully_blank_rows_are_dropped_even_with_source_sheet_tagged():
    # Regression: source_sheet is set on every row (including blank ones)
    # before the blank-row filter runs, so the filter must ignore it -
    # otherwise every row looks "non-blank" and nothing gets dropped.
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame(
            [
                {
                    "SL#": "1",
                    "TXN DATE": "22-Jul-2026",
                    "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                    "REFERENCE": "REF1",
                    "DEBITS": "1000",
                    "CREDITS": "",
                },
                {
                    "SL#": "",
                    "TXN DATE": "",
                    "DESCRIPTION": "",
                    "REFERENCE": "",
                    "DEBITS": "",
                    "CREDITS": "",
                },
            ]
        ).to_excel(writer, sheet_name="YES AH IDW 2457", index=False)

    rows = parse_statement_file("statement.xlsx", buffer.getvalue())

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"
    assert rows[0]["source_sheet"] == "YES AH IDW 2457"


def test_spacer_row_dropped_even_with_stray_content_in_unrelated_column():
    # Regression: a spacer row can carry leftover content in a column that
    # isn't actually transaction data (a note, a stray SL# tag, etc.) - it
    # must still be dropped, since none of the REQUIRED_COLUMNS have
    # anything in them.
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame(
            [
                {
                    "SL#": "1",
                    "TXN DATE": "22-Jul-2026",
                    "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                    "REFERENCE": "REF1",
                    "DEBITS": "1000",
                    "CREDITS": "",
                },
                {
                    "SL#": "some stray note left by accounts",
                    "TXN DATE": "",
                    "DESCRIPTION": "",
                    "REFERENCE": "",
                    "DEBITS": "",
                    "CREDITS": "",
                },
            ]
        ).to_excel(writer, sheet_name="YES Master 0264", index=False)

    rows = parse_statement_file("statement.xlsx", buffer.getvalue())

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


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


def test_list_candidate_sheets_returns_only_matching_tabs():
    content = _two_sheet_workbook()

    result = list_candidate_sheets("statement.xlsx", content)

    assert result.included == ["YES Rera 0377"]


def test_list_candidate_sheets_reports_ignored_tabs():
    content = _two_sheet_workbook()

    result = list_candidate_sheets("statement.xlsx", content)

    assert result.ignored == ["Index"]


def test_multiple_sheets_with_data_are_concatenated():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF2-Payee2-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF2",
                "DEBITS": "500",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES IDW 0490", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue())

    assert len(rows) == 2
    assert rows[0]["REFERENCE"] == "REF1"
    assert rows[1]["REFERENCE"] == "REF2"


def test_multiple_sheets_non_txn_sheets_are_ignored():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([{"unrelated": "no transaction columns here"}]).to_excel(
            writer, sheet_name="Index", index=False
        )
        pd.DataFrame([{"Summary": "totals"}]).to_excel(
            writer, sheet_name="Dashboard", index=False
        )

    rows = parse_statement_file("multi.xlsx", buffer.getvalue())

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


def test_list_candidate_sheets_empty_for_csv():
    result = list_candidate_sheets("statement.csv", b"a,b\n1,2\n")

    assert result.included == []
    assert result.ignored == []


def test_sheet_names_selects_specific_tabs():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF2-Payee2-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF2",
                "DEBITS": "500",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES IDW 0490", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=["YES Rera 0377"])

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


def test_sheet_names_selects_multiple_tabs():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF2-Payee2-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF2",
                "DEBITS": "500",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES IDW 0490", index=False)
        pd.DataFrame([{"no": "data"}]).to_excel(writer, sheet_name="Dashboard", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=["YES Rera 0377", "YES IDW 0490"])

    assert len(rows) == 2
    assert rows[0]["REFERENCE"] == "REF1"
    assert rows[1]["REFERENCE"] == "REF2"


def test_sheet_names_tags_source_sheet_correctly():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF2-Payee2-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF2",
                "DEBITS": "500",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES IDW 0490", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=["YES IDW 0490", "YES Rera 0377"])

    assert len(rows) == 2
    assert rows[0]["source_sheet"] == "YES IDW 0490"
    assert rows[1]["source_sheet"] == "YES Rera 0377"


def test_sheet_names_is_case_and_whitespace_insensitive():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=["  yes  rera  0377  "])

    assert len(rows) == 1
    assert rows[0]["source_sheet"] == "YES Rera 0377"


def test_sheet_names_unknown_tab_raises_value_error():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([{"SL#": "1", "TXN DATE": "x", "DESCRIPTION": "x", "REFERENCE": "REF1", "DEBITS": "", "CREDITS": ""}]).to_excel(
            writer, sheet_name="YES Rera 0377", index=False
        )

    with pytest.raises(ValueError, match="not found in uploaded file"):
        parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=["Nonexistent Tab"])


def test_sheet_names_empty_list_is_treated_as_no_filter():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF1-Payee1-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "YIB-NEFT-REF2-Payee2-SBIN0007204-Contractor-STATE BANK OF INDIA",
                "REFERENCE": "REF2",
                "DEBITS": "500",
                "CREDITS": "",
            }
        ]).to_excel(writer, sheet_name="YES IDW 0490", index=False)

    rows = parse_statement_file("multi.xlsx", buffer.getvalue(), sheet_names=[])

    assert len(rows) == 2


# --- list_candidate_sheets_from_google / parse_google_sheet_tabs: same
# header-detection logic as the upload path, sourced from a live Google
# Sheet (via sheets_client) instead of uploaded file bytes ---


_TXN_HEADER_ROW = ["SL#", "TXN DATE", "DESCRIPTION", "REFERENCE", "DEBITS", "CREDITS"]


def test_list_candidate_sheets_from_google_classifies_included_and_ignored():
    values_by_tab = {
        "YES Rera 0377": [_TXN_HEADER_ROW, ["1", "22-Jul-2026", "test", "REF1", "1000", ""]],
        "Index": [["unrelated"], ["no transaction columns"]],
    }

    with patch(
        "app.services.statement_parser.sheets_client.list_worksheet_titles",
        return_value=["YES Rera 0377", "Index"],
    ), patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        side_effect=lambda sheet_id, name, row_limit=None: values_by_tab[name],
    ):
        result = list_candidate_sheets_from_google("sheet-id")

    assert result.included == ["YES Rera 0377"]
    assert result.ignored == ["Index"]


def test_list_candidate_sheets_from_google_handles_empty_tab():
    with patch(
        "app.services.statement_parser.sheets_client.list_worksheet_titles",
        return_value=["Blank Tab"],
    ), patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        return_value=[],
    ):
        result = list_candidate_sheets_from_google("sheet-id")

    assert result.included == []
    assert result.ignored == ["Blank Tab"]


def test_parse_google_sheet_tabs_tags_source_sheet_and_returns_rows():
    values_by_tab = {
        "YES Rera 0377": [_TXN_HEADER_ROW, ["1", "22-Jul-2026", "test", "REF1", "1000", ""]],
        "YES IDW 0490": [_TXN_HEADER_ROW, ["1", "22-Jul-2026", "test", "REF2", "500", ""]],
    }

    with patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        side_effect=lambda sheet_id, name, row_limit=None: values_by_tab[name],
    ):
        rows = parse_google_sheet_tabs("sheet-id", ["YES Rera 0377", "YES IDW 0490"])

    assert len(rows) == 2
    assert rows[0]["REFERENCE"] == "REF1"
    assert rows[0]["source_sheet"] == "YES Rera 0377"
    assert rows[1]["REFERENCE"] == "REF2"
    assert rows[1]["source_sheet"] == "YES IDW 0490"


def test_parse_google_sheet_tabs_drops_blank_and_brought_forward_rows():
    values = [
        _TXN_HEADER_ROW,
        ["1", "22-Jul-2026", "test", "REF1", "1000", ""],
        ["", "", "", "", "", ""],
        ["2", "22-Jul-2026", "B/F Balance", "REF2", "500", ""],
    ]

    with patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        return_value=values,
    ):
        rows = parse_google_sheet_tabs("sheet-id", ["YES Rera 0377"])

    assert len(rows) == 1
    assert rows[0]["REFERENCE"] == "REF1"


def test_parse_google_sheet_tabs_missing_header_raises_value_error():
    with patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        return_value=[["unrelated", "columns"], ["a", "b"]],
    ):
        with pytest.raises(ValueError, match="missing required columns"):
            parse_google_sheet_tabs("sheet-id", ["Index"])


def test_list_candidate_sheets_from_google_discovers_approval_columns():
    header_with_approvals = _TXN_HEADER_ROW + ["APPROVAL 1", "APPROVAL 2", "APPROVAL 3"]
    values_by_tab = {
        "YES Rera 0377": [header_with_approvals, ["1", "22-Jul-2026", "test", "REF1", "1000", "", "", "", ""]],
        "Index": [["unrelated"], ["no transaction columns"]],
    }

    with patch(
        "app.services.statement_parser.sheets_client.list_worksheet_titles",
        return_value=["YES Rera 0377", "Index"],
    ), patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        side_effect=lambda sheet_id, name, row_limit=None: values_by_tab[name],
    ):
        result = list_candidate_sheets_from_google("sheet-id")

    assert result.approval_columns == ["APPROVAL 1", "APPROVAL 2", "APPROVAL 3"]


def test_list_candidate_sheets_from_google_discovers_auth_code_approval_columns():
    # The real Bank Statement Processor tabs (confirmed live) use "Auth MB" /
    # "Auth MK" / "Auth NM" - a different naming convention than "APPROVAL n"
    # - both must be discovered by the same dynamic scan.
    header_with_auth_columns = _TXN_HEADER_ROW + ["Auth MB", "Auth MK", "Auth NM"]
    values_by_tab = {
        "YES Master 0264": [header_with_auth_columns, ["1", "22-Jul-2026", "test", "REF1", "1000", "", "", "", ""]],
    }

    with patch(
        "app.services.statement_parser.sheets_client.list_worksheet_titles",
        return_value=["YES Master 0264"],
    ), patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        side_effect=lambda sheet_id, name, row_limit=None: values_by_tab[name],
    ):
        result = list_candidate_sheets_from_google("sheet-id")

    assert result.approval_columns == ["Auth MB", "Auth MK", "Auth NM"]


def test_list_candidate_sheets_from_google_no_approval_columns_is_empty_list():
    values_by_tab = {
        "YES Rera 0377": [_TXN_HEADER_ROW, ["1", "22-Jul-2026", "test", "REF1", "1000", ""]],
    }

    with patch(
        "app.services.statement_parser.sheets_client.list_worksheet_titles",
        return_value=["YES Rera 0377"],
    ), patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        side_effect=lambda sheet_id, name, row_limit=None: values_by_tab[name],
    ):
        result = list_candidate_sheets_from_google("sheet-id")

    assert result.approval_columns == []


def test_parse_google_sheet_tabs_tags_source_row_number():
    values = [
        _TXN_HEADER_ROW,
        ["1", "22-Jul-2026", "test", "REF1", "1000", ""],
        ["2", "22-Jul-2026", "test2", "REF2", "500", ""],
    ]

    with patch(
        "app.services.statement_parser.sheets_client.get_worksheet_values",
        return_value=values,
    ):
        rows = parse_google_sheet_tabs("sheet-id", ["YES Rera 0377"])

    # Header is sheet row 1, so the first data row is sheet row 2, etc.
    assert rows[0]["_source_row_number"] == 2
    assert rows[1]["_source_row_number"] == 3


def test_split_rows_by_approval_separates_blank_and_filled():
    rows = [
        {"REFERENCE": "REF1", "APPROVAL 1": "Yes"},
        {"REFERENCE": "REF2", "APPROVAL 1": ""},
        {"REFERENCE": "REF3", "APPROVAL 1": "   "},
    ]

    approved, not_approved = split_rows_by_approval(rows, ["APPROVAL 1"])

    assert [r["REFERENCE"] for r in approved] == ["REF1"]
    assert [r["REFERENCE"] for r in not_approved] == ["REF2", "REF3"]


def test_split_rows_by_approval_rejects_explicit_no():
    # "No" is a non-blank value but an explicit rejection - must NOT be
    # treated as approved just because the cell isn't empty.
    rows = [
        {"REFERENCE": "REF1", "APPROVAL 1": "Yes"},
        {"REFERENCE": "REF2", "APPROVAL 1": "No"},
    ]

    approved, not_approved = split_rows_by_approval(rows, ["APPROVAL 1"])

    assert [r["REFERENCE"] for r in approved] == ["REF1"]
    assert [r["REFERENCE"] for r in not_approved] == ["REF2"]


def test_split_rows_by_approval_matches_yes_case_insensitively_and_trimmed():
    rows = [
        {"REFERENCE": "REF1", "APPROVAL 1": "YES"},
        {"REFERENCE": "REF2", "APPROVAL 1": " yes "},
        {"REFERENCE": "REF3", "APPROVAL 1": "yEs"},
    ]

    approved, not_approved = split_rows_by_approval(rows, ["APPROVAL 1"])

    assert [r["REFERENCE"] for r in approved] == ["REF1", "REF2", "REF3"]
    assert not_approved == []


def test_split_rows_by_approval_requires_all_selected_columns_filled():
    rows = [
        {"REFERENCE": "REF1", "APPROVAL 1": "yes", "APPROVAL 2": "yes"},
        {"REFERENCE": "REF2", "APPROVAL 1": "yes", "APPROVAL 2": ""},
        {"REFERENCE": "REF3", "APPROVAL 1": "", "APPROVAL 2": "yes"},
    ]

    approved, not_approved = split_rows_by_approval(rows, ["APPROVAL 1", "APPROVAL 2"])

    assert [r["REFERENCE"] for r in approved] == ["REF1"]
    assert [r["REFERENCE"] for r in not_approved] == ["REF2", "REF3"]


def test_split_rows_by_approval_excludes_already_exported_rows():
    rows = [
        {"REFERENCE": "REF1", "APPROVAL 1": "yes", FARVISION_STATUS_COLUMN: "Exported"},
        {"REFERENCE": "REF2", "APPROVAL 1": "yes"},
        {"REFERENCE": "REF3", "APPROVAL 1": "", FARVISION_STATUS_COLUMN: "Exported"},
    ]

    approved, not_approved = split_rows_by_approval(rows, ["APPROVAL 1"])

    assert [r["REFERENCE"] for r in approved] == ["REF2"]
    assert not_approved == []
