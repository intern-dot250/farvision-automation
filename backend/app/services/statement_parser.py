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
    else:
        sheets = pd.read_excel(io.BytesIO(content), dtype=str, header=None, sheet_name=None)

        if sheet_name is not None:
            if sheet_name not in sheets:
                raise ValueError(f"Sheet '{sheet_name}' not found in uploaded file. Available sheets: {', '.join(sheets.keys())}")
            header_row = _find_header_row(sheets[sheet_name])
            if header_row is None:
                raise ValueError(f"Sheet '{sheet_name}' is missing required columns: {', '.join(REQUIRED_COLUMNS)}")
            df = _apply_header(sheets[sheet_name], header_row)
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
                raise ValueError(
                    f"Uploaded file has transaction data on multiple sheets ({', '.join(matches.keys())}). "
                    "Re-upload specifying which sheet to use."
                )
            df = next(iter(matches.values()))

    df = df.fillna("")
    return df.to_dict(orient="records")
