from functools import lru_cache
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import get_settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Canonical header rows for every tab the app writes to, keyed by which
# spreadsheet the tab lives in - both spreadsheets have a "LedgerDetails" tab
# but with different columns, so tab name alone isn't a safe key. Used to
# self-heal a tab whose header row was accidentally wiped (e.g. someone
# deleted all rows including row 1) before the app writes to it again.
_RECEIPT_PAYMENT_HEADERS: dict[str, list[str]] = {
    "ReceiptPayment": [
        "Link Ref Code", "Business Unit", "Financial Year", "Document Type",
        "Document Date", "Document No", "Narration", "BankName", "EntryTypes",
    ],
    "ReceiptPaymentDetail": ["Link Ref Code", "Detail Link Ref Code"],
    "LedgerDetails": [
        "Link Ref Code", "Detail Link Ref Code", "Business Unit", "Document Type",
        "Debit/Credit", "Account Head", "Parent Account Head", "Debit Amount",
        "Credit Amount", "Narration", "Payment Mode", "Cheque No", "Cheque Date",
        "Cheque Type", "Payee Name", "Beneficiary", "Card Type", "Print Cheque",
        "Sub Project", "Budget", "Zone", "Department", "Order", "Milestone",
        "Tower", "Segment", "Employee", "Employee Name", "Department Name",
        "Cost Center", "Purpose Of Payment",
    ],
    "AdjustmentDetails": [
        "Link Ref Code", "Detail Link Ref Code", "Docno", "Date", "Invoice No",
        "Invoice Date", "Bill Amount", "Balance Amount", "Adjustment Amount",
    ],
    "ImportTaxInfo": ["Link Ref Code", "Detail Link Ref Code", "Deduction Type", "Description"],
}

_DEPOSIT_WITHDRAWAL_HEADERS: dict[str, list[str]] = {
    "DepositWithdrawal": [
        "Link Ref Code", "DepositWithdrawal Business Unit", "DepositWithdrawal Narration",
        "Financial Year", "Document Type", "Document Date", "Document No",
        "BankName", "EntryTypes",
    ],
    "DepositWithdrawalDetails": ["Link Ref Code"],
    "LedgerDetails": [
        "Link Ref Code", "Debit/Credit", "Account Head", "Parent Account Head",
        "Debit Amount", "Credit Amount", "Payment Mode", "Cheque No", "Cheque Date",
        "Cheque Type", "Payee Name", "Card Type", "Narration", "Print Cheque",
    ],
}


def _canonical_header(sheet_id: str, worksheet_name: str) -> list[str] | None:
    settings = get_settings()
    if sheet_id == settings.RECEIPT_PAYMENT_SHEET_ID:
        return _RECEIPT_PAYMENT_HEADERS.get(worksheet_name)
    if sheet_id == settings.DEPOSIT_WITHDRAWAL_SHEET_ID:
        return _DEPOSIT_WITHDRAWAL_HEADERS.get(worksheet_name)
    return None


def _resolve_credentials_path() -> Path:
    settings = get_settings()
    path = Path(settings.GOOGLE_CREDENTIALS_PATH)
    return path if path.is_absolute() else BACKEND_ROOT / path


@lru_cache
def get_client() -> gspread.Client:
    """Authenticated gspread client, built once and reused across requests.

    Supports two credential sources (checked in order):
    1. ``GOOGLE_CREDENTIALS_JSON_BASE64`` — base64-encoded service-account JSON,
       ideal for serverless deployments (Vercel, etc.) where a file path is unavailable.
    2. ``GOOGLE_CREDENTIALS_PATH`` — local file path (default: ``credentials/service-account.json``).
    """
    import base64
    import json

    settings = get_settings()

    if settings.GOOGLE_CREDENTIALS_JSON_BASE64.strip():
        json_bytes = base64.b64decode(settings.GOOGLE_CREDENTIALS_JSON_BASE64.strip())
        info = json.loads(json_bytes)
        credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        credentials = Credentials.from_service_account_file(
            str(_resolve_credentials_path()), scopes=SCOPES
        )

    return gspread.authorize(credentials)


@lru_cache
def open_sheet(sheet_id: str) -> gspread.Spreadsheet:
    """Cached per sheet_id: opening a spreadsheet fetches its full metadata
    (1 API read), and every call site opens the same handful of sheet IDs
    repeatedly - reusing the same Spreadsheet object avoids redundant reads
    against Google's per-minute quota. Worksheet content reads (col_values,
    get_all_values, etc.) are never cached - only the "which spreadsheet is
    this" lookup is safe to reuse, since tab names/IDs don't change here.
    """
    return get_client().open_by_key(sheet_id)


