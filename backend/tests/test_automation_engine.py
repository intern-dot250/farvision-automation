import pandas as pd
import pytest
from datetime import datetime
from unittest.mock import patch

from app.services.automation_engine import (
    TransactionRowSet,
    _assign_rows,
    _attach_ambiguous_dropdowns,
    _attach_tax_info_description_dropdowns,
    _build_deposit_withdrawal_rows,
    _build_receipt_payment_rows,
    _compute_narration_from_formula,
    _distinct_sheet_names,
    _format_amount,
    _normalize_business_unit,
    _process_rows,
    _write_transactions,
    clear_destination_data,
)
from app.services.classifier import ClassificationResult


@pytest.fixture(autouse=True)
def _default_account_head_history_index(monkeypatch):
    """_process_rows_stream always reads a small Payee Name/Account
    Head/Parent Account Head history index (sheets_client.get_columns)
    before classifying any rows, the same way it already reads
    get_column_values for duplicate detection. Default this to empty so
    existing tests (which don't care about history-based disambiguation)
    don't each need their own Sheets mock for it - a test that does care can
    still patch sheets_client.get_columns itself, which overrides this
    default for just that test."""
    monkeypatch.setattr("app.services.automation_engine.sheets_client.get_columns", lambda *a, **k: [])


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
    description: str = "YIB-TPT-Some Entity-045563200000377",
) -> TransactionRowSet:
    return TransactionRowSet(
        sl_no="1",
        reference="",
        description=description,
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


def test_deposit_withdrawal_uses_extracted_entity_name_as_payee(monkeypatch):
    from app.services import master_repository

    # No real Master match for this fixture's description/counterparty -
    # isolates this test from whatever real account suffixes happen to be
    # in production Master data (the fixture description's trailing digits
    # are otherwise coincidental, not meant to reference a real account).
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Bank Name"]))
    master_repository._bank_name_suffix_index.cache_clear()

    rows = _build_deposit_withdrawal_rows(_internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED"), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # No counterparty_account and no Master Bank Name -> Account Head falls
    # back to the extracted payee name (last resort before "Internal Transfer").
    assert ledger["Account Head"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # Parent Account Head has no equivalent concept for internal transfers.
    assert ledger["Parent Account Head"] == ""


def test_deposit_withdrawal_falls_back_to_generic_label_when_no_name_extracted(monkeypatch):
    from app.services import master_repository

    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Bank Name"]))
    master_repository._bank_name_suffix_index.cache_clear()

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


def test_deposit_withdrawal_account_head_falls_back_to_description_suffix_when_no_counterparty_account(monkeypatch):
    """Reproduces the real bug: a bank-code-prefixed counterparty account
    number (e.g. Bank of Maharashtra's format) doesn't parse out as a bare
    digit string in description_parser.py, so classification.counterparty_account
    comes back None - but the raw description's last 4 characters ("9675")
    still match a real Master account, and Account Head must resolve to it
    instead of falling all the way back to a generic label (matching what
    the Narration's own "x9675" text already correctly shows)."""
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Bank Name": "BOM IDW A/C.(60090729675)"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)
    master_repository._bank_name_suffix_index.cache_clear()

    txn = _internal_txn(
        "BANK OF MAHARASHTRA",
        counterparty_account=None,
        description="YIB-TPT-BOM60090729675",
    )
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["LedgerDetails"][0]["Account Head"] == "BOM IDW A/C.(60090729675)"


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


def test_receipt_payment_ledger_details_payment_mode_is_direct():
    txn = _receipt_payment_txn("Vendor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["LedgerDetails"][0]["Payment Mode"] == "Direct"


def test_deposit_withdrawal_ledger_details_payment_mode_is_direct():
    txn = _internal_txn("DWARKADHIS PROJECTS PVT LTD")
    rows = _build_deposit_withdrawal_rows(txn, link_ref_code=1)

    assert rows["LedgerDetails"][0]["Payment Mode"] == "Direct"


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


def test_adjustment_details_row_is_generated_when_parent_account_head_present():
    txn = _receipt_payment_txn("Contractor", {"Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert len(rows["AdjustmentDetails"]) == 1
    assert rows["AdjustmentDetails"][0]["Link Ref Code"] == 4


def test_adjustment_details_row_is_skipped_when_parent_account_head_blank():
    # An Override Rule's Account Head can have a blank Parent Account Head in
    # Master itself - Adjustment Details must be left blank for that
    # transaction rather than written with a placeholder. Nothing else about
    # the transaction (ReceiptPayment, LedgerDetails, ...) is affected.
    txn = _receipt_payment_txn("", {"Parent Account Head": ""})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["AdjustmentDetails"] == []
    assert rows["LedgerDetails"][0]["Parent Account Head"] == ""
    assert len(rows["ReceiptPayment"]) == 1
    assert len(rows["LedgerDetails"]) == 1


def test_contractor_head_gets_two_import_tax_info_rows():
    txn = _receipt_payment_txn("Contractor", {"Description": "TDS ON CONTRACTORS"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=7)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 2
    assert tax_rows[0]["Deduction Type"] == "Tax deducted at source"
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    # Contractor payments have no real GST data of their own - the second
    # row stays present (keeping the 2-rows-per-Contractor shape) but blank.
    assert tax_rows[1]["Deduction Type"] == ""
    assert tax_rows[1]["Description"] == ""
    for row in tax_rows:
        assert row["Link Ref Code"] == 7
        assert row["Detail Link Ref Code"] == 7


def test_vendor_head_gets_single_blank_import_tax_info_row():
    # GST is never tracked in ImportTaxInfo - Vendor's row stays present
    # (keeping 1:1 tracking with ReceiptPayment) but both fields are blank,
    # even when Master has real GST description data.
    txn = _receipt_payment_txn("Vendor", {"Description": "Nil Rated-Service"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=3)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == ""
    assert tax_rows[0]["Description"] == ""


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
    # to that fixed text as the last resort. The second row stays blank
    # regardless, since Contractor payments have no real GST data.
    txn = _receipt_payment_txn("Contractor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=8)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 2
    assert tax_rows[0]["Deduction Type"] == "Tax deducted at source"
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    assert tax_rows[1]["Deduction Type"] == ""
    assert tax_rows[1]["Description"] == ""


def test_vendor_with_empty_description_still_emits_blank_import_tax_info_row():
    txn = _receipt_payment_txn("Vendor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=9)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == ""
    assert tax_rows[0]["Description"] == ""


def test_other_head_with_gst_deduction_type_emits_blank_import_tax_info_row():
    # Even outside Contractor/Vendor, if Master's own Deduction Type happens
    # to be "Goods and Service Tax", it's suppressed the same way - GST is
    # never written anywhere in this tab.
    txn = _receipt_payment_txn(
        "Collection",
        {"Deduction Type": "Goods and Service Tax", "Description": "Some GST description"},
    )
    rows = _build_receipt_payment_rows(txn, link_ref_code=13)

    tax_rows = rows["ImportTaxInfo"]
    assert len(tax_rows) == 1
    assert tax_rows[0]["Deduction Type"] == ""
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
    # (master_repository.find_description_for_head) - only the TDS row
    # looks anything up; the second row is always blank, since Contractor
    # payments have no real GST data of their own.
    txn = _receipt_payment_txn(
        "Contractor",
        {"Account Head": "NAVEEN YADAV", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
    )

    with patch(
        "app.services.automation_engine.master_repository.find_description_for_head",
        return_value="TDS ON CONTRACTORS",
    ) as mock_fallback:
        rows = _build_receipt_payment_rows(txn, link_ref_code=11)

    mock_fallback.assert_called_once_with(
        "NAVEEN YADAV", "SUNDRY CREDITORS - CONTRACTORS", "Tax deducted at source"
    )
    tax_rows = rows["ImportTaxInfo"]
    assert tax_rows[0]["Description"] == "TDS ON CONTRACTORS"
    assert tax_rows[1]["Deduction Type"] == ""
    assert tax_rows[1]["Description"] == ""


def test_vendor_never_resolves_a_gst_description():
    # GST is never tracked in ImportTaxInfo anymore - Vendor's row is always
    # blank, so no Description lookup (own Master row or same-category
    # fallback) should even run for it.
    txn = _receipt_payment_txn(
        "Vendor",
        {"Account Head": "SOME VENDOR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
    )

    with patch(
        "app.services.automation_engine.master_repository.find_description_for_head",
    ) as mock_fallback:
        rows = _build_receipt_payment_rows(txn, link_ref_code=12)

    mock_fallback.assert_not_called()
    assert rows["ImportTaxInfo"][0]["Deduction Type"] == ""
    assert rows["ImportTaxInfo"][0]["Description"] == ""


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


def test_collection_head_with_master_match_and_blank_description_is_skipped():
    # Collection is always skipped entirely, regardless of whether Master
    # has a match or a Description for the payee - never routed to Review,
    # never written anywhere.
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "AMITKUMAR", "Parent Account Head": "SUNDRY DEBTORS"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Collection"
    assert txn.destination == "skipped_collection"
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}],
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}],
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
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


def test_narration_computes_payment_disbursement_when_narration_column_blank():
    # No NARRATION column, but ACC REMARKS/HEAD/etc are present - the
    # formula-replication fallback should compute the pretty narration
    # itself now, rather than falling straight to raw description (real
    # example verified against C:/Users/Win11-A/Desktop/DPL Bank Statements
    # 2026-27.xlsx, YES AH IDW 2457 tab, Ref YESME6182007460600).
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YESME6182007460600",
            "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Aravali Heights",
            "HEAD": "Vendor",
            "TYPE FOR RERA IDW": "Dev- Apt",
            "ACC REMARKS": "Purchase of Material for Construction",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].narration == (
        "Payment Disbursement (Purpose: Purchase of Material for Construction) "
        "| To: S S Paints | Ref: YESME6182007460600 | BU: Aravali Heights | Head: Vendor"
    )


def test_narration_falls_back_to_description_when_computed_narration_also_empty():
    # No NARRATION column, and the row is a credit-side non-Internal
    # transaction (Collection) - _compute_narration_from_formula
    # deliberately doesn't handle that case (real narration format proven to
    # differ by tab - see YES Master 0264), so this must still fall through
    # to the raw description as the final safety net, same as before.
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "YES0N6202072677900",
            "DESCRIPTION": "NEFT Cr-ICIC0SF0002-HARI KISHAN-DWARKADHIS PROJECTS PRIVA-IN12620247274271",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "",
            "CREDITS": "70000",
            "BUSINESS UNIT": "Casa Romana",
            "HEAD": "Collection",
            "TYPE FOR RERA IDW": "Customer Collection",
            "ACC REMARKS": "Customer Collection",
            "source_sheet": "YES Master 0264",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert transactions[0].narration == "NEFT Cr-ICIC0SF0002-HARI KISHAN-DWARKADHIS PROJECTS PRIVA-IN12620247274271"


def test_compute_narration_formula_internal_debit_dash_shaped_description():
    # Real example verified against Desktop DPL Bank Statements 2026-27.xlsx,
    # YES AH IDW 2457 tab, Ref YESME6202001955300.
    row = {
        "DESCRIPTION": "YIB-TPT-DWARKADHIS PROJECTS PVT LTD IN CIRP ARAVALI HEIGHTS-internal-045563400002314",
        "REFERENCE": "YESME6202001955300",
        "DEBITS": "100000",
        "CREDITS": "",
        "BUSINESS UNIT": "Aravali Heights",
        "HEAD": "Internal",
        "TYPE FOR RERA IDW": "Internal",
        "ACC REMARKS": "N/A",
    }

    result = _compute_narration_from_formula(row, "YES AH IDW 2457")

    assert result == (
        "Internal Fund Transfer (From YES AH IDW 2457 to x2314) "
        "| Ref: YESME6202001955300 | Type: Internal | BU: Aravali Heights | Head: Internal"
    )


def test_compute_narration_formula_internal_debit_slash_shaped_description():
    # Real example verified against the same file, Ref YESI66187010622500 -
    # an IMPS/-delimited description with zero dashes still produces the
    # full "From X to Y" form in the live sheet (not gated on dash count).
    row = {
        "DESCRIPTION": "IMPS/NA/XXXX9675/RRN:618748887784/PC408545856194489/BANK OF MAHARAS/Dwarkadhis Projects Pvt Ltd/For TDSBOM9675",
        "REFERENCE": "YESI66187010622500",
        "DEBITS": "1000",
        "CREDITS": "",
        "BUSINESS UNIT": "Aravali Heights",
        "HEAD": "Internal",
        "TYPE FOR RERA IDW": "Internal",
        "ACC REMARKS": "N/A",
    }

    result = _compute_narration_from_formula(row, "YES AH IDW 2457")

    assert result == (
        "Internal Fund Transfer (From YES AH IDW 2457 to x9675) "
        "| Ref: YESI66187010622500 | Type: Internal | BU: Aravali Heights | Head: Internal"
    )


def test_compute_narration_formula_internal_credit_side():
    row = {
        "DESCRIPTION": "YIB-TPT-DWARKADHIS PROJECTS PVT LTD IN CIRP-045563200000377",
        "REFERENCE": "YESME6100000000000",
        "DEBITS": "",
        "CREDITS": "50000",
        "BUSINESS UNIT": "Casa Romana",
        "HEAD": "Internal",
        "TYPE FOR RERA IDW": "Internal",
        "ACC REMARKS": "N/A",
    }

    result = _compute_narration_from_formula(row, "YES CR FREE 2477")

    assert result == (
        "Internal Fund Transfer (From x0377 to YES CR FREE 2477) "
        "| Ref: YESME6100000000000 | Type: Internal | BU: Casa Romana | Head: Internal"
    )


def test_compute_narration_formula_payment_disbursement_debit():
    # Real example - see test_narration_computes_payment_disbursement_when_narration_column_blank.
    row = {
        "DESCRIPTION": "YIB-NEFT-YESME6182007460600-S S Paints-HDFC0001977-Vendor-HDFC BANK",
        "REFERENCE": "YESME6182007460600",
        "DEBITS": "1083",
        "CREDITS": "",
        "BUSINESS UNIT": "Aravali Heights",
        "HEAD": "Vendor",
        "TYPE FOR RERA IDW": "Dev- Apt",
        "ACC REMARKS": "Purchase of Material for Construction",
    }

    result = _compute_narration_from_formula(row, "YES AH IDW 2457")

    assert result == (
        "Payment Disbursement (Purpose: Purchase of Material for Construction) "
        "| To: S S Paints | Ref: YESME6182007460600 | BU: Aravali Heights | Head: Vendor"
    )


def test_compute_narration_formula_receipt_credit_not_implemented():
    # Deliberately unimplemented - real data proved the format isn't
    # uniform across tabs (see YES Master 0264) - returns "" so the caller
    # falls back to raw description instead of guessing.
    row = {
        "DESCRIPTION": "NEFT Cr-ICIC0SF0002-HARI KISHAN-DWARKADHIS PROJECTS PRIVA-IN12620247274271",
        "REFERENCE": "YES0N6202072677900",
        "DEBITS": "",
        "CREDITS": "70000",
        "BUSINESS UNIT": "Casa Romana",
        "HEAD": "Collection",
        "TYPE FOR RERA IDW": "Customer Collection",
        "ACC REMARKS": "Customer Collection",
    }

    result = _compute_narration_from_formula(row, "YES Master 0264")

    assert result == ""


def test_compute_narration_formula_blank_acc_remarks_returns_empty():
    # ACC REMARKS is required by the formula's own logic, but the dashboard
    # must never show a fabricated placeholder - returns "" so the caller
    # falls back to the real raw description instead.
    row = {
        "DESCRIPTION": "YIB-NEFT-YESME9999999999-Some Vendor-HDFC0001977-Vendor-HDFC BANK",
        "REFERENCE": "YESME9999999999",
        "DEBITS": "500",
        "CREDITS": "",
        "BUSINESS UNIT": "Casa Romana",
        "HEAD": "Vendor",
        "TYPE FOR RERA IDW": "Dev- Apt",
        "ACC REMARKS": "",
    }

    result = _compute_narration_from_formula(row, "YES AH IDW 2457")

    assert result == ""


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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates", return_value=[]
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}],
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Rajesh Kumar", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Contractor"
    assert txn.destination == "receipt_payment"
    assert txn.review_reason is None


def test_collection_head_is_skipped_not_routed_to_review():
    # Collection is always skipped (business rule) - never flagged for
    # review either. "NEFT Cr-{IFSC}-{Payee}-..." narrations don't match
    # the usual "{channel}-{mode}-{utr}-{payee}-{ifsc}-{head}-{bank}" token
    # shape, but description_parser has a dedicated credit-style branch for
    # it, so the payee name still parses out correctly regardless.
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Collection"
    assert txn.classification.needs_review is False
    assert txn.destination == "skipped_collection"
    assert txn.classification.payee_name == "ROHITAS KUMAR"


def test_internal_credit_leg_is_skipped_not_routed_to_deposit_withdrawal():
    # Internal transfers appear twice across the combined bank statements -
    # once as a Debit on the sending account, once as a Credit on the
    # receiving account. Only the Debit leg should be written to
    # Deposit/Withdrawal; the Credit leg must be skipped entirely so the
    # transfer isn't recorded twice.
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-INTERNAL-1",
            "DESCRIPTION": "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "",
            "CREDITS": "50000",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
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
    assert txn.classification.is_internal is True
    assert txn.destination == "skipped_internal_credit"


def test_collection_head_transaction_is_skipped_entirely():
    # Collection-headed transactions must never be written to any sheet, and
    # never routed to review either - dropped unconditionally.
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-COLLECTION-1",
            "DESCRIPTION": "Some collection narration",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "",
            "CREDITS": "50000",
            "BUSINESS UNIT": "Casa Romana",
            "HEAD": "Collection",
        }
    ]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        return_value=set(),
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.head == "Collection"
    assert txn.destination == "skipped_collection"


def test_assign_rows_skips_collection_without_building_rows(monkeypatch):
    # Same convention as skipped_internal_credit - _assign_rows only builds
    # rows for "receipt_payment"/"deposit_withdrawal" destinations, so
    # "skipped_collection" must fall through untouched.
    txn = _receipt_payment_txn("Collection", {})
    txn.destination = "skipped_collection"

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active", lambda: []
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows == {}
    assert txn.destination == "skipped_collection"


def test_internal_debit_leg_still_routes_to_deposit_withdrawal():
    bank_rows = [
        {
            "SL#": "2",
            "REFERENCE": "REF-INTERNAL-2",
            "DESCRIPTION": "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563400002477",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "50000",
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
        return_value=None,
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.classification.is_internal is True
    assert txn.destination == "deposit_withdrawal"


def test_assign_rows_skips_internal_credit_leg_without_building_rows(monkeypatch):
    # _assign_rows only builds/writes rows for "receipt_payment" and
    # "deposit_withdrawal" destinations - "skipped_internal_credit" must
    # fall through untouched (no rows built, nothing written).
    txn = _internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED")
    txn.destination = "skipped_internal_credit"

    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active", lambda: []
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows == {}
    assert txn.destination == "skipped_internal_credit"


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
    from app.services import master_repository

    # Master has its own row for the override's Account Head, with a
    # different Parent Account Head than the original (pre-override) payee
    # had - reproduces the real bug: Account Head "Ravi Vats(555)" must
    # come with Master's own "IMPREST SITE IDW" Parent Account Head, not
    # whatever the original "Ravi Vats" payee's Master row happened to have.
    df = pd.DataFrame.from_records(
        [{"Company": "DPL", "Payee Name": "Ravi Vats(555)", "Account Head": "Ravi Vats(555)", "Parent Account Head": "IMPREST SITE IDW"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Imprest", {"Parent Account Head": "SALARY PAYABLE"})
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
    # Parent Account Head is re-resolved from Master for the NEW (overridden)
    # Account Head - not left at the original payee's stale "SALARY PAYABLE".
    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] == "IMPREST SITE IDW"


def test_assign_rows_override_parent_account_head_can_be_blank(monkeypatch):
    # Reproduces the exact reported bug: Master's own row for the override's
    # Account Head has a blank Parent Account Head - that blank must win
    # over the original payee's non-blank Parent Account Head.
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Company": "DPL", "Payee Name": "IMPREST SITE IDW", "Account Head": "IMPREST SITE IDW", "Parent Account Head": ""}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Imprest", {"Parent Account Head": "SALARY PAYABLE"})
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
                "account_head": "IMPREST SITE IDW",
                "is_active": True,
            }
        ],
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows["LedgerDetails"][0]["Account Head"] == "IMPREST SITE IDW"
    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] == ""


def test_assign_rows_override_parent_account_head_unchanged_when_no_master_match(monkeypatch):
    # The override's Account Head has no Master row at all - nothing to
    # correct against, so Parent Account Head stays whatever it already was.
    from app.services import master_repository

    monkeypatch.setattr(master_repository, "_load_master_df", lambda: pd.DataFrame(columns=["Account Head", "Parent Account Head"]))

    txn = _receipt_payment_txn("Imprest", {"Parent Account Head": "SALARY PAYABLE"})
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
                "account_head": "Some Account Head Not In Master",
                "is_active": True,
            }
        ],
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Some Account Head Not In Master"
    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] == "SALARY PAYABLE"


