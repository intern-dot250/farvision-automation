from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.constants import Tags
from app.schemas.automation import RunResponse, SheetNamesResponse, TransactionSummary
from app.services import automation_engine, statement_parser

router = APIRouter(prefix="/automation", tags=[Tags.AUTOMATION])


def _build_run_response(result: automation_engine.RunResult) -> RunResponse:
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
                destination_sheet=txn.destination_sheet,
                payee_name=txn.classification.payee_name,
                needs_review=txn.destination in ("review", "error"),
                review_reason=txn.review_reason or txn.classification.review_reason,
            )
            for txn in result.transactions
        ],
    )


@router.post(
    "/sheet-names",
    response_model=SheetNamesResponse,
    summary="List the sheet/tab names in an uploaded workbook that contain transaction data",
)
async def list_sheet_names(file: UploadFile = File(...)) -> SheetNamesResponse:
    content = await file.read()
    try:
        sheets = statement_parser.list_candidate_sheets(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SheetNamesResponse(sheets=sheets)


@router.post("/run", response_model=RunResponse, summary="Run the automation engine against the configured Google Sheet")
def run_automation(dry_run: bool = True) -> RunResponse:
    result = automation_engine.run_automation(dry_run=dry_run)
    return _build_run_response(result)


@router.post(
    "/run-upload",
    response_model=RunResponse,
    summary="Run the automation engine against an uploaded bank statement file",
)
async def run_automation_upload(
    dry_run: bool = True,
    file: UploadFile = File(...),
    sheet_name: str | None = Form(default=None),
) -> RunResponse:
    content = await file.read()

    try:
        rows = statement_parser.parse_statement_file(file.filename or "", content, sheet_name=sheet_name or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(status_code=400, detail="Uploaded file has no transaction rows")

    result = automation_engine.run_automation(dry_run=dry_run, rows=rows)
    return _build_run_response(result)
