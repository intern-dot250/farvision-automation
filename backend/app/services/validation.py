# Required fields per tab, curated against real observed data rather than a
# literal copy of the sheets' own Info-tab flags: "Document No" is flagged
# required there but every real example row (pre-existing and ours) leaves
# it blank, so it's treated as Farvision-assigned-on-import, not blocking.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "ReceiptPayment": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "DepositWithdrawal": ["Link Ref Code", "Financial Year", "Document Type", "Document Date"],
    "LedgerDetails": ["Link Ref Code", "Debit/Credit", "Account Head", "Parent Account Head", "Payment Mode", "Payee Name"],
}


def validate_rows(rows: dict[str, list[dict]]) -> list[str]:
    """Check constructed rows against required fields. Returns error messages (empty = valid)."""
    errors: list[str] = []

    for tab, tab_rows in rows.items():
        required = REQUIRED_FIELDS.get(tab, [])
        for row in tab_rows:
            for field in required:
                value = row.get(field)
                if value is None or str(value).strip() == "":
                    errors.append(f"{tab}.{field} is required but empty")

    return errors