def test_assign_rows_override_scopes_master_lookup_to_dpl_company(monkeypatch):
    # Master has the same Account Head name for both companies, with a
    # genuinely different Parent Account Head - the override fix must pick
    # DPL's row (the only company currently processed), not whichever
    # happens to come first in Master's own row order.
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [
            {"Company": "AMB", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
            {"Company": "DPL", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Imprest", {"Parent Account Head": "SALARY PAYABLE"})
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
                "account_head": "ANITA DEVI",
                "is_active": True,
            }
        ],
    )

    _assign_rows([txn], _FakeSettings(), run_id="test-run")

    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] == "SUNDRY CREDITORS - CONTRACTORS"


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


def test_assign_rows_one_bad_transaction_does_not_block_the_rest(monkeypatch):
    # Reproduces the reported production bug: one transaction's row-building
    # raises (e.g. a transient Master/Sheets error, or Supabase being
    # unreachable during audit logging) - previously this took down the
    # whole run and the streaming API response never reached its final
    # "result" event. It must instead route just that transaction to
    # "error" and let the rest of the batch complete normally.
    from app.services import automation_engine as engine_module

    bad_txn = _receipt_payment_txn("Contractor", {"Account Head": "Bad Txn Head"})
    bad_txn.sl_no = "1"
    good_txn = _receipt_payment_txn("Contractor", {"Account Head": "Good Txn Head"})
    good_txn.sl_no = "2"

    real_build = engine_module._build_receipt_payment_rows

    def fake_build(txn, link_ref_code):
        if txn.sl_no == "1":
            raise RuntimeError("Supabase unreachable")
        return real_build(txn, link_ref_code)

    monkeypatch.setattr(engine_module, "_build_receipt_payment_rows", fake_build)
    monkeypatch.setattr(
        "app.services.automation_engine.ref_code.get_next_ref_code", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "app.services.automation_engine.override_rules_repository.list_active", lambda: []
    )

    with patch("app.services.automation_engine.ledger_repository.log_audit"):
        _assign_rows([bad_txn, good_txn], _FakeSettings(), run_id="test-run")

    assert bad_txn.destination == "error"
    assert "Supabase unreachable" in bad_txn.review_reason

    assert good_txn.destination == "receipt_payment"
    assert good_txn.rows["LedgerDetails"][0]["Account Head"] == "Good Txn Head"


