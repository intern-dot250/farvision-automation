import io

import pandas as pd

REQUIRED_COLUMNS = ["TXN DATE", "DESCRIPTION", "REFERENCE", "DEBITS", "CREDITS"]

# Real statement exports sometimes carry a summary row (e.g. "LAST UPDATE ...")
# above the real header, so the header isn't always row 0.
MAX_HEADER_SCAN_ROWS = 10


def _find_header_row(raw: pd.DataFrame) -> int | None:
    """Scan the first few rows of a headerless dataframe for the row that
    contains all required columns, returning its index (or None)."""
    for i in range(min(MAX_HEADER_SCAN_ROWS, len(raw))):
        values = {str(v).strip() for v in raw.iloc[i].tolist()}
        if all(col in values for col in REQUIRED_COLUMNS):
            return i
    return None


def _apply_header(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row]]
    return df


def _resolve_sheet_name(requested: str, available: list[str]) -> str | None:
    """Match a requested sheet/tab name case- and whitespace-insensitively
    (e.g. "YES RERA 0377" should still find "YES Rera 0377")."""
    key = " ".join(requested.strip().upper().split())
    for name in available:
        if " ".join(name.strip().upper().split()) == key:
            return name
    return None


def list_candidate_sheets(filename: str, content: bytes) -> list[str]:
    """Sheet names in an uploaded workbook that actually contain transaction
    data (same header-detection used by parse_statement_file), so the
    frontend can offer a dropdown of real choices instead of the user
    guessing a tab name after a failed upload. CSV files have no sheets.
    """
    if filename.lower().endswith(".csv"):
        return []

    sheets = pd.read_excel(io.BytesIO(content), dtype=str, header=None, sheet_name=None)
    return [name for name, raw in sheets.items() if _find_header_row(raw) is not None]


def parse_statement_file(filename: str, content: bytes, sheet_name: str | None = None) -> list[dict]:
    """Parse an uploaded bank statement file into the same row-shape used
    when reading from the Google Sheet (same column names), so it can feed
    the same classify/route/write pipeline unchanged.

    The uploaded file may be a plain single-sheet export (header on row 1),
    or a copy of the full multi-account workbook (one tab per bank account,
    with a summary row above the real header). Either is handled by scanning
    for the header row within each sheet, rather than assuming row 0.
    """
    is_csv = filename.lower().endswith(".csv")

    if is_csv:
        raw = pd.read_csv(io.BytesIO(content), dtype=str, header=None)
        header_row = _find_header_row(raw)
        if header_row is None:
            raise ValueError(f"Uploaded file is missing required columns: {', '.join(REQUIRED_COLUMNS)}")
        df = _apply_header(raw, header_row)
        df["source_sheet"] = ""
    else:
        sheets = pd.read_excel(io.BytesIO(content), dtype=str, header=None, sheet_name=None)

        if sheet_name is not None:
            resolved_name = _resolve_sheet_name(sheet_name, list(sheets.keys()))
            if resolved_name is None:
                raise ValueError(f"Sheet '{sheet_name}' not found in uploaded file. Available sheets: {', '.join(sheets.keys())}")
            header_row = _find_header_row(sheets[resolved_name])
            if header_row is None:
                raise ValueError(f"Sheet '{resolved_name}' is missing required columns: {', '.join(REQUIRED_COLUMNS)}")
            df = _apply_header(sheets[resolved_name], header_row)
            df["source_sheet"] = resolved_name
        else:
            matches: dict[str, pd.DataFrame] = {}
            for name, raw in sheets.items():
                header_row = _find_header_row(raw)
                if header_row is not None:
                    matches[name] = _apply_header(raw, header_row)

            if not matches:
                raise ValueError(
                    f"Uploaded file is missing required columns: {', '.join(REQUIRED_COLUMNS)}. "
                    f"Checked {len(sheets)} sheet(s), none had a matching header row."
                )
            if len(matches) > 1:
                # Workbook has several bank-account tabs; the user uploaded
                # without picking one, so process all of them together rather
                # than rejecting the upload. Non-transaction tabs (Index,
                # Dashboard, etc.) are filtered out above by header detection.
                pass
            df = pd.concat(matches.values(), ignore_index=True)
            df["source_sheet"] = ""
            for name, matched in matches.items():
                df.loc[: len(matched) - 1, "source_sheet"] = name

    df = df.fillna("")
    records = df.to_dict(orient="records")
    # Accounts intentionally leaves blank spacer rows in the source workbook
    # (between sections) - drop them rather than trying to classify them as
    # failed transactions. Checked against REQUIRED_COLUMNS specifically
    # (not every column) - a spacer row can still carry stray content in an
    # unrelated column (a note, a leftover SL# tag, our own synthetic
    # "source_sheet" tag, etc.) and still be a spacer, since none of that is
    # actual transaction data.
    records = [
        record
        for record in records
        if any(str(record.get(col, "")).strip() for col in REQUIRED_COLUMNS)
    ]
    # "B/F" (Brought Forward) rows are a standard bank-statement convention
    # carrying the running balance from a previous period/page forward -
    # not a real transaction, regardless of which file/sheet was uploaded.
    return [
        record
        for record in records
        if not str(record.get("DESCRIPTION", "")).strip().upper().startswith("B/F")
    ]
