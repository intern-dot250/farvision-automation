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
