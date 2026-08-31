import io
import re
from dataclasses import dataclass, field

import pandas as pd

from app.services import sheets_client

REQUIRED_COLUMNS = ["TXN DATE", "DESCRIPTION", "REFERENCE", "DEBITS", "CREDITS"]

# Machine-owned status column this app writes back onto a source Google
# Sheet tab (approval-linked runs only) - see automation_engine.py's
# Farvision Status write-back step. Unlike APPROVAL 1/2/3 (human-owned,
# never written by this codebase), this column is safe to overwrite on
# every run.
FARVISION_STATUS_COLUMN = "Farvision Status"
FARVISION_STATUS_EXPORTED = "Exported"

# The Bank Statement Processor project (a separate codebase) appends one of
# these free-text, human-filled columns per approval stage to its per-account
# output tabs (e.g. "APPROVAL 1", "APPROVAL 2", "APPROVAL 3") - never written
# to by this codebase, only read. Matched dynamically (never hardcoded to a
# fixed count of stages) so any number of approval stages is discovered.
_APPROVAL_COLUMN_RE = re.compile(r"^APPROVAL \d+$", re.IGNORECASE)


@dataclass
class SheetCandidates:
    included: list[str]
    ignored: list[str]
    approval_columns: list[str] = field(default_factory=list)

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


def _drop_non_transaction_rows(records: list[dict]) -> list[dict]:
    """Drops rows that survived header-slicing but aren't real transactions -
    shared by parse_statement_file() and parse_google_sheet_tabs() so both
    input sources apply the identical filter, not two copies of it.

    Blank spacer rows: Accounts intentionally leaves blank spacer rows in
    the source workbook (between sections) - drop them rather than trying to
    classify them as failed transactions. Checked against REQUIRED_COLUMNS
    specifically (not every column) - a spacer row can still carry stray
    content in an unrelated column (a note, a leftover SL# tag, our own
    synthetic "source_sheet" tag, etc.) and still be a spacer, since none of
    that is actual transaction data.

    "B/F" (Brought Forward) rows: a standard bank-statement convention
    carrying the running balance from a previous period/page forward - not
    a real transaction, regardless of which file/sheet was uploaded.
    """
    records = [
        record
        for record in records
        if any(str(record.get(col, "")).strip() for col in REQUIRED_COLUMNS)
    ]
    return [
        record
        for record in records
        if not str(record.get("DESCRIPTION", "")).strip().upper().startswith("B/F")
    ]


def _resolve_sheet_name(requested: str, available: list[str]) -> str | None:
    """Match a requested sheet/tab name case- and whitespace-insensitively
    (e.g. "YES RERA 0377" should still find "YES Rera 0377")."""
    key = " ".join(requested.strip().upper().split())
    for name in available:
        if " ".join(name.strip().upper().split()) == key:
            return name
    return None


def list_candidate_sheets_from_google(sheet_id: str) -> SheetCandidates:
    """Same classification as list_candidate_sheets(), but for a live Google
    Sheet instead of an uploaded workbook - every tab in `sheet_id` is
    split into "included" (a bounded preview read contains a row matching
    REQUIRED_COLUMNS, via the exact same _find_header_row() used for
    uploads) and "ignored" (everything else). Only the first
    MAX_HEADER_SCAN_ROWS rows of each tab are read for this check (not the
    whole tab) - a huge, irrelevant tab (e.g. a 15,000-row Master-style
    reference sheet) would otherwise be read in full just to determine it
    doesn't have a matching header.
    """
    titles = sheets_client.list_worksheet_titles(sheet_id)
    included = []
    approval_columns: set[str] = set()
    for title in titles:
        values = sheets_client.get_worksheet_values(sheet_id, title, row_limit=MAX_HEADER_SCAN_ROWS)
        if not values:
            continue
        raw = pd.DataFrame(values)
        header_row = _find_header_row(raw)
        if header_row is None:
            continue
        included.append(title)
        headers = [str(v).strip() for v in raw.iloc[header_row].tolist()]
        approval_columns.update(h for h in headers if _APPROVAL_COLUMN_RE.match(h))
    ignored = [title for title in titles if title not in included]
    return SheetCandidates(included=included, ignored=ignored, approval_columns=sorted(approval_columns))


