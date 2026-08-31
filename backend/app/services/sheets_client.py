import re
import time
from functools import lru_cache
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.http_client import HTTPClient
from gspread.utils import ValidationConditionType

from app.core.config import get_settings
from app.core.logger import logger

# Google's Sheets API read quota is per-minute-per-user - a single
# automation run can genuinely burst past it (duplicate-detection reads,
# history-index reads, dropdown/note attachment, all within the same
# request), and it's shared across every concurrent user of this project,
# so a burst of manual testing elsewhere can also exhaust it. Retrying with
# backoff, patched once at this single choke point that every gspread
# operation funnels through (Worksheet/Spreadsheet methods all end up
# calling HTTPClient.request), means a transient 429 self-heals within the
# same run instead of failing the whole automation with no easy way to
# recover except waiting and re-uploading by hand.
_RETRYABLE_STATUS_CODES = {429}
_MAX_ATTEMPTS = 4
_original_http_client_request = HTTPClient.request


def _request_with_retry(self, method, endpoint, *args, **kwargs):
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return _original_http_client_request(self, method, endpoint, *args, **kwargs)
        except gspread.exceptions.APIError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in _RETRYABLE_STATUS_CODES or attempt == _MAX_ATTEMPTS:
                raise
            wait_seconds = 15 * attempt
            logger.warning(
                f"Sheets API rate limit hit ({method} {endpoint}) - "
                f"retrying in {wait_seconds}s (attempt {attempt}/{_MAX_ATTEMPTS})"
            )
            time.sleep(wait_seconds)


HTTPClient.request = _request_with_retry

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


@lru_cache
def _get_worksheet_cached(sheet_id: str, worksheet_name: str) -> gspread.Worksheet:
    return open_sheet(sheet_id).worksheet(worksheet_name)


def get_worksheet(sheet_id: str, worksheet_name: str) -> gspread.Worksheet:
    """Cached per (sheet_id, worksheet_name) for the lifetime of the process,
    cleared once per automation run via clear_worksheet_cache() (alongside
    master_repository.clear_cache()). gspread's Spreadsheet.worksheet()
    issues a full, uncached spreadsheet-metadata read API call on every
    invocation - and this function sits at the top of nearly every Sheets
    operation in this module, including once per ambiguous transaction
    during dropdown attachment, so leaving it uncached was burning through
    Google's per-minute read quota fast enough to make the ambiguous-Account-
    Head dropdown silently fail to attach under load (confirmed live via the
    audit_log: repeated 429s on "Failed to attach Account Head dropdown").
    """
    return _get_worksheet_cached(sheet_id, worksheet_name)


_header_cache: dict[tuple[str, str], list[str]] = {}


def _get_header(sheet_id: str, worksheet_name: str, worksheet: gspread.Worksheet | None = None) -> list[str]:
    """Header row (row 1), cached per (sheet_id, worksheet_name) for the same
    reason as get_worksheet() above - every dropdown/note/formula/lookup
    helper below was independently re-fetching this via its own API call on
    every invocation."""
    key = (sheet_id, worksheet_name)
    if key not in _header_cache:
        ws = worksheet or get_worksheet(sheet_id, worksheet_name)
        _header_cache[key] = ws.row_values(1)
    return _header_cache[key]


def clear_worksheet_cache() -> None:
    """Clears the worksheet-object and header-row caches above - call once
    per automation run (alongside master_repository.clear_cache()) so a
    long-lived warm serverless instance doesn't serve a stale worksheet
    handle or header row across runs."""
    _get_worksheet_cached.cache_clear()
    _header_cache.clear()


def list_worksheet_titles(sheet_id: str) -> list[str]:
    return [worksheet.title for worksheet in open_sheet(sheet_id).worksheets()]


_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9-_]+$")


def extract_spreadsheet_id(url_or_id: str) -> str | None:
    """Pulls a spreadsheet ID out of a pasted Google Sheets URL (any of its
    usual forms - .../edit, .../edit#gid=..., .../view, no trailing path at
    all), or accepts an already-bare ID typed/pasted directly. Returns None
    for anything that's neither - the caller turns that into a clear
    "invalid URL" message rather than trying to open garbage."""
    if not url_or_id:
        return None
    candidate = url_or_id.strip()
    match = _SPREADSHEET_ID_RE.search(candidate)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(candidate) and "docs.google.com" not in candidate:
        return candidate
    return None


