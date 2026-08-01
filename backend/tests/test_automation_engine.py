import pandas as pd
from datetime import datetime
from unittest.mock import patch

from app.services.automation_engine import (
    TransactionRowSet,
    _assign_rows,
    _build_deposit_withdrawal_rows,
    _build_receipt_payment_rows,
    _distinct_sheet_names,
    _format_amount,
    _normalize_business_unit,
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


def test_normalize_business_unit_expands_ho():
    assert _normalize_business_unit("HO") == "DWARKADHIS PROJECTS PVT. LTD-HO"
    assert _normalize_business_unit("ho") == "DWARKADHIS PROJECTS PVT. LTD-HO"
    assert _normalize_business_unit("  Ho  ") == "DWARKADHIS PROJECTS PVT. LTD-HO"


def test_normalize_business_unit_leaves_others_unchanged():
    assert _normalize_business_unit("Casa Romana") == "Casa Romana"
    assert _normalize_business_unit("Aravali Heights") == "Aravali Heights"
    assert _normalize_business_unit("") == ""


def test_distinct_sheet_names_deduplicates_and_sorts():
    bank_rows = [
        {"source_sheet": "YES IDW 0490"},
        {"source_sheet": "YES AH IDW 2457"},
        {"source_sheet": "YES IDW 0490"},
    ]
    assert _distinct_sheet_names(bank_rows) == ["YES AH IDW 2457", "YES IDW 0490"]


def test_distinct_sheet_names_empty_for_plain_sheet_rows():
    bank_rows = [{"SL#": "1"}, {"SL#": "2", "source_sheet": ""}]
    assert _distinct_sheet_names(bank_rows) == []


def _internal_txn(
    payee_name: str | None,
    matched_master_row: dict | None = None,
    bank_name: str | None = None,
    counterparty_account: str | None = None,
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
            counterparty_account=counterparty_account,
        ),
        destination="deposit_withdrawal",
    )