def test_clear_destination_data_receipt_payment_only(monkeypatch):
    from app.services import automation_engine as engine_module

    monkeypatch.setattr(engine_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        engine_module.sheets_client, "clear_all_tabs",
        lambda sheet_id: {"rp-sheet-id": ["ReceiptPayment", "LedgerDetails"]}[sheet_id],
    )
    with patch("app.services.automation_engine.ledger_repository.log_audit") as mock_log:
        results = clear_destination_data("receipt_payment")

    assert results == [{"sheet": "Receipt / Payment", "tabs_cleared": ["ReceiptPayment", "LedgerDetails"]}]
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "warning"


def test_clear_destination_data_deposit_withdrawal_only(monkeypatch):
    from app.services import automation_engine as engine_module

    monkeypatch.setattr(engine_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        engine_module.sheets_client, "clear_all_tabs",
        lambda sheet_id: {"dw-sheet-id": ["DepositWithdrawal"]}[sheet_id],
    )
    with patch("app.services.automation_engine.ledger_repository.log_audit"):
        results = clear_destination_data("deposit_withdrawal")

    assert results == [{"sheet": "Deposit / Withdrawal", "tabs_cleared": ["DepositWithdrawal"]}]


def test_clear_destination_data_both_clears_and_logs_each_sheet_separately(monkeypatch):
    from app.services import automation_engine as engine_module

    monkeypatch.setattr(engine_module, "get_settings", lambda: _FakeSettings())
    tabs_by_sheet = {
        "rp-sheet-id": ["ReceiptPayment"],
        "dw-sheet-id": ["DepositWithdrawal"],
    }
    monkeypatch.setattr(
        engine_module.sheets_client, "clear_all_tabs", lambda sheet_id: tabs_by_sheet[sheet_id]
    )
    with patch("app.services.automation_engine.ledger_repository.log_audit") as mock_log:
        results = clear_destination_data("both")

    assert results == [
        {"sheet": "Receipt / Payment", "tabs_cleared": ["ReceiptPayment"]},
        {"sheet": "Deposit / Withdrawal", "tabs_cleared": ["DepositWithdrawal"]},
    ]
    assert mock_log.call_count == 2