def get_worksheet_values(sheet_id: str, worksheet_name: str, row_limit: int | None = None) -> list[list[str]]:
    """Raw grid values for a worksheet (no header assumed) - used for tabs
    whose shape isn't known ahead of time (an arbitrary externally-pasted
    spreadsheet's tabs), unlike read_all_records() which requires a real
    header row already in place. `row_limit`, when given, bounds the read to
    just the first N rows (e.g. for header-detection previews) so a huge,
    irrelevant tab isn't read in full just to check whether it looks like a
    transaction sheet."""
    worksheet = get_worksheet(sheet_id, worksheet_name)
    range_name = f"A1:ZZ{row_limit}" if row_limit else None
    return worksheet.get_values(range_name)


def get_or_create_worksheet(
    sheet_id: str, worksheet_name: str, rows: int = 10000, cols: int = 4
) -> gspread.Worksheet:
    """Looks up a worksheet by name, creating it (hidden - not meant for
    normal use, e.g. a dropdown-source lookup tab) if it doesn't exist yet.
    Self-healing: no manual one-time setup step is needed in the Google
    Sheets UI - the first automation run that needs the tab creates it.
    Uses get_worksheet()'s cache on the found/created worksheet, same as
    every other worksheet lookup in this module."""
    spreadsheet = open_sheet(sheet_id)
    try:
        return get_worksheet(sheet_id, worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        pass
    worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=rows, cols=cols)
    spreadsheet.batch_update({
        "requests": [{
            "updateSheetProperties": {
                "properties": {"sheetId": worksheet.id, "hidden": True},
                "fields": "hidden",
            }
        }]
    })
    _get_worksheet_cached.cache_clear()
    return get_worksheet(sheet_id, worksheet_name)


def _ensure_header(worksheet: gspread.Worksheet, sheet_id: str, worksheet_name: str) -> list[str]:
    """Returns the worksheet's header row, restoring it first if blank (e.g.
    someone accidentally deleted row 1 along with data rows) - without this,
    gspread's get_all_records() raises on an all-empty header row (reads as
    duplicate "" columns) instead of just treating the sheet as empty."""
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if not header:
        header = _canonical_header(sheet_id, worksheet_name)
        if not header:
            raise ValueError(
                f"'{worksheet_name}' has no header row and no canonical header is known for it"
            )
        worksheet.update(range_name="A1", values=[header])
        _header_cache[(sheet_id, worksheet_name)] = header
    return header


def ensure_column(sheet_id: str, worksheet_name: str, column_name: str) -> None:
    """Appends `column_name` as a new header cell (in the next empty column
    of row 1) if it isn't already present on this worksheet - self-healing,
    no manual one-time sheet setup needed, same convention as
    get_or_create_worksheet. No-op if the column already exists. Used to
    add the machine-owned "Farvision Status" column to a source Google Sheet
    tab the app doesn't otherwise write to.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column_name in header:
        return
    letter = _column_letter(len(header) + 1)
    worksheet.update(range_name=f"{letter}1", values=[[column_name]])
    _header_cache[(sheet_id, worksheet_name)] = header + [column_name]


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
    header = _get_header(sheet_id, worksheet_name, worksheet)
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
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return None
    col_index = header.index(column) + 1
    values = worksheet.col_values(col_index)
    target = str(value).strip()
    for i in range(len(values) - 1, 0, -1):
        if values[i].strip() == target:
            return i + 1
    return None


def find_row_numbers_bulk(sheet_id: str, worksheet_name: str, column: str, values: list) -> dict[str, int]:
    """Like find_row_number(), but resolves many target values in a single
    column read instead of one Sheets API read per value - used when a
    post-write step needs to locate several already-written rows (e.g.
    attaching a dropdown to every ambiguous transaction from the same run)
    instead of looking each one up independently.

    Returns {str(value): row_number} only for values actually found (last
    matching row wins, same "search from the bottom" semantics as
    find_row_number). Values not present in the column are simply absent
    from the result - callers already handle a missing row the same way
    find_row_number's None return is handled today.
    """
    if not values:
        return {}
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return {}
    col_index = header.index(column) + 1
    col_values = worksheet.col_values(col_index)
    wanted = {str(value).strip() for value in values}
    found: dict[str, int] = {}
    for i, cell in enumerate(col_values):
        if i == 0:
            continue  # header row
        cell = cell.strip()
        if cell in wanted:
            found[cell] = i + 1  # last match wins - later rows overwrite earlier ones
    return found


def get_column_values(sheet_id: str, worksheet_name: str, column: str) -> set[str]:
    """Non-empty values in a named column (excluding the header), reading
    just that one column rather than the whole sheet. Returns an empty set
    if the column doesn't exist in this worksheet.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
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