def get_worksheet(sheet_id: str, worksheet_name: str) -> gspread.Worksheet:
    return open_sheet(sheet_id).worksheet(worksheet_name)


def list_worksheet_titles(sheet_id: str) -> list[str]:
    return [worksheet.title for worksheet in open_sheet(sheet_id).worksheets()]


def read_all_records(sheet_id: str, worksheet_name: str) -> list[dict]:
    """Read a worksheet as a list of dicts, keyed by its header row."""
    return get_worksheet(sheet_id, worksheet_name).get_all_records()


def count_data_rows(sheet_id: str, worksheet_name: str) -> int:
    """Count non-empty data rows in a worksheet, excluding the header row.

    Reads just the first column rather than the whole sheet, so this stays
    cheap even as a sheet grows.
    """
    values = get_worksheet(sheet_id, worksheet_name).col_values(1)
    return max(len(values) - 1, 0)


def get_column_values(sheet_id: str, worksheet_name: str, column: str) -> set[str]:
    """Non-empty values in a named column (excluding the header), reading
    just that one column rather than the whole sheet. Returns an empty set
    if the column doesn't exist in this worksheet.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if column not in header:
        return set()
    col_index = header.index(column) + 1  # gspread columns are 1-indexed
    values = worksheet.col_values(col_index)[1:]
    return {v.strip() for v in values if v.strip()}


_AMOUNT_COLUMNS = {"Debit Amount", "Credit Amount", "Adjustment Amount"}

# Tabs that get a Western-grouped, no-decimal NUMBER format applied to their
# amount columns after every write - see _apply_amount_number_format().
_AMOUNT_COLUMNS_BY_TAB: dict[str, list[str]] = {
    "LedgerDetails": ["Debit Amount", "Credit Amount"],
    "AdjustmentDetails": ["Adjustment Amount"],
}


def _column_letter(col_index: int) -> str:
    """1-indexed column number -> spreadsheet column letter(s) (1 -> "A")."""
    letters = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _apply_amount_number_format(worksheet: gspread.Worksheet, header: list[str], worksheet_name: str) -> None:
    """Applies a real, no-decimal NUMBER format ("#,##0") to this tab's
    amount columns, for every data row (open-ended range) - not just the
    rows just appended, so it also fixes any older rows in the same column.

    Indian digit grouping ("1,50,000") isn't achievable on a genuine Sheets
    number - confirmed exhaustively (NUMBER/TEXT format types, custom comma
    patterns, locale tags, en_GB, even India's own hi_IN locale all only
    ever produce Western 3-digit grouping ("150,000")) - so this is the best
    available real-number formatting: right-aligned, sortable, usable in
    SUM/formulas, whole rupees only.
    """
    columns = _AMOUNT_COLUMNS_BY_TAB.get(worksheet_name)
    if not columns:
        return
    for column in columns:
        if column not in header:
            continue
        letter = _column_letter(header.index(column) + 1)
        worksheet.format(f"{letter}2:{letter}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})


def append_records(sheet_id: str, worksheet_name: str, records: list[dict]) -> None:
    """Append rows to a worksheet, ordering values to match its existing header row.

    Numeric columns (Link Ref Code, Detail Link Ref Code, Debit/Credit/
    Adjustment Amount) are written as integers so Sheets treats them as real
    numbers. Date columns (Document Date, Invoice Date) are written as plain
    "DD/MM/YYYY" strings - the same format they already arrive in from
    automation_engine.py - so both columns stay consistent and never get
    silently reformatted to ISO ("YYYY-MM-DD"). A plain string is always
    JSON serializable, unlike a native `date` object (which previously broke
    real writes).

    Uses RAW input mode, not USER_ENTERED: Sheets' "smart parsing" under
    USER_ENTERED inconsistently converts some comma-grouped strings into
    real numbers while leaving others as literal text (locale-dependent),
    causing inconsistent number/text alignment on the same column. RAW keeps
    every string exactly as given; integer values are unaffected either way,
    since they're sent as real JSON numbers rather than strings.
    """
    if not records:
        return

    INT_COLUMNS = {"Link Ref Code", "Detail Link Ref Code"} | _AMOUNT_COLUMNS

    def _coerce(value, column: str):
        if column in INT_COLUMNS:
            try:
                return int(value)
            except (ValueError, TypeError):
                return value
        return value

    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if not header:
        header = _canonical_header(sheet_id, worksheet_name)
        if not header:
            raise ValueError(
                f"'{worksheet_name}' has no header row and no canonical header is known for it"
            )
        worksheet.update(range_name="A1", values=[header])

    rows = [
        [_coerce(record.get(column, ""), column) for column in header]
        for record in records
    ]
    worksheet.append_rows(rows, value_input_option="RAW")
    _apply_amount_number_format(worksheet, header, worksheet_name)
