from app.services.validation import validate_rows


def test_valid_rows_produce_no_errors():
    rows = {
        "ReceiptPayment": [
            {
                "Link Ref Code": 5,
                "Financial Year": "01-04-2026-31-03-2027",
                "Document Type": "RECEIPT / PAYMENT",
                "Document Date": "22/07/2026",
            }
        ],
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Rakiba BIBI",
                "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
                "Payment Mode": "Direct",
                "Payee Name": "Rakiba BIBI",
            }
        ],
    }

    assert validate_rows(rows) == []


def test_missing_required_field_is_reported():
    rows = {
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "",
                "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
                "Payment Mode": "Direct",
                "Payee Name": "Rakiba BIBI",
            }
        ]
    }

    errors = validate_rows(rows)

    assert len(errors) == 1
    assert "LedgerDetails.Account Head" in errors[0]


def test_deposit_withdrawal_ledger_details_does_not_require_parent_account_head():
    # Parent Account Head is intentionally left blank for internal transfers
    # (no equivalent concept).
    rows = {
        "DepositWithdrawal": [
            {
                "Link Ref Code": 5,
                "Financial Year": "01-04-2026-31-03-2027",
                "Document Type": "Deposit / Withdrawal",
                "Document Date": "22/07/2026",
            }
        ],
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "YES BANK CR FREE 045563400002477",
                "Parent Account Head": "",
                "Payment Mode": "Net Banking",
                "Payee Name": "Internal Transfer",
            }
        ],
    }

    assert validate_rows(rows) == []


def test_receipt_payment_ledger_details_does_not_require_parent_account_head():
    # Can legitimately be blank when an Override Rule's Account Head has a
    # blank Parent Account Head in Master itself - see
    # automation_engine.py's override handling in _assign_rows.
    rows = {
        "ReceiptPayment": [
            {
                "Link Ref Code": 5,
                "Financial Year": "01-04-2026-31-03-2027",
                "Document Type": "RECEIPT / PAYMENT",
                "Document Date": "22/07/2026",
            }
        ],
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Rakiba BIBI",
                "Parent Account Head": "",
                "Payment Mode": "Direct",
                "Payee Name": "Rakiba BIBI",
            }
        ],
    }

    assert validate_rows(rows) == []


def test_blank_adjustment_details_never_fails_validation():
    # automation_engine skips the AdjustmentDetails row entirely for a
    # transaction whose Parent Account Head is blank - validation must never
    # error on that empty list.
    rows = {
        "ReceiptPayment": [
            {
                "Link Ref Code": 5,
                "Financial Year": "01-04-2026-31-03-2027",
                "Document Type": "RECEIPT / PAYMENT",
                "Document Date": "22/07/2026",
            }
        ],
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Rakiba BIBI",
                "Parent Account Head": "",
                "Payment Mode": "Direct",
                "Payee Name": "Rakiba BIBI",
            }
        ],
        "AdjustmentDetails": [],
    }

    assert validate_rows(rows) == []


def test_document_no_is_not_required_despite_sheet_flag():
    rows = {
        "ReceiptPayment": [
            {
                "Link Ref Code": 5,
                "Financial Year": "01-04-2026-31-03-2027",
                "Document Type": "RECEIPT / PAYMENT",
                "Document Date": "22/07/2026",
                "Document No": "",
            }
        ]
    }

    assert validate_rows(rows) == []


def test_parent_account_head_vendor_is_invalid():
    rows = {
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Sharma Paints",
                "Parent Account Head": "Vendor",
                "Payment Mode": "Direct",
                "Payee Name": "Sharma Paints",
            }
        ],
    }

    errors = validate_rows(rows)
    assert len(errors) == 1
    assert "Parent Account Head is invalid" in errors[0]


def test_parent_account_head_vendor_is_invalid_case_and_whitespace_insensitive():
    for value in ("VENDOR", "vendor", " Vendor", "VENDOR "):
        rows = {
            "LedgerDetails": [
                {
                    "Link Ref Code": 5,
                    "Debit/Credit": "Debit",
                    "Account Head": "Sharma Paints",
                    "Parent Account Head": value,
                    "Payment Mode": "Direct",
                    "Payee Name": "Sharma Paints",
                }
            ],
        }
        errors = validate_rows(rows)
        assert len(errors) == 1, f"expected an error for {value!r}"


def test_parent_account_head_blank_is_still_valid():
    # Blank is a legitimate state (no Master match, or Master's own Parent
    # Account Head is blank) - only the literal generic label is invalid.
    rows = {
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Sharma Paints",
                "Parent Account Head": "",
                "Payment Mode": "Direct",
                "Payee Name": "Sharma Paints",
            }
        ],
    }

    assert validate_rows(rows) == []


def test_parent_account_head_real_value_containing_vendor_word_is_not_flagged():
    # Only an exact match to the generic label is invalid - a real Master
    # value that happens to contain "vendor" as a substring must not be
    # wrongly flagged.
    rows = {
        "LedgerDetails": [
            {
                "Link Ref Code": 5,
                "Debit/Credit": "Debit",
                "Account Head": "Sharma Paints",
                "Parent Account Head": "SUNDRY CREDITORS - VENDOR PAYMENTS",
                "Payment Mode": "Direct",
                "Payee Name": "Sharma Paints",
            }
        ],
    }

    assert validate_rows(rows) == []