def test_clear_destination_data_rejects_unknown_target():
    try:
        clear_destination_data("everything")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "everything" in str(exc)


# --- _attach_ambiguous_dropdowns: the dropdown step is compulsory, not
# best-effort, for every ambiguous transaction that got written ---


def _ambiguous_txn(candidates, destination="receipt_payment", link_ref_code=42):
    txn = _receipt_payment_txn("Vendor", candidates[0])
    txn.classification.account_head_ambiguous = True
    txn.classification.account_head_candidates = candidates
    txn.destination = destination
    txn.rows = {"LedgerDetails": [{"Link Ref Code": link_ref_code}]}
    return txn


_CANDIDATES = [
    {"Account Head": "RAJESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
    {"Account Head": "RAJESH KUMAR", "Parent Account Head": "GENERAL CATEGORY-FLATS"},
]


def test_attach_ambiguous_dropdowns_calls_add_dropdown_for_every_ambiguous_transaction():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add, patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ):
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # Account Head is the only field ever offered as a dropdown - synthesized
    # combined labels since these candidates share identical raw Account
    # Head text (see account_head_resolver.dropdown_targets).
    mock_add.assert_called_once_with(
        "rp-sheet-id", "LedgerDetails", 5, "Account Head",
        ["RAJESH KUMAR (SUNDRY CREDITORS - OTHER)", "RAJESH KUMAR (GENERAL CATEGORY-FLATS)"],
    )


