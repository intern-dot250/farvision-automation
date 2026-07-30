import pandas as pd
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


def test_format_amount_returns_real_int():
    result = _format_amount(9900)
    assert result == 9900
    assert isinstance(result, int)


def test_format_amount_large_value_stays_int():
    assert _format_amount(12345678) == 12345678


def test_format_amount_drops_decimals():
    result = _format_amount(44840.75)
    assert result == 44841
    assert isinstance(result, int)


def test_format_amount_zero_is_blank():
    assert _format_amount(0) == ""


def test_format_amount_small_number():
    assert _format_amount(500) == 500


def _internal_txn(
    payee_name: str | None,
    matched_master_row: dict | None = None,
    bank_name: str | None = None,
) -> TransactionRowSet:
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
            matched_master_row=matched_master_row,
            needs_review=False,
            bank_name=bank_name,
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


def test_deposit_withdrawal_bank_name_comes_from_master_first():
    txn = _internal_txn(
        "DWARKADHIS PROJECTS PRIVATE LIMITED",
        matched_master_row={"Bank Name": "UBI ESCROW A/C CR- 497801010000168"},
        bank_name="SOME NARRATION BANK",
    )
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["DepositWithdrawal"][0]["BankName"] == "UBI ESCROW A/C CR- 497801010000168"


def test_deposit_withdrawal_bank_name_falls_back_to_narration_when_master_has_none():
    txn = _internal_txn(
        "DWARKADHIS PROJECTS PRIVATE LIMITED", matched_master_row={}, bank_name="SOME NARRATION BANK"
    )
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["DepositWithdrawal"][0]["BankName"] == "SOME NARRATION BANK"


def test_deposit_withdrawal_bank_name_blank_when_neither_has_it():
    txn = _internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED", matched_master_row={}, bank_name=None)
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["DepositWithdrawal"][0]["BankName"] == ""


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


def test_ledger_details_parent_account_head_falls_back_to_trusted_head():
    # An unmatched Vendor/Contractor payee must still pass LedgerDetails'
    # required-field validation (Parent Account Head) so _assign_rows doesn't
    # wrongly reroute it to "review" just because Master has no entry for it.
    txn = _receipt_payment_txn("Vendor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["LedgerDetails"][0]["Parent Account Head"] == "Vendor"


def test_ledger_details_account_head_and_payee_name_fall_back_to_head_when_no_payee_name():
    # "POS GST"-style narrations (Bank Charges, etc.) have no extractable
    # payee name and no Master match - Account Head/Payee Name must still
    # fall back to the trusted head so LedgerDetails' required fields never
    # end up blank and silently reroute the row to review.
    txn = _receipt_payment_txn("Bank Charges", {})
    txn.classification.payee_name = None
    rows = _build_receipt_payment_rows(txn, link_ref_code=5)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Account Head"] == "Bank Charges"
    assert ledger["Parent Account Head"] == "Bank Charges"
    assert ledger["Payee Name"] == "Bank Charges"


def test_ledger_details_parent_account_head_prefers_master_when_present():
    txn = _receipt_payment_txn("Contractor", {"Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["LedgerDetails"][0]["Parent Account Head"] == "SUNDRY CREDITORS - CONTRACTORS"


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
            "source_sheet": "YES Rera 0377",
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
    assert txn.source_sheet == "YES Rera 0377"
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
            "source_sheet": "YES AH IDW 2457",
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
    assert transactions[0].source_sheet == "YES AH IDW 2457"


def test_collection_head_routes_to_receipt_payment_not_review():
    # "NEFT Cr-{IFSC}-{Payee}-..." narrations don't match the usual
    # "{channel}-{mode}-{utr}-{payee}-{ifsc}-{head}-{bank}" token shape, so
    # payee_name parses out as None - Collection routes to Receipt/Payment
    # (business rule) and must not get flagged for review just because the
    # narration shape is unusual; the Account Head/Payee Name fallback to
    # the trusted head covers the missing payee name.
    bank_rows = [
        {
            "SL#": "168",
            "REFERENCE": "REF-COLLECTION-1",
            "DESCRIPTION": "NEFT Cr-ICIC0SF0002-ROHITAS KUMAR-DWARKADHIS",
            "TXN DATE": "06-Jul-2026",
            "DEBITS": "",
            "CREDITS": "50000",
            "BUSINESS UNIT": "Casa Romana",
            "HEAD": "Collection",
            "source_sheet": "YES Master 0264",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        return_value=set(),
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party",
        return_value=None,
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Collection"
    assert txn.classification.needs_review is False
    assert txn.destination == "receipt_payment"


def test_receipt_payment_bank_name_uses_source_sheet_when_present(monkeypatch):
    # _resolve_own_bank_name calls find_bank_by_account_suffix → _load_master_df →
    # live Google Sheets. Stub the loader so the test stays offline.
    from app.services import master_repository

    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Bank Name"]))

    txn = _receipt_payment_txn("Contractor", {"Bank Name": "PNB CURRENT A/C -"})
    txn.source_sheet = "YES AH IDW 2457"
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    # Source sheet wins over Master and narration bank name.
    assert rows["ReceiptPayment"][0]["BankName"] == "YES AH IDW 2457"


def test_deposit_withdrawal_bank_name_uses_source_sheet_when_present(monkeypatch):
    from app.services import master_repository

    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Bank Name"]))

    txn = _internal_txn(
        "DWARKADHIS PROJECTS PRIVATE LIMITED",
        matched_master_row={"Bank Name": "UBI ESCROW A/C CR- 497801010000168"},
        bank_name="SOME NARRATION BANK",
    )
    txn.source_sheet = "YES Rera 0377"
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["DepositWithdrawal"][0]["BankName"] == "YES Rera 0377"


def test_receipt_payment_bank_name_resolves_full_form_from_master_by_suffix(monkeypatch):
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Bank Name": "YES BANK AH IDW 045563400002457"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Contractor", {"Bank Name": "PNB CURRENT A/C -"})
    txn.source_sheet = "YES AH IDW 2457"
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    # Source sheet's "2457" suffix matches Master's full-form entry.
    assert rows["ReceiptPayment"][0]["BankName"] == "YES BANK AH IDW 045563400002457"


def test_receipt_payment_bank_name_falls_back_to_source_sheet_when_no_master_suffix_match(monkeypatch):
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Bank Name": "SOME OTHER BANK 99998888"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Contractor", {"Bank Name": "PNB CURRENT A/C -"})
    txn.source_sheet = "YES AH IDW 2457"
    rows = _build_receipt_payment_rows(txn, link_ref_code=2)

    # No suffix match — keep the source sheet as-is.
    assert rows["ReceiptPayment"][0]["BankName"] == "YES AH IDW 2457"


def test_deposit_withdrawal_bank_name_resolves_full_form_from_master_by_suffix(monkeypatch):
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Bank Name": "YES BANK RERA 045563200000377"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _internal_txn(
        "DWARKADHIS PROJECTS PRIVATE LIMITED",
        matched_master_row={"Bank Name": "UBI ESCROW A/C CR- 497801010000168"},
        bank_name="SOME NARRATION BANK",
    )
    txn.source_sheet = "YES Rera 0377"
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["DepositWithdrawal"][0]["BankName"] == "YES BANK RERA 045563200000377"
