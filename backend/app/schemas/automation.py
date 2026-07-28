from pydantic import BaseModel


class TransactionSummary(BaseModel):
    sl_no: str
    reference: str
    description: str
    head: str
    destination: str
    destination_sheet: str | None = None
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
    transactions: list[TransactionSummary]


class SheetNamesResponse(BaseModel):
    sheets: list[str]