def test_attach_ambiguous_dropdowns_also_attaches_a_verification_note():
    # Even though Parent Account Head auto-fills via formula for this
    # (identical-Account-Head-text) ambiguity shape, a cell note still
    # explains what happened.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ), patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ) as mock_note, patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ):
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_note.assert_called_once()
    args = mock_note.call_args.args
    assert args[:4] == ("rp-sheet-id", "LedgerDetails", 5, "Account Head")
    assert "Parent Account Head" in args[4]


def test_attach_ambiguous_dropdowns_writes_parent_account_head_formula_for_synthesized_labels():
    # These candidates share identical Account Head text ("RAJESH KUMAR"),
    # so the dropdown offers synthesized "Head (Parent)" labels - Parent
    # Account Head must auto-fill from whichever label gets picked, via a
    # live formula that extracts the parenthesized part.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ), patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ) as mock_letter, patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ) as mock_formula:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_letter.assert_called_once_with("rp-sheet-id", "LedgerDetails", "Account Head")
    mock_formula.assert_called_once()
    args = mock_formula.call_args.args
    assert args[:4] == ("rp-sheet-id", "LedgerDetails", 5, "Parent Account Head")
    formula = args[4]
    assert formula.startswith("=")
    assert "B5" in formula


def test_attach_ambiguous_dropdowns_does_not_write_formula_when_account_head_text_differs():
    # When Account Head text itself distinguishes the candidates, the
    # dropdown values are the plain real Account Head strings - there's
    # nothing to extract, and the old manual-verification note still stands.
    candidates = [
        {"Account Head": "RAJESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
        {"Account Head": "RAJESH K. SHARMA", "Parent Account Head": "GENERAL CATEGORY-FLATS"},
    ]
    txn = _ambiguous_txn(candidates)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ), patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ) as mock_note, patch(
        "app.services.automation_engine.sheets_client.column_letter_for"
    ) as mock_letter, patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ) as mock_formula:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_letter.assert_not_called()
    mock_formula.assert_not_called()
    assert "not updated automatically" in mock_note.call_args.args[4]


