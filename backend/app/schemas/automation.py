from pydantic import BaseModel


class TransactionSummary(BaseModel):
    sl_no: str
    date: str
    reference: str
    description: str
    narration: str
    head: str
    destination: str
    destination_sheet: str | None = None
    source_sheet: str | None = None
    payee_name: str | None = None
    needs_review: bool
    review_reason: str | None = None


class RunResponse(BaseModel):
    run_id: str
    dry_run: bool
    total_transactions: int
    routed_deposit_withdrawal: int
    routed_receipt_payment: int
    needs_review: int
    duplicates_skipped: int
    skipped_internal_credit: int
    skipped_collection: int
    transactions: list[TransactionSummary]


class SheetNamesResponse(BaseModel):
    sheets: list[str]
    total_sheets: int
    ignored_sheets: list[str]


class GoogleSheetTabsRequest(BaseModel):
    url: str


class GoogleSheetTabsResponse(BaseModel):
    spreadsheet_id: str
    spreadsheet_title: str | None = None
    sheets: list[str]
    total_sheets: int
    ignored_sheets: list[str]
    approval_columns: list[str] = []


class GoogleSheetRunRequest(BaseModel):
    spreadsheet_id: str
    sheet_names: list[str]
    approval_columns: list[str] | None = None


class ClearedSheet(BaseModel):
    sheet: str
    tabs_cleared: list[str]


class ClearSheetResponse(BaseModel):
    target: str
    sheets_cleared: list[ClearedSheet]
