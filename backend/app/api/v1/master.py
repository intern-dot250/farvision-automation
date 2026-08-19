from fastapi import APIRouter

from app.core.constants import Tags
from app.schemas.override_rules import AccountHeadOptionsResponse, HeadOptionsResponse
from app.services import master_repository

router = APIRouter(prefix="/master", tags=[Tags.SHEETS])

# Deriving this list from Master (via classifier._derive_head, which falls
# back to a row's raw Account Head whenever Parent Account Head is blank)
# let bank-account entries and other ledger-specific noise leak into what's
# supposed to be a short, clean category list - confirmed live, e.g. "PNB
# CURRENT A/C - (...)" showing up as a selectable "Head". Replaced with the
# fixed, accounts-team-provided list below so the dropdown is guaranteed
# correct regardless of Master's data shape.
_HEAD_OPTIONS = {
    "AAKRITI", "ADISH JAIN", "AHRWA", "AMAN & CO", "AMBITION", "BANK CHARGES",
    "BONUS", "BOOKING", "BOUNCE", "BOUNCE RECOVER", "CANCELLATION", "CARD",
    "CASA DEV", "COLLECTION", "DIRECTOR REM", "EMI", "EXOTIC", "FDR",
    "FEES RATE & TAXES", "INTEREST", "INTERNAL", "LEGAL & PROFF.", "LOAN",
    "LOAN RECOVERY", "MBPL", "MEPL", "MISC", "NAVTECH", "OBOC", "OTHER COS",
    "PANDA", "PLP", "PROFESSIONAL", "RADHE", "RENTAL", "RTB", "SALARY",
    "SELF", "SKG BUILDCON", "TAX", "VENDOR", "STAMP PAPER", "VIEVEK SIR",
    "A.RENTAL", "EPF/ESI", "MLPL", "DPL", "VAT REFUND", "FULL & FINAL",
    "CAR 24", "RERA", "DD", "REIMBURSEMENT", "AUDIT FEE", "AXIS EMI",
    "SBI EMI", "ARRER SALARY", "CONTRACTOR", "COLABREATION  SEC-23",
    "REFUND", "PANTRY MATERIAL", "VECH.SALE", "IMPREST",
    "SHOP RENT RECEIVED", "INSURANCE", "WAGES", "LEI", "INVESTMENT",
    "MKT/ADVER", "EXOTIC BUILDWELL", "REPAIR & MAINT", "M TECH",
    "COMMISSION", "BG RENEWAL", "TENDER FEE", "DHBVN", "SUSPENSE",
    "OFFICE RENT", "IDW TO FREE LOAN", "FREE TO IDW LOAN", "SALARY-HO",
    "SALARY-SITE", "VENDOR - HO", "VENDOR -SITE", "REFUNDABLE SECURITY",
    "FOREIGN TRAVELLING EXP", "OFFICE EQUIPMENT", "ROC FEES",
    "PROFESSIONAL INCOME", "FREIGHT EXPENSES", "SALE", "STIPEND",
}


@router.get(
    "/heads",
    response_model=HeadOptionsResponse,
    summary="Fixed list of valid Head values, for dropdown population",
)
def get_head_options() -> HeadOptionsResponse:
    return HeadOptionsResponse(heads=sorted(_HEAD_OPTIONS))


@router.get(
    "/account-heads",
    response_model=AccountHeadOptionsResponse,
    summary="Distinct Account Head values from Master, for dropdown population",
)
def get_account_head_options() -> AccountHeadOptionsResponse:
    df = master_repository._load_master_df()
    if "Account Head" not in df.columns:
        return AccountHeadOptionsResponse(account_heads=[])
    values = df["Account Head"].astype(str).str.strip()
    return AccountHeadOptionsResponse(account_heads=sorted({v for v in values if v}))
