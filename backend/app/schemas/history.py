from datetime import datetime

from pydantic import BaseModel


class RunSummary(BaseModel):
    run_id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    dry_run: bool | None = None
    sheet_names: list[str] | None = None
    routed_receipt_payment: int | None = None
    routed_deposit_withdrawal: int | None = None
    needs_review: int | None = None
    duplicates_skipped: int | None = None
    skipped_internal_credit: int | None = None


class LogEntry(BaseModel):
    id: str
    run_id: str
    level: str
    message: str
    context: dict | None = None
    created_at: datetime


class StatsSummary(BaseModel):
    total_processed: int
    total_receipt_payment: int
    total_deposit_withdrawal: int
