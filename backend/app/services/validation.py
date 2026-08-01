# Required fields per tab, curated against real observed data rather than a
# literal copy of the sheets' own Info-tab flags: "Document No" is flagged
# required there but every real example row (pre-existing and ours) leaves
# it blank, so it's treated as Farvision-assigned-on-import, not blocking.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "ReceiptPayment": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "DepositWithdrawal": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "LedgerDetails": ["Link Ref Code", "Debit/Credit", "Account Head", "Parent Account Head", "Payment Mode", "Payee Name"],
}

# DepositWithdrawal's LedgerDetails has no Parent Account Head concept for
# internal transfers - it's left blank by design (see
# automation_engine.py _build_deposit_withdrawal_rows). Only
# Receipt/Payment's LedgerDetails still requires it.
_DEPOSIT_WITHDRAWAL_LEDGER_DETAILS_REQUIRED_FIELDS = [
    field for field in REQUIRED_FIELDS["LedgerDetails"] if field != "Parent Account Head"
]


def validate_rows(rows: dict[str, list[dict]]) -> list[str]:
    """Check constructed rows against required fields. Returns error messages
    (empty = valid). `rows` only ever comes from one builder at a time
    (_build_receipt_payment_rows or _build_deposit_withdrawal_rows), so the
    presence of a "DepositWithdrawal" key reliably identifies which
    LedgerDetails required-field set applies."""
    errors: list[str] = []
    is_deposit_withdrawal = "DepositWithdrawal" in rows

    for tab, tab_rows in rows.items():
        if tab == "LedgerDetails" and is_deposit_withdrawal:
            required = _DEPOSIT_WITHDRAWAL_LEDGER_DETAILS_REQUIRED_FIELDS
        else:
            required = REQUIRED_FIELDS.get(tab, [])
        for row in tab_rows:
            for field in required:
                value = row.get(field)
                if value is None or str(value).strip() == "":
                    errors.append(f"{tab}.{field} is required but empty")

    return errors
