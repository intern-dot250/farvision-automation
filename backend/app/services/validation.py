# Required fields per tab, curated against real observed data rather than a
# literal copy of the sheets' own Info-tab flags: "Document No" is flagged
# required there but every real example row (pre-existing and ours) leaves
# it blank, so it's treated as Farvision-assigned-on-import, not blocking.
#
# LedgerDetails.Parent Account Head is deliberately NOT required: it's
# always blank by design for DepositWithdrawal (internal transfers have no
# equivalent concept), and for ReceiptPayment it can legitimately be blank
# too when an Override Rule's Account Head has a blank Parent Account Head
# in Master itself (automation_engine.py's override handling in
# _assign_rows re-resolves it from Master exactly, rather than leaving a
# stale value from the pre-override payee) - the normal (non-overridden)
# path already guarantees a non-blank value via its own fallback chain, so
# this only actually goes blank in that specific, intentional case.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "ReceiptPayment": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "DepositWithdrawal": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "LedgerDetails": ["Link Ref Code", "Debit/Credit", "Account Head", "Payment Mode", "Payee Name"],
}


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

    return errors
