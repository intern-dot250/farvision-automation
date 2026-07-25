from fastapi import APIRouter

from app.core.config import get_settings
from app.core.constants import Tags
from app.schemas.sheets import SheetConnectionStatus, SheetsStatusResponse
from app.services import sheets_client

router = APIRouter(prefix="/sheets", tags=[Tags.SHEETS])


@router.get("/status", response_model=SheetsStatusResponse, summary="Check connectivity to all configured sheets")
def get_sheets_status() -> SheetsStatusResponse:
    settings = get_settings()

    targets = [
        ("Statement / Master", settings.STATEMENT_MASTER_SHEET_ID),
        ("Deposit / Withdrawal", settings.DEPOSIT_WITHDRAWAL_SHEET_ID),
        ("Receipt / Payment", settings.RECEIPT_PAYMENT_SHEET_ID),
    ]

    results: list[SheetConnectionStatus] = []
    for name, sheet_id in targets:
        try:
            worksheets = sheets_client.list_worksheet_titles(sheet_id)
            results.append(
                SheetConnectionStatus(
                    name=name, sheet_id=sheet_id, connected=True, worksheets=worksheets
                )
            )
        except Exception as exc:
            # Broad on purpose: this is a connectivity diagnostic endpoint that
            # must report every possible gspread/Google API failure uniformly
            # rather than letting one bad sheet crash the whole status check.
            results.append(
                SheetConnectionStatus(
                    name=name, sheet_id=sheet_id, connected=False, error=str(exc)
                )
            )

    return SheetsStatusResponse(sheets=results)
