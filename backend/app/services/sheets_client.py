from datetime import datetime
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


def open_sheet(sheet_id: str) -> gspread.Spreadsheet:
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


def append_records(sheet_id: str, worksheet_name: str, records: list[dict]) -> None:
    """Append rows to a worksheet, ordering values to match its existing header row.

    Numeric columns (Link Ref Code, Detail Link Ref Code) are written as integers
    so Sheets right-aligns them. Date columns (Document Date, Invoice Date) are
    parsed from DD/MM/YYYY and written as ISO date strings ("YYYY-MM-DD") -
    Sheets still recognizes these as real dates and right-aligns them with
    USER_ENTERED, but unlike a native `date` object, a string is JSON
    serializable when gspread sends the write request.
    """
    if not records:
        return

    INT_COLUMNS = {"Link Ref Code", "Detail Link Ref Code"}
    DATE_COLUMNS = {"Document Date", "Invoice Date"}

    def _coerce(value: str, column: str):
        if column in INT_COLUMNS:
            try:
                return int(value)
            except (ValueError, TypeError):
                return value
        if column in DATE_COLUMNS:
            try:
                return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
            except (ValueError, TypeError):
                return value
        return value

    worksheet = get_worksheet(sheet_id, worksheet_name)
    header = worksheet.row_values(1)
    rows = [
        [_coerce(record.get(column, ""), column) for column in header]
        for record in records
    ]
    worksheet.append_rows(rows, value_input_option="USER_ENTERED")
