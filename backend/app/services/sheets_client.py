from functools import lru_cache
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValidationConditionType

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


def _ensure_header(worksheet: gspread.Worksheet, sheet_id: str, worksheet_name: str) -> list[str]:
    """Returns the worksheet's header row, restoring it first if blank (e.g.
    someone accidentally deleted row 1 along with data rows) - without this,
    gspread's get_all_records() raises on an all-empty header row (reads as
    duplicate "" columns) instead of just treating the sheet as empty."""
    header = worksheet.row_values(1)
    if not header:
        header = _canonical_header(sheet_id, worksheet_name)
        if not header:
            raise ValueError(
                f"'{worksheet_name}' has no header row and no canonical header is known for it"
            )
        worksheet.update(range_name="A1", values=[header])
    return header


def read_all_records(sheet_id: str, worksheet_name: str) -> list[dict]:
    """Read a worksheet as a list of dicts, keyed by its header row."""
    worksheet = get_worksheet(sheet_id, worksheet_name)
    _ensure_header(worksheet, sheet_id, worksheet_name)
    return worksheet.get_all_records()


def count_data_rows(sheet_id: str, worksheet_name: str) -> int:
    """Count non-empty data rows in a worksheet, excluding the header row.

    Reads just the first column rather than the whole sheet, so this stays
    cheap even as a sheet grows.
    """
    values = get_worksheet(sheet_id, worksheet_name).col_values(1)
    return max(len(values) - 1, 0)


def get_columns(sheet_id: str, worksheet_name: str, columns: list[str]) -> list[tuple[str, ...]]:
    """Several named columns read together, row-aligned (excluding the
    header) - used to build an index (e.g. {payee: Counter((Account Head,
    Parent Account Head))}) without reading the whole worksheet. Returns []
    if any requested column doesn't exist.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if any(column not in header for column in columns):
        return []
    indexes = [header.index(column) + 1 for column in columns]
    value_lists = [worksheet.col_values(i)[1:] for i in indexes]
    return list(zip(*value_lists))


def find_row_number(sheet_id: str, worksheet_name: str, column: str, value) -> int | None:
    """1-indexed row number of the last row whose `column` cell equals
    `value` (searched from the bottom, since the row of interest was just
    appended), or None if `column` doesn't exist or no row matches."""
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if column not in header:
        return None
    col_index = header.index(column) + 1
    values = worksheet.col_values(col_index)
    target = str(value).strip()
    for i in range(len(values) - 1, 0, -1):
        if values[i].strip() == target:
            return i + 1
    return None


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
    header = _ensure_header(worksheet, sheet_id, worksheet_name)

    rows = [
        [_coerce(record.get(column, ""), column) for column in header]
        for record in records
    ]
    worksheet.append_rows(rows, value_input_option="RAW")
    _apply_amount_number_format(worksheet, header, worksheet_name)


def add_dropdown_validation(
    sheet_id: str, worksheet_name: str, row_number: int, column: str, values: list[str]
) -> None:
    """Attach a native Sheets dropdown (restricted to `values`) to one cell
    of an already-written row - used for a Ledger Details Account Head cell
    whose beneficiary matched more than one genuine Master option, so it can
    be resolved with two clicks directly in the sheet instead of a separate
    review step. No-op if `column` isn't a real header on this worksheet.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if column not in header:
        return
    letter = _column_letter(header.index(column) + 1)
    worksheet.add_validation(
        f"{letter}{row_number}:{letter}{row_number}",
        ValidationConditionType.one_of_list,
        values,
        showCustomUi=True,
    )


def add_cell_note(sheet_id: str, worksheet_name: str, row_number: int, column: str, note_text: str) -> None:
    """Attach a plain cell note (the small red-corner comment, not a
    validation dropdown) to one cell of an already-written row - used
    alongside add_dropdown_validation to explain that a second column needs
    manual verification, since native Sheets validation can't auto-update
    one cell based on another cell's selection. No-op if `column` isn't a
    real header on this worksheet.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    if column not in header:
        return
    letter = _column_letter(header.index(column) + 1)
    worksheet.insert_note(f"{letter}{row_number}", note_text)


# Never cleared, regardless of which tab-name conventions a spreadsheet uses -
# holds reference/instructional content, not transaction data.
_CLEAR_EXCLUDED_WORKSHEETS = {"Info"}


def clear_all_tabs(sheet_id: str) -> list[str]:
    """Erase every data row (row 2 downward) from every tab in this
    spreadsheet, except "Info" - header row 1 is never touched on any tab.

    Also clears any data validation (e.g. an Account Head dropdown left over
    from a previous run's ambiguous transaction) from the same cleared range
    - values.batchClear only erases cell values, never validation/formatting
    metadata, so a validation rule left in place would otherwise stay
    physically pinned to its row and silently misapply to whatever
    unrelated transaction a later run happens to write into that same row.

    Tabs are discovered dynamically from the live spreadsheet rather than a
    hardcoded list, so this stays correct even if tabs are added later.
    Returns the list of tab names actually cleared.
    """
    spreadsheet = open_sheet(sheet_id)
    cleared: list[str] = []
    validation_requests = []
    for worksheet in spreadsheet.worksheets():
        if worksheet.title in _CLEAR_EXCLUDED_WORKSHEETS:
            continue
        last_col_letter = _column_letter(max(worksheet.col_count, 1))
        worksheet.batch_clear([f"A2:{last_col_letter}"])
        validation_requests.append({
            "setDataValidation": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(worksheet.col_count, 1),
                }
            }
        })
        cleared.append(worksheet.title)
    if validation_requests:
        spreadsheet.batch_update({"requests": validation_requests})
    return cleared