def test_attach_ambiguous_dropdowns_skips_non_ambiguous_transactions():
    txn = _receipt_payment_txn("Vendor", {"Account Head": "X", "Parent Account Head": "Y"})
    txn.rows = {"LedgerDetails": [{"Link Ref Code": 1}]}

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number"
    ) as mock_find, patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add, patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ) as mock_note:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()
    mock_add.assert_not_called()
    mock_note.assert_not_called()


def test_attach_ambiguous_dropdowns_retries_once_then_logs_error_on_final_failure():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_add, patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # Retried once (2 attempts total) before giving up.
    assert mock_add.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_ambiguous_dropdowns_recovers_on_retry():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation",
        side_effect=[RuntimeError("transient"), None],
    ) as mock_add, patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    assert mock_add.call_count == 2
    mock_log.assert_not_called()


def test_attach_ambiguous_dropdowns_note_retries_once_then_logs_error_on_final_failure():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ), patch(
        "app.services.automation_engine.sheets_client.add_cell_note",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_note, patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    assert mock_note.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_ambiguous_dropdowns_failure_never_raises():
    # The write to sheets has already happened by the time this step runs -
    # a dropdown-attachment failure must never propagate and break the run.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=5
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation",
        side_effect=RuntimeError("permanent failure"),
    ), patch(
        "app.services.automation_engine.sheets_client.add_cell_note",
        side_effect=RuntimeError("permanent failure"),
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for",
        side_effect=RuntimeError("permanent failure"),
    ), patch(
        "app.services.automation_engine.sheets_client.set_cell_formula"
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ):
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise


