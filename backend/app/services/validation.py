# Required fields per tab, curated against real observed data rather than a
# literal copy of the sheets' own Info-tab flags: "Document No" is flagged
# required there but every real example row (pre-existing and ours) leaves
# it blank, so it's treated as Farvision-assigned-on-import, not blocking.
#
# LedgerDetails.Parent Account Head is deliberately NOT required: it's
# always blank by design for DepositWithdrawal (internal transfers have no
# equivalent concept), and for ReceiptPayment it's legitimately blank
# whenever no Master row was matched at all, or an Override Rule's Account
# Head has a blank Parent Account Head in Master itself
# (automation_engine.py's _build_receipt_payment_rows / _assign_rows's
# override handling both derive it only from a real matched Master row,
# never fabricated from the generic trusted head - see
# _VENDOR_PARENT_ACCOUNT_HEAD check below for why that matters).
# AdjustmentDetails has no entry here - deliberately. It's optional per
# transaction: automation_engine._build_receipt_payment_rows skips writing an
# AdjustmentDetails row at all when the transaction's Parent Account Head is
# blank, so there's nothing to require, and this must stay true for the skip
# to never trigger an import error.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "ReceiptPayment": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "DepositWithdrawal": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "LedgerDetails": ["Link Ref Code", "Debit/Credit", "Account Head", "Payment Mode", "Payee Name"],
}

# "Vendor" (or any casing/whitespace variant of it) is a generic
# classification label, never a real Master Parent Account Head value - if
# this literal string ever reaches LedgerDetails.Parent Account Head, it
# means a fallback fabricated it instead of deriving it from a real Master
# row (the exact bug this check exists to catch as a safety net, on top of
# the code-level fix in automation_engine.py that should make it
# structurally impossible to produce in the first place).
_INVALID_PARENT_ACCOUNT_HEAD_VALUES = {"VENDOR"}


def validate_rows(rows: dict[str, list[dict]]) -> list[str]:
    """Check constructed rows against required fields. Returns error messages
    (empty = valid)."""
    errors: list[str] = []

    for tab, tab_rows in rows.items():
        required = REQUIRED_FIELDS.get(tab, [])
        for row in tab_rows:
            for field in required:
                value = row.get(field)
                if value is None or str(value).strip() == "":
                    errors.append(f"{tab}.{field} is required but empty")

            if tab == "LedgerDetails":
                parent_account_head = str(row.get("Parent Account Head", "")).strip().upper()
                if parent_account_head in _INVALID_PARENT_ACCOUNT_HEAD_VALUES:
                    errors.append(
                        f"{tab}.Parent Account Head is invalid: "
                        f"{row.get('Parent Account Head')!r} is a generic label, not a real Master value"
                    )

    return errors