def parse_google_sheet_tabs(sheet_id: str, sheet_names: list[str]) -> list[dict]:
    """Parse specific tabs of a live Google Sheet into the same row-shape
    parse_statement_file() produces from an uploaded workbook (same column
    names, same source_sheet tagging, same trailing blank-row/B-F-row
    filters) - so it feeds the same classify/route/write pipeline unchanged,
    regardless of whether the transaction data came from an upload or a
    pasted Google Sheet URL.
    """
    frames: list[pd.DataFrame] = []
    for name in sheet_names:
        values = sheets_client.get_worksheet_values(sheet_id, name)
        raw = pd.DataFrame(values)
        header_row = _find_header_row(raw)
        if header_row is None:
            raise ValueError(f"Sheet '{name}' is missing required columns: {', '.join(REQUIRED_COLUMNS)}")
        sheet_df = _apply_header(raw, header_row)
        sheet_df["source_sheet"] = name
        # 1-indexed sheet row number each row actually lives on - `.iloc`
        # preserves `raw`'s original row positions as the index, so this
        # survives the header slice untouched. Needed later to write
        # Farvision Status back to the exact right cell (see
        # automation_engine.py's write-back step) - only meaningful for
        # this Google Sheet input path, unlike source_sheet which is also
        # used by uploads.
        sheet_df["_source_row_number"] = sheet_df.index + 1
        frames.append(sheet_df)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df = df.fillna("")
    return _drop_non_transaction_rows(df.to_dict(orient="records"))


def split_rows_by_approval(rows: list[dict], approval_column: str) -> tuple[list[dict], list[dict]]:
    """Splits Google-Sheet-sourced rows (tagged with source_sheet/
    _source_row_number by parse_google_sheet_tabs above) into (approved,
    not_approved), based on whether `approval_column` is non-blank for that
    row - "approved" means any non-blank value, confirmed with the user (the
    accounts team writes whatever they use for a completed approval, this
    codebase never dictates or reads a specific value).

    A row whose Farvision Status is already "Exported" from a prior run is
    excluded from both buckets - it's already been handled, so re-running
    the same sheet after new rows are appended doesn't re-export or
    re-touch it.
    """
    approved: list[dict] = []
    not_approved: list[dict] = []
    for row in rows:
        if str(row.get(FARVISION_STATUS_COLUMN, "")).strip() == FARVISION_STATUS_EXPORTED:
            continue
        if str(row.get(approval_column, "")).strip():
            approved.append(row)
        else:
            not_approved.append(row)
    return approved, not_approved


def list_candidate_sheets(filename: str, content: bytes) -> SheetCandidates:
    """Splits every sheet name in an uploaded workbook into "included" (has a
    matching header row - same detection used by parse_statement_file, so
    the frontend can offer a dropdown of real choices instead of the user
    guessing a tab name after a failed upload) and "ignored" (everything
    else, e.g. an Index/Dashboard tab, or one with a differently-shaped
    header) - so the frontend can also show what got skipped and why. CSV
    files have no sheets, so both lists are empty for those.
    """
    if filename.lower().endswith(".csv"):
        return SheetCandidates(included=[], ignored=[])

    sheets = pd.read_excel(io.BytesIO(content), dtype=str, header=None, sheet_name=None)
    included = [name for name, raw in sheets.items() if _find_header_row(raw) is not None]
    ignored = [name for name in sheets if name not in included]
    return SheetCandidates(included=included, ignored=ignored)


def parse_statement_file(filename: str, content: bytes, sheet_name: str | None = None, sheet_names: list[str] | None = None) -> list[dict]:
    """Parse an uploaded bank statement file into the same row-shape used
    when reading from the Google Sheet (same column names), so it can feed
    the same classify/route/write pipeline unchanged.

    The uploaded file may be a plain single-sheet export (header on row 1),
    or a copy of the full multi-account workbook (one tab per bank account,
    with a summary row above the real header). Either is handled by scanning
    for the header row within each sheet, rather than assuming row 0.

    `sheet_names` lets the caller pick specific tabs to parse (multi-select
    mode); each row is tagged with the actual tab name it came from. When
    neither `sheet_name` nor `sheet_names` is given, every matching tab is
    processed together.
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
        elif sheet_names:
            frames: list[pd.DataFrame] = []
            available = list(sheets.keys())
            for requested in sheet_names:
                resolved_name = _resolve_sheet_name(requested, available)
                if resolved_name is None:
                    raise ValueError(f"Sheet '{requested}' not found in uploaded file. Available sheets: {', '.join(available)}")
                raw = sheets[resolved_name]
                header_row = _find_header_row(raw)
                if header_row is None:
                    raise ValueError(f"Sheet '{resolved_name}' is missing required columns: {', '.join(REQUIRED_COLUMNS)}")
                sheet_df = _apply_header(raw, header_row)
                sheet_df["source_sheet"] = resolved_name
                frames.append(sheet_df)
            df = pd.concat(frames, ignore_index=True)
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
            offset = 0
            for name, matched in matches.items():
                df.loc[offset:offset + len(matched) - 1, "source_sheet"] = name
                offset += len(matched)

    df = df.fillna("")
    return _drop_non_transaction_rows(df.to_dict(orient="records"))