def sync_lookup_column(
    sheet_id: str, worksheet_name: str, column_letter: str, header: str, values: list[str]
) -> str:
    """Overwrites one column of a helper/lookup tab (see
    get_or_create_worksheet()) with `header` in row 1 and `values` below it,
    clearing any stale leftover rows first (e.g. if Master's list shrank
    since the last sync) - used as the same-spreadsheet source range for a
    "List from a range" (ONE_OF_RANGE) dropdown validation, which has no
    practical size cap unlike an inline ONE_OF_LIST dropdown (confirmed
    live: the Sheets API rejects a ONE_OF_LIST validation outright past 500
    values, with error "Use the 'List from a range' criteria instead").

    Returns the A1 range reference for the written values (excluding the
    header row), ready to pass straight into batch_apply_cell_flags' new
    `dropdown_range` flag. Confirmed live: the Sheets API's ONE_OF_RANGE
    condition rejects a bare "Sheet!A2:A10" string ("Invalid
    ConditionValue.userEnteredValue") - it must be a formula-style
    reference with a leading "=", e.g. "=Sheet!A2:A10".
    """
    worksheet = get_or_create_worksheet(sheet_id, worksheet_name)
    last_row = max(worksheet.row_count, len(values) + 1, 2)
    worksheet.batch_clear([f"{column_letter}2:{column_letter}{last_row}"])
    worksheet.update(
        range_name=f"{column_letter}1", values=[[header]] + [[v] for v in values],
        value_input_option="RAW",
    )
    return f"={worksheet_name}!{column_letter}2:{column_letter}{max(len(values) + 1, 2)}"


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
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return
    letter = _column_letter(header.index(column) + 1)
    worksheet.add_validation(
        f"{letter}{row_number}:{letter}{row_number}",
        ValidationConditionType.one_of_list,
        values,
        showCustomUi=True,
    )


def column_letter_for(sheet_id: str, worksheet_name: str, column: str) -> str | None:
    """Spreadsheet column letter (e.g. "F") for a named header column, or
    None if `column` isn't a real header - used to build a cell reference
    (e.g. for a formula referring to another cell in the same row)."""
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return None
    return _column_letter(header.index(column) + 1)


