from app.core.config import get_settings
from app.services import sheets_client

LINK_REF_CODE_COLUMN = "Link Ref Code"

# Tabs linked by Link Ref Code for each destination - mirrors the dict keys
# returned by _build_deposit_withdrawal_rows()/_build_receipt_payment_rows()
# in automation_engine.py, so this can never drift from what's actually
# written on each real run.
DESTINATION_TABS = {
    "deposit_withdrawal": ["DepositWithdrawal", "DepositWithdrawalDetails", "LedgerDetails"],
    "receipt_payment": ["ReceiptPayment", "ReceiptPaymentDetail", "LedgerDetails", "AdjustmentDetails", "ImportTaxInfo"],
}


def _sheet_id_for(destination: str) -> str:
    settings = get_settings()
    return (
        settings.DEPOSIT_WITHDRAWAL_SHEET_ID
        if destination == "deposit_withdrawal"
        else settings.RECEIPT_PAYMENT_SHEET_ID
    )


def _sort_key(code: str):
    return (0, int(code)) if code.isdigit() else (1, code)


def check_orphans(destination: str) -> dict:
    """Find Link Ref Codes that appear in some, but not all, of a
    destination's linked tabs - a sign a row was deleted from only one tab
    (e.g. manually), leaving orphaned detail/ledger rows or a transaction
    with missing detail rows.
    """
    tabs = DESTINATION_TABS[destination]
    sheet_id = _sheet_id_for(destination)

    codes_by_tab = {tab: sheets_client.get_column_values(sheet_id, tab, LINK_REF_CODE_COLUMN) for tab in tabs}
    all_codes = set().union(*codes_by_tab.values())

    orphans = []
    for code in sorted(all_codes, key=_sort_key):
        present_in = [tab for tab in tabs if code in codes_by_tab[tab]]
        missing_from = [tab for tab in tabs if code not in codes_by_tab[tab]]
        if missing_from:
            orphans.append({"link_ref_code": code, "present_in": present_in, "missing_from": missing_from})

    return {"destination": destination, "tabs_checked": tabs, "orphans": orphans}


def check_all_orphans() -> list[dict]:
    return [check_orphans(destination) for destination in DESTINATION_TABS]
