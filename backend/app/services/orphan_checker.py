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

# Tabs that legitimately don't get a row for every Link Ref Code, so their
# absence alone should never be reported as an orphan - AdjustmentDetails is
# intentionally skipped for a transaction whose Parent Account Head is blank
# (see automation_engine._build_receipt_payment_rows). A code that *is*
# present in an optional tab must still exist in every required tab though -
# that direction still catches a genuine stray/orphaned row.
OPTIONAL_TABS = {
    "deposit_withdrawal": set(),
    "receipt_payment": {"AdjustmentDetails"},
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
    optional_tabs = OPTIONAL_TABS.get(destination, set())
    required_tabs = [tab for tab in tabs if tab not in optional_tabs]
    sheet_id = _sheet_id_for(destination)

    codes_by_tab = {tab: sheets_client.get_column_values(sheet_id, tab, LINK_REF_CODE_COLUMN) for tab in tabs}
    all_codes = set().union(*codes_by_tab.values())

    orphans = []
    for code in sorted(all_codes, key=_sort_key):
        present_in = [tab for tab in tabs if code in codes_by_tab[tab]]
        # A code missing from an optional tab (e.g. AdjustmentDetails, for a
        # blank-Parent-Account-Head transaction) is expected and not an
        # orphan on its own - it's only reported if it's also missing from a
        # required tab (a real gap) or if it's present in an optional tab
        # without being in every required tab (a stray/orphaned row there).
        missing_from = [tab for tab in tabs if code not in codes_by_tab[tab]]
        missing_required = [tab for tab in missing_from if tab not in optional_tabs]
        stray_optional = any(tab in codes_by_tab and code in codes_by_tab[tab] for tab in optional_tabs) and any(
            code not in codes_by_tab[tab] for tab in required_tabs
        )
        if missing_required or stray_optional:
            orphans.append({"link_ref_code": code, "present_in": present_in, "missing_from": missing_from})

    return {"destination": destination, "tabs_checked": tabs, "orphans": orphans}


def check_all_orphans() -> list[dict]:
    return [check_orphans(destination) for destination in DESTINATION_TABS]