def set_cell_formula(sheet_id: str, worksheet_name: str, row_number: int, column: str, formula: str) -> None:
    """Write a live formula (e.g. one that extracts Parent Account Head out
    of an Account Head dropdown's selected label) into one cell of an
    already-written row. Uses USER_ENTERED, unlike append_records' RAW mode
    - a leading "=" is only evaluated as a formula under USER_ENTERED, so it
    needs its own write path. No-op if `column` isn't a real header.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return
    letter = _column_letter(header.index(column) + 1)
    worksheet.update(range_name=f"{letter}{row_number}", values=[[formula]], value_input_option="USER_ENTERED")


def add_cell_note(sheet_id: str, worksheet_name: str, row_number: int, column: str, note_text: str) -> None:
    """Attach a plain cell note (the small red-corner comment, not a
    validation dropdown) to one cell of an already-written row - used
    alongside add_dropdown_validation to explain that a second column needs
    manual verification, since native Sheets validation can't auto-update
    one cell based on another cell's selection. No-op if `column` isn't a
    real header on this worksheet.
    """
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    if column not in header:
        return
    letter = _column_letter(header.index(column) + 1)
    worksheet.insert_note(f"{letter}{row_number}", note_text)


def batch_apply_cell_flags(sheet_id: str, worksheet_name: str, flags: list[dict]) -> None:
    """Apply many dropdown-validation / note / formula cell writes in a
    single Sheets API batch_update call, instead of one call per (row,
    field) pair - used for the post-write "flag this row for review"
    step (ambiguous/no-match Account Head dropdowns), which previously
    issued 3-9 sequential API calls per flagged row. For a large upload
    with dozens of flagged rows this took minutes, exceeding this
    project's serverless function time limit (confirmed live via
    audit_log: a run with no completion logged at all). Batching brings
    the whole step down to one round trip regardless of row count -
    same technique clear_all_tabs() already uses for its own
    validation/note-clearing requests.

    Each entry in `flags`: {"row_number": int, "column": str,
    "dropdown_values": list[str] | None, "dropdown_range": str | None,
    "note_text": str | None, "formula": str | None, "value": str | None} -
    any of note_text/formula/value can be combined with one of
    dropdown_values/dropdown_range for the same cell (e.g. a dropdown + a
    note together); dropdown_values and dropdown_range are mutually
    exclusive per entry (an inline ONE_OF_LIST dropdown vs. a "List from a
    range" ONE_OF_RANGE dropdown - the latter for option lists too large for
    ONE_OF_LIST's ~500-value cap, sourced from a same-spreadsheet helper tab
    via sync_lookup_column()). `value` writes a plain literal string into the
    cell (e.g. a computed status label) - unlike `formula`, it's never
    evaluated as a formula even if it starts with "=".
    No-op (per entry) if `column` isn't a real header on this worksheet.
    A malformed request anywhere in the batch fails the whole call
    (Sheets API batchUpdate is all-or-nothing) - callers should treat
    this the same "cosmetic, never blocks the real write" way the
    previous per-row calls were already treated.
    """
    if not flags:
        return
    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = _get_header(sheet_id, worksheet_name, worksheet)
    spreadsheet = open_sheet(sheet_id)

    requests = []
    for flag in flags:
        column = flag["column"]
        if column not in header:
            continue
        row_number = flag["row_number"]
        col_index = header.index(column) + 1
        cell_range = {
            "sheetId": worksheet.id,
            "startRowIndex": row_number - 1,
            "endRowIndex": row_number,
            "startColumnIndex": col_index - 1,
            "endColumnIndex": col_index,
        }

        dropdown_values = flag.get("dropdown_values")
        dropdown_range = flag.get("dropdown_range")
        if dropdown_values:
            requests.append({
                "setDataValidation": {
                    "range": cell_range,
                    "rule": {
                        "condition": {
                            "type": ValidationConditionType.one_of_list.value,
                            "values": [{"userEnteredValue": v} for v in dropdown_values],
                        },
                        "showCustomUi": True,
                    },
                }
            })
        elif dropdown_range:
            requests.append({
                "setDataValidation": {
                    "range": cell_range,
                    "rule": {
                        "condition": {
                            "type": ValidationConditionType.one_of_range.value,
                            "values": [{"userEnteredValue": dropdown_range}],
                        },
                        "showCustomUi": True,
                    },
                }
            })

        note_text = flag.get("note_text")
        if note_text:
            requests.append({
                "updateCells": {
                    "range": cell_range,
                    "fields": "note",
                    "rows": [{"values": [{"note": note_text}]}],
                }
            })

        formula = flag.get("formula")
        if formula:
            requests.append({
                "updateCells": {
                    "range": cell_range,
                    "fields": "userEnteredValue",
                    "rows": [{"values": [{"userEnteredValue": {"formulaValue": formula}}]}],
                }
            })

        value = flag.get("value")
        if value is not None:
            requests.append({
                "updateCells": {
                    "range": cell_range,
                    "fields": "userEnteredValue",
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": str(value)}}]}],
                }
            })

    if requests:
        spreadsheet.batch_update({"requests": requests})


# Never cleared, regardless of which tab-name conventions a spreadsheet uses -
# "Info" holds reference/instructional content, not transaction data;
# "Lookup" (see get_or_create_worksheet/sync_lookup_column) is a hidden
# dropdown-source helper tab synced independently each time it's needed, not
# per-automation-run transaction data - clearing it here would leave any
# already-attached ONE_OF_RANGE dropdown pointing at a blank range until the
# next row that needs it happens to re-sync it.
_CLEAR_EXCLUDED_WORKSHEETS = {"Info", "Lookup"}


def clear_all_tabs(sheet_id: str) -> list[str]:
    """Erase every data row (row 2 downward) from every tab in this
    spreadsheet, except "Info" - header row 1 is never touched on any tab.

    Also clears any data validation (e.g. an Account Head dropdown) and any
    cell notes (e.g. the "multiple Master entries..." note attached
    alongside that dropdown) left over from a previous run's ambiguous
    transaction, from the same cleared range - values.batchClear only erases
    cell values, never validation/note/formatting metadata, so either one
    left in place would otherwise stay physically pinned to its row and
    silently misapply to whatever unrelated transaction a later run happens
    to write into that same row.

    Tabs are discovered dynamically from the live spreadsheet rather than a
    hardcoded list, so this stays correct even if tabs are added later.
    Returns the list of tab names actually cleared.
    """
    spreadsheet = open_sheet(sheet_id)
    cleared: list[str] = []
    metadata_requests = []
    for worksheet in spreadsheet.worksheets():
        if worksheet.title in _CLEAR_EXCLUDED_WORKSHEETS:
            continue
        last_col_letter = _column_letter(max(worksheet.col_count, 1))
        worksheet.batch_clear([f"A2:{last_col_letter}"])
        cleared_range = {
            "sheetId": worksheet.id,
            "startRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": max(worksheet.col_count, 1),
        }
        metadata_requests.append({"setDataValidation": {"range": cleared_range}})
        metadata_requests.append({
            "repeatCell": {"range": cleared_range, "cell": {}, "fields": "note"}
        })
        cleared.append(worksheet.title)
    if metadata_requests:
        spreadsheet.batch_update({"requests": metadata_requests})
    return cleared
