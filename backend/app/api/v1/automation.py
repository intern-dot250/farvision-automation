from fastapi import APIRouter

from app.core.constants import Tags
from app.schemas.automation import RunResponse, TransactionSummary
from app.services import automation_engine

router = APIRouter(prefix="/automation", tags=[Tags.AUTOMATION])


@router.post("/run", response_model=RunResponse, summary="Run the bank statement automation engine")
def run_automation(dry_run: bool = True) -> RunResponse:
    result = automation_engine.run_automation(dry_run=dry_run)

    return RunResponse(
        run_id=result.run_id,
        dry_run=result.dry_run,
        total_transactions=result.total_transactions,
        routed_deposit_withdrawal=result.routed_deposit_withdrawal,
        routed_receipt_payment=result.routed_receipt_payment,
        needs_review=result.needs_review,
        duplicates_skipped=result.duplicates_skipped,
        transactions=[
            TransactionSummary(
                sl_no=txn.sl_no,
                reference=txn.reference,
                description=txn.description,
                head=txn.classification.head,
                destination=txn.destination,
                payee_name=txn.classification.payee_name,
                needs_review=txn.destination in ("review", "error"),
                review_reason=txn.review_reason or txn.classification.review_reason,
            )
            for txn in result.transactions
        ],
    )
