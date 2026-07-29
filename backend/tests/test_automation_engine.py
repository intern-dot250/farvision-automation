from datetime import datetime
from unittest.mock import patch

from app.services.automation_engine import (
    TransactionRowSet,
    _build_deposit_withdrawal_rows,
    _build_receipt_payment_rows,
    _format_amount,
    _process_rows,
)
from app.services.classifier import ClassificationResult


def test_format_amount_indian_grouping_under_one_lakh():
    assert _format_amount(9900) == "9,900"


def test_format_amount_indian_grouping_one_lakh():
    assert _format_amount(150000) == "1,50,000"


def test_format_amount_indian_grouping_crore():
    assert _format_amount(12345678) == "1,23,45,678"


def test_format_amount_drops_decimals():
    assert _format_amount(44840.75) == "44,841"


def test_format_amount_zero_is_blank():
    assert _format_amount(0) == ""


def test_format_amount_small_number_no_grouping():
    assert _format_amount(500) == "500"


def _internal_txn(payee_name: str | None) -> TransactionRowSet:
    return TransactionRowSet(
        sl_no="1",
        reference="",
        description="YIB-TPT-Some Entity-045563200000377",
        debit=1000.0,
        credit=0.0,
        business_unit="Casa Romana",
        txn_date=datetime(2026, 7, 8),
        classification=ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=payee_name,
            matched_master_row=None,
            needs_review=False,
        ),
        destination="deposit_withdrawal",
    )


def test_deposit_withdrawal_uses_extracted_entity_name_as_payee():
    rows = _build_deposit_withdrawal_rows(_internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED"), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # Head stays the category label regardless of the extracted name.
    assert ledger["Account Head"] == "Internal Transfer"
    assert ledger["Parent Account Head"] == "Internal Transfer"


def test_deposit_withdrawal_falls_back_to_generic_label_when_no_name_extracted():
    rows = _build_deposit_withdrawal_rows(_internal_txn(None), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "Internal Transfer"


def _receipt_payment_txn(head: str, matched_master_row: dict | None) -> TransactionRowSet:
    return TransactionRowSet(
        sl_no="1",
        reference="REF1",
        description="YIB-NEFT-REF1-Some Party-SBIN0007204-Contractor-STATE BANK OF INDIA",
        debit=1000.0,
        credit=0.0,
        business_unit="Casa Romana",
        txn_date=datetime(2026, 7, 8),
        classification=ClassificationResult(
            is_internal=False,
            head=head,
            payee_name="Some Party",
            matched_master_row=matched_master_row,
            needs_review=False,
        ),
        destination="receipt_payment",
    )


def test_contractor_head_gets_two_import_tax_info_rows():
    txn = _receipt_payment_txn("Contractor", {"Description": "TDS ON CONTRACTORS"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=7)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 2
    assert tax_rows[0]["Deduction Type"] == "Tax deducted at source"
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    assert tax_rows[1]["Deduction Type"] == "Goods and Service Tax"
    assert tax_rows[1]["Description"] == "TDS ON CONTRACTORS"
    for row in tax_rows:
        assert row["Link Ref Code"] == 7
        assert row["Detail Link Ref Code"] == 7


def test_vendor_head_gets_single_gst_import_tax_info_row():
    txn = _receipt_payment_txn("Vendor", {"Description": "Nil Rated-Service"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=3)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == "Goods and Service Tax"
    assert tax_rows[0]["Description"] == "Nil Rated-Service"


def test_receipt_payment_bank_name_comes_from_master_not_hardcoded():
    txn = _receipt_payment_txn("Contractor", {"Bank Name": "PNB CURRENT A/C - (4184002100014005)"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    assert rows["ReceiptPayment"][0]["BankName"] == "PNB CURRENT A/C - (4184002100014005)"


def test_receipt_payment_bank_name_falls_back_to_narration_when_master_has_none():
    txn = _receipt_payment_txn("Contractor", {})
    txn.classification.bank_name = "FEDERAL BANK"
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    assert rows["ReceiptPayment"][0]["BankName"] == "FEDERAL BANK"


def test_receipt_payment_bank_name_blank_when_master_and_narration_have_none():
    txn = _receipt_payment_txn("Contractor", {})
    txn.classification.bank_name = None
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    assert rows["ReceiptPayment"][0]["BankName"] == ""


def test_other_head_keeps_original_master_driven_single_row():
    txn = _receipt_payment_txn(
        "SUNDRY CREDITORS - OTHER",
        {"Deduction Type": "Something Else", "Description": "Some description"},
    )
    rows = _build_receipt_payment_rows(txn, link_ref_code=5)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == "Something Else"
    assert tax_rows[0]["Description"] == "Some description"


class _FakeSettings:
    RECEIPT_PAYMENT_SHEET_ID = "rp-sheet-id"
    DEPOSIT_WITHDRAWAL_SHEET_ID = "dw-sheet-id"


def test_duplicate_transaction_is_detected_directly_from_the_sheet():
    # Duplicate-detection reads the Reference column straight from the real
    # Sheet, not a separate ledger that could drift out of sync with it.
    bank_rows = [
        {
            "SL#": "336",
            "REFERENCE": "YESME6203001855300",
            "DESCRIPTION": "YIB-NEFT-YESME6203001855300-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
        }
    ]

    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "ReceiptPayment":
            return {"YESME6203001855300"}
        return set()

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ), patch("app.services.automation_engine.ledger_repository.log_audit"), patch(
        "app.services.automation_engine.classifier.master_repository.find_party",
        return_value={"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.destination == "duplicate"
    assert txn.destination_sheet == "receipt/payment"
    assert txn.classification.head == "Contractor"
    assert txn.classification.payee_name == "Rakiba BIBI"


def test_non_duplicate_transaction_when_reference_absent_from_both_sheets():
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "NEWREF001",
            "DESCRIPTION": "YIB-NEFT-NEWREF001-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        return_value=set(),
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party",
        return_value={"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    assert transactions[0].destination == "receipt_payment"