def test_deposit_withdrawal_uses_extracted_entity_name_as_payee():
    rows = _build_deposit_withdrawal_rows(_internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED"), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # No counterparty_account and no Master Bank Name -> Account Head falls
    # back to the extracted payee name (last resort before "Internal Transfer").
    assert ledger["Account Head"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # Parent Account Head has no equivalent concept for internal transfers.
    assert ledger["Parent Account Head"] == ""


def test_deposit_withdrawal_falls_back_to_generic_label_when_no_name_extracted():
    rows = _build_deposit_withdrawal_rows(_internal_txn(None), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "Internal Transfer"
    # No payee name, no counterparty_account, no Master Bank Name -> the
    # final fallback, literal "Internal Transfer".
    assert ledger["Account Head"] == "Internal Transfer"


def test_deposit_withdrawal_account_head_resolves_counterparty_full_account(monkeypatch):
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Bank Name": "YES BANK CR FREE 045563400002477"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _internal_txn("DWARKADHIS PROJECTS PVT LTD", counterparty_account="045563400002477")
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["LedgerDetails"][0]["Account Head"] == "YES BANK CR FREE 045563400002477"


def test_deposit_withdrawal_account_head_falls_back_to_master_bank_name_when_no_suffix_match(monkeypatch):
    from app.services import master_repository

    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Bank Name"]))

    txn = _internal_txn(
        "DWARKADHIS PROJECTS PVT LTD",
        matched_master_row={"Bank Name": "UBI ESCROW A/C CR- 497801010000168"},
        counterparty_account="999999999999999",
    )
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["LedgerDetails"][0]["Account Head"] == "UBI ESCROW A/C CR- 497801010000168"


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


def test_other_head_gets_single_master_driven_row_with_description():
    # Every head - not just Contractor/Vendor - gets an ImportTaxInfo row so
    # the tab tracks 1:1 with ReceiptPayment; other heads pull Deduction
    # Type/Description straight from the matched Master row.
    txn = _receipt_payment_txn(
        "SUNDRY CREDITORS - OTHER",
        {"Deduction Type": "Something Else", "Description": "Some description"},
    )
    rows = _build_receipt_payment_rows(txn, link_ref_code=5)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == "Something Else"
    assert tax_rows[0]["Description"] == "Some description"


def test_contractor_with_empty_description_defaults_to_tds_on_contractors():
    # A missing Master Description (and no same-category fallback match) no
    # longer suppresses the row nor leaves it blank - every Contractor
    # payment is a TDS-on-contractor deduction by definition, so it defaults
    # to that fixed text as the last resort.
    txn = _receipt_payment_txn("Contractor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=8)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 2
    assert tax_rows[0]["Deduction Type"] == "Tax deducted at source"
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    assert tax_rows[1]["Deduction Type"] == "Goods and Service Tax"
    assert tax_rows[1]["Description"] == "TDS ON CONTRACTORS"


def test_vendor_with_empty_description_still_emits_import_tax_info_row():
    txn = _receipt_payment_txn("Vendor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=9)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == "Goods and Service Tax"
    assert tax_rows[0]["Description"] == ""


def test_other_head_with_no_master_match_still_emits_blank_import_tax_info_row():
    txn = _receipt_payment_txn("Collection", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=10)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == ""
    assert tax_rows[0]["Description"] == ""


def test_contractor_with_blank_description_falls_back_to_same_category_description():
    # When the payee's own Master row has no Description, reuse the
    # Description from another Master row sharing the same Account
    # Head/Parent Account Head AND the same Deduction Type
    # (master_repository.find_description_for_head) - each row's fallback
    # lookup is keyed to its own Deduction Type so a TDS Description can't
    # leak onto the GST row or vice versa.
    txn = _receipt_payment_txn(
        "Contractor",
        {"Account Head": "NAVEEN YADAV", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
    )

    def fake_fallback(account_head, parent_account_head, deduction_type):
        return {
            "Tax deducted at source": "TDS ON CONTRACTORS",
            "Goods and Service Tax": "GST ON CONTRACTORS",
        }[deduction_type]

    with patch(
        "app.services.automation_engine.master_repository.find_description_for_head",
        side_effect=fake_fallback,
    ) as mock_fallback:
        rows = _build_receipt_payment_rows(txn, link_ref_code=11)

    assert mock_fallback.call_count == 2
    mock_fallback.assert_any_call("NAVEEN YADAV", "SUNDRY CREDITORS - CONTRACTORS", "Tax deducted at source")
    mock_fallback.assert_any_call("NAVEEN YADAV", "SUNDRY CREDITORS - CONTRACTORS", "Goods and Service Tax")
    tax_rows = rows["ImportTaxInfo"]
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    assert tax_rows[1]["Description"] == "GST ON CONTRACTORS"


def test_vendor_with_blank_description_falls_back_to_same_category_gst_description():
    txn = _receipt_payment_txn(
        "Vendor",
        {"Account Head": "SOME VENDOR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
    )

    with patch(
        "app.services.automation_engine.master_repository.find_description_for_head",
        return_value="Nil Rated-Service",
    ) as mock_fallback:
        rows = _build_receipt_payment_rows(txn, link_ref_code=12)

    mock_fallback.assert_called_once_with("SOME VENDOR", "SUNDRY CREDITORS - OTHER", "Goods and Service Tax")
    assert rows["ImportTaxInfo"][0]["Description"] == "Nil Rated-Service"


def test_other_head_with_blank_deduction_falls_back_to_paired_deduction_and_description():
    txn = _receipt_payment_txn(
        "Collection",
        {"Account Head": "SOME COLLECTOR", "Parent Account Head": "SUNDRY DEBTORS"},
    )

    with patch(
        "app.services.automation_engine.master_repository.find_deduction_for_head",
        return_value=("Tax deducted at source", "TDS ON COMMISSION"),
    ) as mock_fallback:
        rows = _build_receipt_payment_rows(txn, link_ref_code=13)

    mock_fallback.assert_called_once_with("SOME COLLECTOR", "SUNDRY DEBTORS")
    tax_rows = rows["ImportTaxInfo"]
    assert tax_rows[0]["Deduction Type"] == "Tax deducted at source"
    assert tax_rows[0]["Description"] == "TDS ON COMMISSION"


def test_collection_head_with_master_match_and_blank_description_routes_to_receipt_payment():
    # Regression for the bug where a Master match with blank Description
    # blocked ANY head in Review, not just Contractor/Vendor - Collection
    # (and any other non-Contractor/Vendor head) must route straight to
    # Receipt/Payment even when Master has no Description for the payee.
    bank_rows = [
        {
            "SL#": "165",
            "REFERENCE": "REF-COLLECTION-2",
            "DESCRIPTION": "IMPS/AMITKUMAR/XXX3986/RRN:618712584961/AXIS BANK",
            "TXN DATE": "06-Jul-2026",
            "DEBITS": "",
            "CREDITS": "5000",
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
        return_value={"Account Head": "AMITKUMAR", "Parent Account Head": "SUNDRY DEBTORS"},
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Collection"
    assert txn.destination == "receipt_payment"
    assert txn.review_reason is None


class _FakeSettings:
    RECEIPT_PAYMENT_SHEET_ID = "rp-sheet-id"
    DEPOSIT_WITHDRAWAL_SHEET_ID = "dw-sheet-id"


def test_duplicate_transaction_is_detected_directly_from_the_sheet():
    # Duplicate-detection reads the Narration column straight from the real
    # Sheet (not a dedicated Reference column - Farvision's format has no
    # room for one, and Narration already carries the bank's own
    # reference/UTR embedded in the text), not a separate ledger that could
    # drift out of sync with it.
    narration = "YIB-NEFT-YESME6203001855300-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA"
    bank_rows = [
        {
            "SL#": "336",
            "REFERENCE": "YESME6203001855300",
            "DESCRIPTION": narration,
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES Rera 0377",
        }
    ]

    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "ReceiptPayment":
            return {narration}
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


def test_narration_column_is_used_over_raw_description_when_present():
    # The source file's own pretty-formatted NARRATION column (computed by
    # the user's bank-statement spreadsheet) is what should end up on the
    # ERP row - not the raw DESCRIPTION bank code.
    pretty_narration = (
        "Payment Disbursement (Purpose: Purchase of Material for Construction) "
        "| To: S S Paints | Ref: YESME6182007460600 | BU: Aravali Heights | Head: Vendor"
    )
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME6182007460600",
            "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "NARRATION": pretty_narration,
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party", return_value=None
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    # Classification still receives the raw DESCRIPTION - not affected by
    # the completely different pretty-narration shape.
    assert txn.classification.payee_name == "S S Paints"
    assert txn.narration == pretty_narration
    rows = _build_receipt_payment_rows(txn, link_ref_code=1)
    assert rows["ReceiptPayment"][0]["Narration"] == pretty_narration


def test_narration_falls_back_to_description_when_no_narration_column():
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME6182007460600",
            "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party", return_value=None
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].narration == "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK"


def test_duplicate_detection_matches_pretty_narration_format():
    # A row already in the Sheet was written AFTER the switch to pretty
    # NARRATION - the incoming transaction's own reference digits must still
    # be found (as a substring) inside that pretty-formatted existing value.
    existing_pretty_narration = (
        "Payment Disbursement (Purpose: Purchase of Material for Construction) "
        "| To: S S Paints | Ref: YESME6182007460600 | BU: Aravali Heights | Head: Vendor"
    )
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME6182007460600",
            "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "ReceiptPayment":
            return {existing_pretty_narration}
        return set()

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ), patch("app.services.automation_engine.ledger_repository.log_audit"), patch(
        "app.services.automation_engine.classifier.master_repository.find_party", return_value=None
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].destination == "duplicate"


def test_duplicate_detection_matches_old_raw_description_format():
    # A row already in the Sheet was written BEFORE this change, in the old
    # raw-DESCRIPTION format - backward compatibility across the transition.
    existing_raw_narration = "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK"
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME6182007460600",
            "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "ReceiptPayment":
            return {existing_raw_narration}
        return set()

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ), patch("app.services.automation_engine.ledger_repository.log_audit"), patch(
        "app.services.automation_engine.classifier.master_repository.find_party", return_value=None
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].destination == "duplicate"


def test_genuinely_new_reference_is_not_flagged_duplicate():
    existing_narration = "YIB-NEFT-YESME1111111111111-Someone Else-HDFC0001977-Vendor-HDFC BANK"
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME2222222222222",
            "DESCRIPTION": "YIB-NEFT-YESME2222222222222-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "ReceiptPayment":
            return {existing_narration}
        return set()

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party", return_value=None
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].destination != "duplicate"


def test_blank_reference_never_false_positives_as_duplicate():
    # A blank/short reference must never trivially "match" every existing
    # row via an empty-substring false positive.
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "",
            "DESCRIPTION": "POS GST",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        return_value={"YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK"},
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].destination != "duplicate"


def test_process_rows_expands_ho_business_unit():
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "NEWREF002",
            "DESCRIPTION": "YIB-NEFT-NEWREF002-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "HO",
            "source_sheet": "YES IDW 0490",
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
    assert transactions[0].business_unit == "DWARKADHIS PROJECTS PVT. LTD-HO"


def test_contractor_head_with_blank_master_description_still_routes_to_receipt_payment():
    # Business rule: only Internal routes to Deposit/Withdrawal - every other
    # head (Contractor included) routes to Receipt/Payment regardless of
    # whether Master has a Description for the payee. A blank Description
    # just means no TDS/GST ImportTaxInfo rows get built, not a block.
    bank_rows = [
        {
            "SL#": "3",
            "REFERENCE": "YESME6158000706",
            "DESCRIPTION": "YIB-NEFT-YESME6158000706-Rajesh Kumar-HDFC0004201-Contractor-HDFC BANK",
            "TXN DATE": "07-Jun-2026",
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
        return_value={"Account Head": "Rajesh Kumar", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Contractor"
    assert txn.destination == "receipt_payment"
    assert txn.review_reason is None


def test_collection_head_routes_to_receipt_payment_not_review():
    # Collection routes to Receipt/Payment (business rule) and must not get
    # flagged for review. "NEFT Cr-{IFSC}-{Payee}-..." narrations don't
    # match the usual "{channel}-{mode}-{utr}-{payee}-{ifsc}-{head}-{bank}"
    # token shape, but description_parser has a dedicated credit-style
    # branch for it, so the payee name still parses out correctly.
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
    assert txn.classification.payee_name == "ROHITAS KUMAR"


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


def test_assign_rows_applies_matching_override_rule(monkeypatch):
    txn = _receipt_payment_txn("Imprest", {})
    txn.description = "YIB-NEFT-YESME61620064305-Ravi Vats-UBIN0567370-Imprest-UNION BANK OF INDIA"
    txn.source_sheet = "YES AH IDW 2457"

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active",
        lambda: [
            {
                "id": 1,
                "description_keyword": "Ravi Vats",
                "head": "Imprest",
                "sheet_name": "YES AH IDW 2457",
                "account_head": "Ravi Vats(555)",
                "is_active": True,
            }
        ],
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.destination == "receipt_payment"
    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Ravi Vats(555)"
    # Parent Account Head is untouched by Override Rules, per the explicit
    # decision to only override Account Head.
    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] != "Ravi Vats(555)"


def test_assign_rows_leaves_account_head_unchanged_when_no_rule_matches(monkeypatch):
    txn = _receipt_payment_txn("Contractor", {"Account Head": "Auto Matched Head"})
    txn.source_sheet = "YES AH IDW 2457"

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active",
        lambda: [
            {
                "id": 1,
                "description_keyword": "Ravi Vats",
                "head": "Imprest",
                "sheet_name": "YES AH IDW 2457",
                "account_head": "Ravi Vats(555)",
                "is_active": True,
            }
        ],
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Auto Matched Head"


def test_assign_rows_with_no_active_rules_leaves_todays_behavior_identical(monkeypatch):
    txn = _receipt_payment_txn("Contractor", {"Account Head": "Auto Matched Head"})
    txn.source_sheet = "YES AH IDW 2457"

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active", lambda: []
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Auto Matched Head"


def test_assign_rows_degrades_gracefully_when_rule_loading_fails(monkeypatch):
    # A Supabase hiccup (unreachable, table not created yet, ...) must not
    # block the whole automation run - it should log and continue as if
    # there were no active rules.
    txn = _receipt_payment_txn("Contractor", {"Account Head": "Auto Matched Head"})
    txn.source_sheet = "YES AH IDW 2457"

    def raise_error():
        raise RuntimeError("Supabase unreachable")

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active", raise_error
    )

    with patch("app.services.automation_engine.ledger_repository.log_audit"):
        _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.destination == "receipt_payment"
    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Auto Matched Head"
