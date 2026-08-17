import hmac
import json

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.constants import Tags
from app.schemas.automation import (
    ClearedSheet,
    ClearSheetResponse,
    RunResponse,
    SheetNamesResponse,
    TransactionSummary,
)
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
        skipped_internal_credit=result.skipped_internal_credit,
        skipped_collection=result.skipped_collection,
        transactions=[
            TransactionSummary(
                sl_no=txn.sl_no,
                date=txn.txn_date.strftime("%d/%m/%Y"),
                reference=txn.reference,
                description=txn.description,
                narration=txn.narration,
                head=txn.classification.head,
                destination=txn.destination,
                destination_sheet=txn.destination_sheet,
                source_sheet=txn.source_sheet,
                payee_name=txn.classification.payee_name,
                needs_review=txn.destination in ("review", "error") or txn.classification.account_head_ambiguous,
                review_reason=(
                    txn.review_reason
                    or txn.classification.review_reason
                    or ("Beneficiary matches multiple Account Heads - resolve via the sheet's dropdown"
                        if txn.classification.account_head_ambiguous else None)
                ),
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
        candidates = statement_parser.list_candidate_sheets(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SheetNamesResponse(
        sheets=candidates.included,
        total_sheets=len(candidates.included) + len(candidates.ignored),
        ignored_sheets=candidates.ignored,
    )


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
    sheet_names: list[str] | None = Form(default=None),
) -> RunResponse:
    content = await file.read()

    try:
        rows = statement_parser.parse_statement_file(
            file.filename or "", content, sheet_name=sheet_name or None, sheet_names=sheet_names
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(status_code=400, detail="Uploaded file has no transaction rows")

    result = automation_engine.run_automation(dry_run=dry_run, rows=rows)
    return _build_run_response(result)


@router.post(
    "/run-upload-stream",
    summary="Same as /run-upload, but streams live progress as newline-delimited JSON instead of one final response",
)
async def run_automation_upload_stream(
    dry_run: bool = True,
    file: UploadFile = File(...),
    sheet_name: str | None = Form(default=None),
    sheet_names: list[str] | None = Form(default=None),
) -> StreamingResponse:
    content = await file.read()

    try:
        rows = statement_parser.parse_statement_file(
            file.filename or "", content, sheet_name=sheet_name or None, sheet_names=sheet_names
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(status_code=400, detail="Uploaded file has no transaction rows")

    def event_stream():
        for event in automation_engine.run_automation_stream(dry_run=dry_run, rows=rows):
            if event["type"] == "result":
                response = _build_run_response(event["result"])
                yield json.dumps({"type": "result", **response.model_dump()}) + "\n"
            else:
                yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _verify_internal_secret(x_internal_secret: str | None) -> None:
    """Guards /clear-sheet specifically (the one endpoint in this API that
    permanently deletes data) - checked against ACCESS_PASSWORD, the same
    secret already shared between the frontend and backend halves of this
    Vercel project. Only the frontend's own server-side /api/clear-sheet
    proxy route (gated by a logged-in dashboard session) knows this value;
    it's never sent to the browser. Every other endpoint in this API is
    intentionally left as-is - this is a scoped fix for the most dangerous
    action, not a full backend-auth overhaul."""
    expected = get_settings().ACCESS_PASSWORD
    if not expected or not x_internal_secret or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid internal secret")


@router.post(
    "/clear-sheet",
    response_model=ClearSheetResponse,
    summary="Permanently erase all data rows (every tab except Info, headers kept) from the Receipt/Payment sheet, the Deposit/Withdrawal sheet, or both",
)
def clear_sheet(
    target: str,
    x_internal_secret: str | None = Header(default=None),
) -> ClearSheetResponse:
    _verify_internal_secret(x_internal_secret)

    if target not in ("receipt_payment", "deposit_withdrawal", "both"):
        raise HTTPException(status_code=400, detail=f"Unknown target: {target!r}")

    try:
        results = automation_engine.clear_destination_data(target)
    except Exception as exc:
        # Surface the real failure as clean JSON - without this, an
        # unhandled exception falls through to Starlette's debug-mode HTML
        # error page (DEBUG defaults True), which the frontend can't parse,
        # so a real error (e.g. a Sheets API rate limit) shows up as an
        # opaque "status 500" with no way to tell what actually happened.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ClearSheetResponse(
        target=target,
        sheets_cleared=[ClearedSheet(**r) for r in results],
    )