def test_attach_ambiguous_dropdowns_skips_when_row_not_found_and_logs_error():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number", return_value=None
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add, patch(
        "app.services.automation_engine.sheets_client.add_cell_note"
    ) as mock_note:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_add.assert_not_called()
    mock_note.assert_not_called()


def test_attach_ambiguous_dropdowns_skips_deposit_withdrawal_destination():
    # Deposit/Withdrawal's LedgerDetails Account Head is the counterparty
    # bank name, not a beneficiary head - never eligible for this dropdown.
    txn = _ambiguous_txn(_CANDIDATES, destination="deposit_withdrawal")

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number"
    ) as mock_find:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


# --- _write_transactions: wiring to _attach_tax_info_description_dropdowns ---


def test_write_transactions_attaches_tax_info_dropdowns_with_correct_start_row():
    txn = _receipt_payment_txn("Contractor", {"Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"})
    txn.rows = {
        "ImportTaxInfo": [
            {"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"},
            {"Link Ref Code": 1, "Deduction Type": "", "Description": ""},
        ]
    }

    with patch(
        "app.services.automation_engine.sheets_client.append_records"
    ), patch(
        "app.services.automation_engine.sheets_client.count_data_rows", return_value=9
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ), patch(
        "app.services.automation_engine._attach_tax_info_description_dropdowns"
    ) as mock_attach:
        _write_transactions([txn], _FakeSettings(), run_id="test-run")

    # start_row = count_data_rows(...) + 2 = 9 + 2 = 11
    args = mock_attach.call_args.args
    assert args[0] == txn.rows["ImportTaxInfo"]
    assert args[1] == 11
    assert args[3] == "test-run"


def test_write_transactions_skips_tax_info_dropdown_step_when_no_import_tax_info_rows():
    txn = _internal_txn("DWARKADHIS PROJECTS PVT LTD")
    txn.rows = {"DepositWithdrawal": [{"Link Ref Code": 1}]}

    with patch(
        "app.services.automation_engine.sheets_client.append_records"
    ), patch(
        "app.services.automation_engine.sheets_client.count_data_rows"
    ) as mock_count, patch(
        "app.services.automation_engine._attach_tax_info_description_dropdowns"
    ) as mock_attach:
        _write_transactions([txn], _FakeSettings(), run_id="test-run")

    mock_count.assert_not_called()
    mock_attach.assert_not_called()


# --- _attach_tax_info_description_dropdowns ---


def test_attach_tax_info_description_dropdowns_attaches_only_to_tds_rows():
    rows = [
        {"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"},
        {"Link Ref Code": 1, "Deduction Type": "", "Description": ""},
        {"Link Ref Code": 2, "Deduction Type": "", "Description": ""},
    ]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions",
        return_value=["TDS ON CONTRACTORS", "TDS ON RENT PAID"],
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    # Row 0 (offset 0 -> sheet row 2) is the only TDS row - rows 1 and 2
    # (blank Deduction Type) never get a dropdown, nothing forced onto them.
    mock_add.assert_called_once_with(
        "rp-sheet-id", "ImportTaxInfo", 2, "Description", ["TDS ON CONTRACTORS", "TDS ON RENT PAID"],
    )


def test_attach_tax_info_description_dropdowns_computes_row_numbers_from_write_order():
    # A Contractor's 2 ImportTaxInfo rows share one Link Ref Code - row
    # numbers must come from position in the write order, not a Link Ref
    # Code lookup (which can't disambiguate them).
    rows = [
        {"Link Ref Code": 5, "Deduction Type": "", "Description": ""},
        {"Link Ref Code": 6, "Deduction Type": "Tax deducted at source", "Description": "TDS ON SALARY"},
        {"Link Ref Code": 6, "Deduction Type": "", "Description": ""},
    ]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions",
        return_value=["TDS ON SALARY"],
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add:
        _attach_tax_info_description_dropdowns(rows, start_row=10, settings=_FakeSettings(), run_id="test-run")

    mock_add.assert_called_once_with("rp-sheet-id", "ImportTaxInfo", 11, "Description", ["TDS ON SALARY"])


def test_attach_tax_info_description_dropdowns_no_op_when_master_has_no_tds_descriptions():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=[]
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation"
    ) as mock_add:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    mock_add.assert_not_called()


def test_attach_tax_info_description_dropdowns_retries_once_then_logs_error_on_final_failure():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=["TDS ON SALARY"]
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_add, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    assert mock_add.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_tax_info_description_dropdowns_failure_never_raises():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=["TDS ON SALARY"]
    ), patch(
        "app.services.automation_engine.sheets_client.add_dropdown_validation",
        side_effect=RuntimeError("permanent failure"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ):
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")  # must not raise


# --- History index build (threaded into classify_transaction) ---


def test_process_rows_builds_and_threads_history_index():
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-HIST-1",
            "DESCRIPTION": "YIB-NEFT-YESME999-Rajesh Kumar-SBIN0007204-STATE BANK OF INDIA",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]

    def fake_get_columns(sheet_id, worksheet_name, columns):
        return [("Rajesh Kumar", "RAJESH KUMAR", "SUNDRY CREDITORS - OTHER")]

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.sheets_client.get_columns", side_effect=fake_get_columns
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[
            {"Account Head": "RAJESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
            {"Account Head": "RAJESH KUMAR", "Parent Account Head": "GENERAL CATEGORY-FLATS"},
        ],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    txn = transactions[0]
    # History has exactly one prior write for this payee (SUNDRY CREDITORS -
    # OTHER) - resolves unambiguously via historical majority, not flagged.
    assert txn.classification.account_head_ambiguous is False
    assert txn.classification.matched_master_row["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"


# --- Master cache freshness ---


def test_run_automation_stream_clears_master_cache_before_processing():
    # A long-lived warm serverless instance must never keep serving a stale
    # in-memory Master snapshot across runs - each run has to force a fresh
    # read before classifying anything.
    from app.services import automation_engine as engine_module

    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-CACHE-1",
            "DESCRIPTION": "YIB-NEFT-REFCACHE1-Some Vendor-SBIN0007204-Vendor-STATE BANK OF INDIA",
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
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[],
    ), patch(
        "app.services.automation_engine.master_repository.clear_cache"
    ) as mock_clear, patch(
        "app.services.automation_engine.ref_code.get_next_ref_code", return_value=1
    ), patch(
        "app.services.automation_engine.override_rules_repository.list_active", return_value=[]
    ):
        list(engine_module.run_automation_stream(dry_run=True, rows=bank_rows))

    mock_clear.assert_called_once()
