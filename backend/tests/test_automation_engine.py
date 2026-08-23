import pandas as pd
import pytest
from datetime import datetime
from unittest.mock import patch

from app.services.automation_engine import (
    TransactionRowSet,
    _assign_rows,
    _attach_ambiguous_dropdowns,
    _attach_no_match_dropdowns,
    _NO_MATCH_ACCOUNT_HEAD_NOTE,
    _attach_unresolved_full_dropdowns,
    _UNRESOLVED_ACCOUNT_HEAD_NOTE,
    _KEYWORD_SCOPED_ACCOUNT_HEAD_NOTE,
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
    default for just that test. Also defaults sheets_client.read_all_records
    to empty - used the same way by the no-reference duplicate-detection
    fallback's (Narration, Amount) join."""
    monkeypatch.setattr("app.services.automation_engine.sheets_client.get_columns", lambda *a, **k: [])
    monkeypatch.setattr("app.services.automation_engine.sheets_client.read_all_records", lambda *a, **k: [])


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


def test_ledger_details_parent_account_head_stays_blank_when_no_master_match():
    # An unmatched Vendor/Contractor payee must NOT get the generic head
    # ("Vendor"/"Contractor") fabricated into Parent Account Head - that
    # literal string previously leaked into real LedgerDetails rows this
    # way. Parent Account Head is not a required field (validation.py), so
    # staying blank here is correct, not a validation failure - unlike
    # Account Head, which IS required and legitimately falls back below.
    txn = _receipt_payment_txn("Vendor", {})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["LedgerDetails"][0]["Parent Account Head"] == ""
    assert rows["LedgerDetails"][0]["Account Head"] == "Some Party"


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
    # payee name and no Master match - Account Head/Payee Name (both
    # required fields) must still fall back to the trusted head so
    # LedgerDetails' required fields never end up blank and silently
    # reroute the row to review. Parent Account Head is NOT required and
    # must stay blank rather than also fabricating the generic head into it
    # - that was the bug ("Vendor"/"Contractor" leaking into Parent Account
    # Head whenever nothing matched in Master).
    txn = _receipt_payment_txn("Bank Charges", {})
    txn.classification.payee_name = None
    rows = _build_receipt_payment_rows(txn, link_ref_code=5)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Account Head"] == "Bank Charges"
    assert ledger["Parent Account Head"] == ""
    assert ledger["Payee Name"] == "Bank Charges"


def test_ledger_details_parent_account_head_always_comes_from_matched_master_row():
    # Test 1 (spec): a real Master match must always win, never the trusted
    # head, even when the head string itself would look plausible.
    txn = _receipt_payment_txn("Vendor", {"Account Head": "MKA DECORATOR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=6)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Account Head"] == "MKA DECORATOR"
    assert ledger["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"


def test_ledger_details_no_master_match_prefers_payee_name_over_head_for_account_head():
    # Test 2 (spec): when nothing matched in Master, Account Head must still
    # prefer the extracted payee name over the generic trusted head - never
    # collapsing "ABC" down to "Vendor" just because Master has no entry.
    # Parent Account Head has no such fallback at all - stays blank.
    txn = _receipt_payment_txn("Vendor", {})
    txn.classification.payee_name = "ABC"
    rows = _build_receipt_payment_rows(txn, link_ref_code=7)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Account Head"] == "ABC"
    assert ledger["Parent Account Head"] == ""


def test_ledger_details_parent_account_head_prefers_master_when_present():
    txn = _receipt_payment_txn("Contractor", {"Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"})
    rows = _build_receipt_payment_rows(txn, link_ref_code=4)

    assert rows["LedgerDetails"][0]["Parent Account Head"] == "SUNDRY CREDITORS - CONTRACTORS"


def test_ledger_details_parent_account_head_prefilled_from_no_match_mapping():
    # Salary Site with zero Master candidates (classifier already resolved
    # this to a category dropdown, see classifier._HEAD_TO_PARENT_ACCOUNT_
    # HEAD) - every option in that dropdown shares the same Parent Account
    # Head, so it's safe to pre-fill directly, unlike the generic trusted
    # head string this guards against elsewhere.
    txn = _receipt_payment_txn("Salary Site", {})
    txn.classification.no_match_parent_account_head = "SALARY PAYABLE"
    txn.classification.no_match_dropdown_options = ["Ashish Gaur(157)", "Bharat Singh(406)"]
    rows = _build_receipt_payment_rows(txn, link_ref_code=8)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Parent Account Head"] == "SALARY PAYABLE"
    # AdjustmentDetails follows automatically from the non-blank Parent
    # Account Head, no special-casing needed.
    assert len(rows["AdjustmentDetails"]) == 1


def test_ledger_details_parent_account_head_no_match_mapping_never_overrides_a_real_master_match():
    # A genuine Master match must always win over the no-match mapping, even
    # if both happen to be set (shouldn't happen per classifier.py, but this
    # guards the precedence explicitly).
    txn = _receipt_payment_txn(
        "Salary Site", {"Parent Account Head": "SUNDRY CREDITORS - OTHER"}
    )
    txn.classification.no_match_parent_account_head = "SALARY PAYABLE"
    rows = _build_receipt_payment_rows(txn, link_ref_code=9)

    assert rows["LedgerDetails"][0]["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"


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


def test_no_reference_duplicate_is_detected_via_narration_and_amount():
    # "BOM 905"-style statement: REFERENCE is always "N/A", so the primary
    # reference-digit check can never fire - the (Narration, Amount)
    # fallback must catch this re-upload instead.
    narration = "Payment Disbursement (Purpose: Bank Charges) | To: LF CHG CA AC | Ref: N/A | BU: HO | Head: Bank Charges"
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "N/A",
            "DESCRIPTION": narration,
            "NARRATION": narration,
            "TXN DATE": "08-Apr-2026",
            "DEBITS": "5000",
            "CREDITS": "",
            "BUSINESS UNIT": "HO",
            "source_sheet": "BOM 905",
        }
    ]

    def fake_read_all_records(sheet_id, worksheet_name):
        if worksheet_name == "ReceiptPayment":
            return [{"Link Ref Code": "1", "Narration": narration}]
        if worksheet_name == "LedgerDetails":
            return [{"Link Ref Code": "1", "Debit Amount": "5,000", "Credit Amount": ""}]
        return []

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.sheets_client.read_all_records", side_effect=fake_read_all_records
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Bank Charges", "Parent Account Head": "BANK CHARGES"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    assert transactions[0].destination == "duplicate"


def test_no_reference_transaction_not_duplicate_when_amount_differs():
    # Same Narration, different amount - two genuinely distinct transactions
    # (e.g. the same recurring bank charge on two different dates) must NOT
    # be flagged as duplicates of each other.
    narration = "Payment Disbursement (Purpose: Bank Charges) | To: LF CHG CA AC | Ref: N/A | BU: HO | Head: Bank Charges"
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "N/A",
            "DESCRIPTION": narration,
            "NARRATION": narration,
            "TXN DATE": "08-Apr-2026",
            "DEBITS": "7500",
            "CREDITS": "",
            "BUSINESS UNIT": "HO",
            "source_sheet": "BOM 905",
        }
    ]

    def fake_read_all_records(sheet_id, worksheet_name):
        if worksheet_name == "ReceiptPayment":
            return [{"Link Ref Code": "1", "Narration": narration}]
        if worksheet_name == "LedgerDetails":
            return [{"Link Ref Code": "1", "Debit Amount": "5,000", "Credit Amount": ""}]
        return []

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.sheets_client.read_all_records", side_effect=fake_read_all_records
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Bank Charges", "Parent Account Head": "BANK CHARGES"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    assert transactions[0].destination != "duplicate"


def test_no_reference_transaction_not_duplicate_when_narration_differs():
    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "N/A",
            "DESCRIPTION": "Payment Disbursement (Purpose: Bank Charges) | To: LF CHG CA AC | Ref: N/A | BU: HO | Head: Bank Charges",
            "NARRATION": "Payment Disbursement (Purpose: Bank Charges) | To: LF CHG CA AC | Ref: N/A | BU: HO | Head: Bank Charges",
            "TXN DATE": "08-Apr-2026",
            "DEBITS": "5000",
            "CREDITS": "",
            "BUSINESS UNIT": "HO",
            "source_sheet": "BOM 905",
        }
    ]

    def fake_read_all_records(sheet_id, worksheet_name):
        if worksheet_name == "ReceiptPayment":
            return [{"Link Ref Code": "1", "Narration": "A completely different narration text"}]
        if worksheet_name == "LedgerDetails":
            return [{"Link Ref Code": "1", "Debit Amount": "5,000", "Credit Amount": ""}]
        return []

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
    ), patch(
        "app.services.automation_engine.sheets_client.read_all_records", side_effect=fake_read_all_records
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Bank Charges", "Parent Account Head": "BANK CHARGES"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    assert transactions[0].destination != "duplicate"


def test_reference_bearing_transaction_still_uses_reference_check_not_no_ref_fallback():
    # A transaction with a real reference number must keep using the
    # precise digit-match path - the (Narration, Amount) fallback should
    # never even be consulted for it.
    narration = "YIB-NEFT-YESME6203001855300-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA"
    bank_rows = [
        {
            "SL#": "1",
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
        return set()  # not present in Narration - genuinely new

    def fake_read_all_records(sheet_id, worksheet_name):
        # Deliberately matching data - if the fallback were wrongly
        # consulted for a reference-bearing row, this would not matter
        # since it must never be reached in the first place.
        if worksheet_name == "ReceiptPayment":
            return [{"Link Ref Code": "1", "Narration": narration}]
        if worksheet_name == "LedgerDetails":
            return [{"Link Ref Code": "1", "Debit Amount": "1,000", "Credit Amount": ""}]
        return []

    with patch(
        "app.services.automation_engine.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ), patch(
        "app.services.automation_engine.sheets_client.read_all_records", side_effect=fake_read_all_records
    ), patch(
        "app.services.automation_engine.classifier.master_repository.find_party_candidates",
        return_value=[{"Account Head": "Rakiba BIBI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}],
    ):
        transactions = _process_rows(bank_rows, run_id="test-run", settings=_FakeSettings())

    assert len(transactions) == 1
    assert transactions[0].destination != "duplicate"


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
    # A non-blank override Parent Account Head must leave AdjustmentDetails
    # untouched (still the normal, populated row).
    assert len(txn.rows["AdjustmentDetails"]) == 1


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
    # AdjustmentDetails was already built from the pre-override (non-blank)
    # Parent Account Head - once the override re-resolves it to blank, the
    # stale AdjustmentDetails row must be cleared too, not left stranded.
    assert txn.rows["AdjustmentDetails"] == []


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


def test_assign_rows_override_clears_leftover_ambiguity_from_original_classification(monkeypatch):
    # A transaction that was originally flagged ambiguous (multiple Master
    # candidates for the payee) but then matched an Override Rule - the
    # override is a definitive, explicit answer and must supersede the
    # leftover ambiguity, otherwise _attach_ambiguous_dropdowns() would
    # later attach a dropdown built from the ORIGINAL candidates onto a row
    # whose Account Head has since been overridden to something that may
    # not even be one of those candidates.
    from app.services import master_repository

    df = pd.DataFrame.from_records(
        [{"Company": "DPL", "Payee Name": "Ravi Vats(555)", "Account Head": "Ravi Vats(555)", "Parent Account Head": "IMPREST SITE IDW"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    txn = _receipt_payment_txn("Imprest", {"Parent Account Head": "SALARY PAYABLE"})
    txn.description = "YIB-NEFT-YESME61620064305-Ravi Vats-UBIN0567370-Imprest-UNION BANK OF INDIA"
    txn.source_sheet = "YES AH IDW 2457"
    txn.classification.account_head_ambiguous = True
    txn.classification.account_head_candidates = [
        {"Account Head": "Ravi Vats", "Parent Account Head": "SALARY PAYABLE"},
        {"Account Head": "Ravi Vats", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
    ]

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

    assert txn.rows["LedgerDetails"][0]["Account Head"] == "Ravi Vats(555)"
    assert txn.rows["LedgerDetails"][0]["Parent Account Head"] == "IMPREST SITE IDW"
    assert txn.classification.account_head_ambiguous is False
    assert txn.classification.account_head_candidates is None


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
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # Account Head is the only field ever offered as a dropdown - synthesized
    # combined labels since these candidates share identical raw Account
    # Head text (see account_head_resolver.dropdown_targets).
    mock_batch.assert_called_once()
    args = mock_batch.call_args.args
    assert args[:2] == ("rp-sheet-id", "LedgerDetails")
    flags = args[2]
    dropdown_flag = next(f for f in flags if f["column"] == "Account Head")
    assert dropdown_flag["row_number"] == 5
    assert dropdown_flag["dropdown_values"] == [
        "RAJESH KUMAR (SUNDRY CREDITORS - OTHER)", "RAJESH KUMAR (GENERAL CATEGORY-FLATS)",
    ]


def test_attach_ambiguous_dropdowns_also_attaches_a_verification_note():
    # Even though Parent Account Head auto-fills via formula for this
    # (identical-Account-Head-text) ambiguity shape, a cell note still
    # explains what happened.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    dropdown_flag = next(f for f in flags if f["column"] == "Account Head")
    assert dropdown_flag["row_number"] == 5
    assert "Parent Account Head" in dropdown_flag["note_text"]


def test_attach_ambiguous_dropdowns_writes_parent_account_head_formula_for_synthesized_labels():
    # These candidates share identical Account Head text ("RAJESH KUMAR"),
    # so the dropdown offers synthesized "Head (Parent)" labels - Parent
    # Account Head must auto-fill from whichever label gets picked, via a
    # live formula that extracts the parenthesized part.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ) as mock_letter, patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_letter.assert_called_once_with("rp-sheet-id", "LedgerDetails", "Account Head")
    flags = mock_batch.call_args.args[2]
    formula_flag = next(f for f in flags if f["column"] == "Parent Account Head")
    assert formula_flag["row_number"] == 5
    formula = formula_flag["formula"]
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
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="F"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # column_letter_for is now looked up once per batch regardless (cheap -
    # served from the already-warm header cache, no extra Sheets API call),
    # but no Parent Account Head formula should be written for this shape.
    flags = mock_batch.call_args.args[2]
    assert not any(f["column"] == "Parent Account Head" for f in flags)
    dropdown_flag = next(f for f in flags if f["column"] == "Account Head")
    assert "not updated automatically" in dropdown_flag["note_text"]


def test_attach_ambiguous_dropdowns_skips_non_ambiguous_transactions():
    txn = _receipt_payment_txn("Vendor", {"Account Head": "X", "Parent Account Head": "Y"})
    txn.rows = {"LedgerDetails": [{"Link Ref Code": 1}]}

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find, patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()
    mock_batch.assert_not_called()


def test_attach_ambiguous_dropdowns_retries_once_then_logs_error_on_final_failure():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # Retried once (2 attempts total) before giving up.
    assert mock_batch.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_ambiguous_dropdowns_recovers_on_retry():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=[RuntimeError("transient"), None],
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    assert mock_batch.call_count == 2
    mock_log.assert_not_called()


def test_attach_ambiguous_dropdowns_failure_never_raises():
    # The write to sheets has already happened by the time this step runs -
    # a dropdown-attachment failure must never propagate and break the run.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("permanent failure"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ):
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise


def test_attach_ambiguous_dropdowns_skips_when_row_not_found_and_logs_error():
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    # No rows resolved -> nothing to flag, batch call made with an empty list.
    mock_batch.assert_called_once_with("rp-sheet-id", "LedgerDetails", [])


def test_attach_ambiguous_dropdowns_survives_find_row_number_failure():
    # A transient Sheets API failure while locating the written rows (e.g. a
    # quota hiccup) must not raise out of this function - it's a cosmetic,
    # post-write step, and the docstring's "never blocking the write"
    # promise must hold even for this call, not just the retried ones below.
    txn = _ambiguous_txn(_CANDIDATES)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise

    mock_batch.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_ambiguous_dropdowns_uses_keyword_scoped_dropdown_for_category_shaped_payee():
    # "CREDITOR - AR" fuzzy-matched 2 real Master rows, but the text itself
    # is a category label ("Credit"), not a specific vendor/person - the
    # keyword-scoped dropdown should replace the narrow 2-candidate one.
    txn = _ambiguous_txn(_CANDIDATES)
    txn.classification.payee_name = "CREDITOR - AR"

    with _patched_master_repository(), _patched_sync_lookup_column(range_value="=Lookup!A2:A3") as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads (Credit)", values=_CREDIT_ACCOUNT_HEADS,
    )
    flags = mock_batch.call_args.args[2]
    account_head_flag = next(f for f in flags if f["column"] == "Account Head")
    assert account_head_flag["dropdown_range"] == "=Lookup!A2:A3"
    assert "dropdown_values" not in account_head_flag
    assert account_head_flag["note_text"] == _KEYWORD_SCOPED_ACCOUNT_HEAD_NOTE
    parent_flag = next(f for f in flags if f["column"] == "Parent Account Head")
    assert parent_flag["dropdown_values"][0] == ""
    assert "formula" not in parent_flag


def test_attach_ambiguous_dropdowns_keyword_scoping_never_writes_a_formula():
    txn = _ambiguous_txn(_CANDIDATES)
    txn.classification.payee_name = "CREDITOR - AR"

    with _patched_master_repository(), _patched_sync_lookup_column(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    assert all("formula" not in f for f in flags)


def test_attach_ambiguous_and_unresolved_dropdowns_share_lookup_column_cache():
    # A shared cache (as run_automation_stream now passes) must sync each
    # distinct (company, keywords) combo only once and never let the two
    # attach steps collide on the same Lookup tab column.
    ambiguous_txn = _ambiguous_txn(_CANDIDATES, link_ref_code=42)
    ambiguous_txn.classification.payee_name = "CREDITOR - AR"
    unresolved_txn = _unresolved_txn(link_ref_code=91, description="CREDIT ADJUSTMENT ENTRY")

    shared_cache = {}
    with _patched_master_repository(), _patched_sync_lookup_column(range_value="=Lookup!A2:A3") as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"42": 5}
    ), patch(
        "app.services.automation_engine.sheets_client.column_letter_for", return_value="B"
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_ambiguous_dropdowns([ambiguous_txn], _FakeSettings(), run_id="test-run", account_head_lookup_cache=shared_cache)

        with patch(
            "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
        ):
            _attach_unresolved_full_dropdowns(
                [unresolved_txn], _FakeSettings(), run_id="test-run", account_head_lookup_cache=shared_cache
            )

    # Both transactions matched the same "Credit" keyword for the same
    # company - the second call reuses the cached range instead of
    # re-syncing (which would otherwise overwrite column "A" a second time).
    mock_sync.assert_called_once()


def test_attach_ambiguous_dropdowns_skips_deposit_withdrawal_destination():
    # Deposit/Withdrawal's LedgerDetails Account Head is the counterparty
    # bank name, not a beneficiary head - never eligible for this dropdown.
    txn = _ambiguous_txn(_CANDIDATES, destination="deposit_withdrawal")

    with patch(
        "app.services.automation_engine.sheets_client.find_row_number"
    ) as mock_find:
        _attach_ambiguous_dropdowns([txn], _FakeSettings(), run_id="test-run")


# --- _attach_no_match_dropdowns: category dropdown for a trusted head with
# a known Parent Account Head mapping but zero extractable payee name ---


def _no_match_txn(options, destination="receipt_payment", link_ref_code=81):
    txn = _receipt_payment_txn("Salary Site", {})
    txn.classification.no_match_dropdown_options = options
    txn.classification.no_match_parent_account_head = "SALARY PAYABLE"
    txn.destination = destination
    txn.rows = {"LedgerDetails": [{"Link Ref Code": link_ref_code}]}
    return txn


_NO_MATCH_OPTIONS = ["Ashish Gaur(157)", "Bharat Singh(406)"]


def test_attach_no_match_dropdowns_calls_add_dropdown_with_master_payee_list():
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"81": 82}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_batch.assert_called_once_with(
        "rp-sheet-id", "LedgerDetails",
        [{
            "row_number": 82, "column": "Account Head",
            "dropdown_values": _NO_MATCH_OPTIONS, "note_text": _NO_MATCH_ACCOUNT_HEAD_NOTE,
        }],
    )


def test_attach_no_match_dropdowns_also_attaches_a_note():
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"81": 82}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    assert flags[0]["row_number"] == 82
    assert flags[0]["column"] == "Account Head"
    assert flags[0]["note_text"]


def test_attach_no_match_dropdowns_never_writes_a_formula():
    # Unlike the synthesized-label ambiguous case, every option shares the
    # same Parent Account Head - already written directly by
    # _build_receipt_payment_rows, no REGEXEXTRACT formula needed here.
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"81": 82}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    assert all("formula" not in f for f in flags)


def test_attach_no_match_dropdowns_skips_transactions_without_options():
    txn = _no_match_txn(None)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find, patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()
    mock_batch.assert_not_called()


def test_attach_no_match_dropdowns_skips_deposit_withdrawal_destination():
    txn = _no_match_txn(_NO_MATCH_OPTIONS, destination="deposit_withdrawal")

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_no_match_dropdowns_retries_once_then_logs_error_on_final_failure():
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"81": 82}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")

    assert mock_batch.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_no_match_dropdowns_failure_never_raises():
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"81": 82}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("boom"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ):
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise


def test_attach_no_match_dropdowns_survives_find_row_number_failure():
    txn = _no_match_txn(_NO_MATCH_OPTIONS)

    with patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_no_match_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise

    mock_batch.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


# --- _attach_unresolved_full_dropdowns: full Master-wide fallback for rows
# where nothing at all could be inferred (no payee, no candidates, no
# category mapping) - the true dead-end case neither _attach_ambiguous_
# dropdowns nor _attach_no_match_dropdowns handles ---


_ALL_ACCOUNT_HEADS = ["Ashish Gaur(157)", "Bharat Singh(406)", "Some Vendor"]
_ALL_PARENT_ACCOUNT_HEADS = ["", "SALARY PAYABLE", "SUNDRY CREDITORS - OTHER"]
_ACCOUNT_HEAD_LOOKUP_RANGE = "=Lookup!A2:A4"
_GST_ACCOUNT_HEADS = ["CGST Cash Ledger", "SGST Cash Ledger"]
_TDS_ACCOUNT_HEADS = ["194 Q TDS on Goods"]
_CREDIT_ACCOUNT_HEADS = ["CENVAT CREDIT SUSPENSE A/C", "CREDITOR - AR"]


def _unresolved_txn(destination="receipt_payment", link_ref_code=91, description=None, narration="", **overrides):
    txn = _receipt_payment_txn("Unclassified", None)
    if description is not None:
        txn.description = description
    txn.narration = narration
    txn.destination = destination
    txn.rows = {"LedgerDetails": [{"Link Ref Code": link_ref_code}]}
    for key, value in overrides.items():
        setattr(txn.classification, key, value)
    return txn


def _keyword_account_heads(keywords, company):
    matched = set()
    for keyword in keywords:
        if keyword.upper() == "GST":
            matched.update(_GST_ACCOUNT_HEADS)
        elif keyword.upper() == "TDS":
            matched.update(_TDS_ACCOUNT_HEADS)
        elif keyword.upper() == "CREDIT":
            matched.update(_CREDIT_ACCOUNT_HEADS)
    return sorted(matched)


def _patched_master_repository():
    return patch.multiple(
        "app.services.automation_engine.master_repository",
        resolve_company=lambda source_sheet: "DPL",
        list_all_account_heads=lambda company: _ALL_ACCOUNT_HEADS,
        list_all_parent_account_heads=lambda company: _ALL_PARENT_ACCOUNT_HEADS[1:],
        list_account_heads_matching_keywords=_keyword_account_heads,
    )


def _patched_sync_lookup_column(range_value=_ACCOUNT_HEAD_LOOKUP_RANGE):
    return patch(
        "app.services.automation_engine.sheets_client.sync_lookup_column", return_value=range_value
    )


def test_attach_unresolved_full_dropdowns_writes_both_columns_for_true_dead_end():
    txn = _unresolved_txn()

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads", values=_ALL_ACCOUNT_HEADS,
    )
    mock_batch.assert_called_once_with(
        "rp-sheet-id", "LedgerDetails",
        [
            {
                "row_number": 92, "column": "Account Head",
                "dropdown_range": _ACCOUNT_HEAD_LOOKUP_RANGE, "note_text": _UNRESOLVED_ACCOUNT_HEAD_NOTE,
            },
            {
                "row_number": 92, "column": "Parent Account Head",
                "dropdown_values": _ALL_PARENT_ACCOUNT_HEADS,
            },
        ],
    )


def test_attach_unresolved_full_dropdowns_syncs_lookup_tab_once_per_distinct_company():
    txn_a = _unresolved_txn(link_ref_code=91)
    txn_b = _unresolved_txn(link_ref_code=92)

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk",
        return_value={"91": 92, "92": 93},
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([txn_a, txn_b], _FakeSettings(), run_id="test-run")

    # Both transactions resolve to the same (mocked) company "DPL" - the
    # lookup tab should be synced once, not once per row.
    mock_sync.assert_called_once()


def test_attach_unresolved_full_dropdowns_scopes_to_gst_keyword_when_narration_mentions_it():
    txn = _unresolved_txn(description="GSGSTTAX 260806...TRANSFER TO...GST POOL ACCOUNT")

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads (GST)", values=_GST_ACCOUNT_HEADS,
    )


def test_attach_unresolved_full_dropdowns_scopes_to_narration_field_too():
    # The keyword hint can come from the app's own display narration even
    # when the raw bank description doesn't carry it - same reasoning as
    # classifier._extract_from_narration.
    txn = _unresolved_txn(description="SOME OPAQUE REF", narration="Purpose: TDS on Contractor")

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads (TDS)", values=_TDS_ACCOUNT_HEADS,
    )


def test_attach_unresolved_full_dropdowns_unions_multiple_matched_keywords():
    txn = _unresolved_txn(description="GST AND TDS ADJUSTMENT ENTRY")

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads (GST/TDS)",
        values=sorted(set(_GST_ACCOUNT_HEADS) | set(_TDS_ACCOUNT_HEADS)),
    )


def test_attach_unresolved_full_dropdowns_falls_back_to_full_list_when_no_keyword_matches():
    txn = _unresolved_txn(description="UNRELATED SELF TRANSFER NARRATION")

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_sync.assert_called_once_with(
        "rp-sheet-id", "Lookup", "A", header="DPL Account Heads", values=_ALL_ACCOUNT_HEADS,
    )


def test_attach_unresolved_full_dropdowns_syncs_lookup_tab_once_per_distinct_keyword_combo():
    gst_txn = _unresolved_txn(link_ref_code=91, description="GST ENTRY")
    tds_txn = _unresolved_txn(link_ref_code=92, description="TDS ENTRY")

    with _patched_master_repository(), _patched_sync_lookup_column() as mock_sync, patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk",
        return_value={"91": 92, "92": 93},
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ):
        _attach_unresolved_full_dropdowns([gst_txn, tds_txn], _FakeSettings(), run_id="test-run")

    # Different matched-keyword sets for the same company - each combo gets
    # its own sync/column, distinct from a single shared "all Account Heads"
    # sync.
    assert mock_sync.call_count == 2
    columns_used = {call.args[2] for call in mock_sync.call_args_list}
    assert columns_used == {"A", "B"}


def test_attach_unresolved_full_dropdowns_includes_blank_option_for_parent_account_head():
    txn = _unresolved_txn()

    with _patched_master_repository(), _patched_sync_lookup_column(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    parent_flag = next(f for f in flags if f["column"] == "Parent Account Head")
    assert parent_flag["dropdown_values"][0] == ""
    assert "note_text" not in parent_flag

    account_head_flag = next(f for f in flags if f["column"] == "Account Head")
    assert account_head_flag["dropdown_range"] == _ACCOUNT_HEAD_LOOKUP_RANGE
    assert "dropdown_values" not in account_head_flag
    assert account_head_flag["note_text"] == _UNRESOLVED_ACCOUNT_HEAD_NOTE


def test_attach_unresolved_full_dropdowns_never_writes_a_formula():
    txn = _unresolved_txn()

    with _patched_master_repository(), _patched_sync_lookup_column(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    flags = mock_batch.call_args.args[2]
    assert all("formula" not in f for f in flags)


def test_attach_unresolved_full_dropdowns_skips_row_when_lookup_sync_fails():
    txn = _unresolved_txn()

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.sync_lookup_column",
        side_effect=RuntimeError("Sheets API hiccup"),
    ), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_batch.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_unresolved_full_dropdowns_skips_when_already_matched():
    txn = _unresolved_txn(matched_master_row={"Account Head": "Some Vendor"})

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_unresolved_full_dropdowns_skips_ambiguous_transactions():
    txn = _unresolved_txn(account_head_ambiguous=True)

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_unresolved_full_dropdowns_skips_no_match_mapped_transactions():
    txn = _unresolved_txn(no_match_dropdown_options=["Ashish Gaur(157)"])

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_unresolved_full_dropdowns_skips_internal_transactions():
    txn = _unresolved_txn(is_internal=True)

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_unresolved_full_dropdowns_skips_deposit_withdrawal_destination():
    txn = _unresolved_txn(destination="deposit_withdrawal")

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk"
    ) as mock_find:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    mock_find.assert_not_called()


def test_attach_unresolved_full_dropdowns_retries_once_then_logs_error_on_final_failure():
    txn = _unresolved_txn()

    with _patched_master_repository(), _patched_sync_lookup_column(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")

    assert mock_batch.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_unresolved_full_dropdowns_failure_never_raises():
    txn = _unresolved_txn()

    with _patched_master_repository(), _patched_sync_lookup_column(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk", return_value={"91": 92}
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("boom"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ):
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise


def test_attach_unresolved_full_dropdowns_survives_find_row_number_failure():
    txn = _unresolved_txn()

    with _patched_master_repository(), patch(
        "app.services.automation_engine.sheets_client.find_row_numbers_bulk",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_unresolved_full_dropdowns([txn], _FakeSettings(), run_id="test-run")  # must not raise

    mock_batch.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


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


def test_write_transactions_survives_count_data_rows_failure():
    # count_data_rows is a best-effort read for a cosmetic dropdown - a
    # failure there (e.g. a transient Sheets API quota hiccup) must never
    # block the real transaction write.
    txn = _receipt_payment_txn("Contractor", {"Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"})
    txn.rows = {
        "ImportTaxInfo": [
            {"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"},
        ]
    }

    with patch(
        "app.services.automation_engine.sheets_client.append_records"
    ) as mock_append, patch(
        "app.services.automation_engine.sheets_client.count_data_rows",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log, patch(
        "app.services.automation_engine._attach_tax_info_description_dropdowns"
    ) as mock_attach:
        _write_transactions([txn], _FakeSettings(), run_id="test-run")  # must not raise

    mock_append.assert_called()  # the real data write still happened
    mock_attach.assert_not_called()  # dropdown step skipped, not attempted with a bad start row
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


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
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    # Row 0 (offset 0 -> sheet row 2) is the only TDS row - rows 1 and 2
    # (blank Deduction Type) never get a dropdown, nothing forced onto them.
    mock_batch.assert_called_once_with(
        "rp-sheet-id", "ImportTaxInfo",
        [{"row_number": 2, "column": "Description", "dropdown_values": ["TDS ON CONTRACTORS", "TDS ON RENT PAID"]}],
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
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_tax_info_description_dropdowns(rows, start_row=10, settings=_FakeSettings(), run_id="test-run")

    mock_batch.assert_called_once_with(
        "rp-sheet-id", "ImportTaxInfo",
        [{"row_number": 11, "column": "Description", "dropdown_values": ["TDS ON SALARY"]}],
    )


def test_attach_tax_info_description_dropdowns_batches_multiple_tds_rows_in_one_call():
    rows = [
        {"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"},
        {"Link Ref Code": 2, "Deduction Type": "Tax deducted at source", "Description": "Y"},
        {"Link Ref Code": 3, "Deduction Type": "", "Description": ""},
    ]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=["TDS ON SALARY"]
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    mock_batch.assert_called_once()
    flags = mock_batch.call_args.args[2]
    assert [f["row_number"] for f in flags] == [2, 3]


def test_attach_tax_info_description_dropdowns_survives_list_tds_descriptions_failure():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")  # must not raise

    mock_batch.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_tax_info_description_dropdowns_no_op_when_master_has_no_tds_descriptions():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=[]
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags"
    ) as mock_batch:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    mock_batch.assert_not_called()


def test_attach_tax_info_description_dropdowns_retries_once_then_logs_error_on_final_failure():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=["TDS ON SALARY"]
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
        side_effect=RuntimeError("Sheets API hiccup"),
    ) as mock_batch, patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        _attach_tax_info_description_dropdowns(rows, start_row=2, settings=_FakeSettings(), run_id="test-run")

    assert mock_batch.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "error"


def test_attach_tax_info_description_dropdowns_failure_never_raises():
    rows = [{"Link Ref Code": 1, "Deduction Type": "Tax deducted at source", "Description": "X"}]

    with patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=["TDS ON SALARY"]
    ), patch(
        "app.services.automation_engine.sheets_client.batch_apply_cell_flags",
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
        if columns == ["Payee Name", "Account Head", "Parent Account Head"]:
            return [("Rajesh Kumar", "RAJESH KUMAR", "SUNDRY CREDITORS - OTHER")]
        return []

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


def test_run_automation_stream_survives_attach_ambiguous_dropdowns_failure():
    # A cosmetic post-write step failing (e.g. a Sheets API quota hiccup)
    # must never prevent the stream from yielding its final result - the
    # real data write has already succeeded by the time this runs.
    from app.services import automation_engine as engine_module

    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-STREAM-1",
            "DESCRIPTION": "YIB-NEFT-REFSTREAM1-Some Vendor-SBIN0007204-Vendor-STATE BANK OF INDIA",
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
    ), patch(
        "app.services.automation_engine.ref_code.get_next_ref_code", return_value=1
    ), patch(
        "app.services.automation_engine.override_rules_repository.list_active", return_value=[]
    ), patch(
        "app.services.automation_engine.sheets_client.append_records"
    ), patch(
        "app.services.automation_engine.sheets_client.count_data_rows", return_value=0
    ), patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=[]
    ), patch(
        "app.services.automation_engine._attach_ambiguous_dropdowns",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        events = list(engine_module.run_automation_stream(dry_run=False, rows=bank_rows))  # must not raise

    assert events[-1]["type"] == "result"
    assert any(call.args[1] == "error" for call in mock_log.call_args_list)


def test_run_automation_stream_survives_attach_no_match_dropdowns_failure():
    # Same structural guarantee as _attach_ambiguous_dropdowns above, for the
    # sibling no-match category dropdown step.
    from app.services import automation_engine as engine_module

    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-STREAM-2",
            "DESCRIPTION": "YIB-NEFT-REFSTREAM2-Some Vendor-SBIN0007204-Vendor-STATE BANK OF INDIA",
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
    ), patch(
        "app.services.automation_engine.ref_code.get_next_ref_code", return_value=1
    ), patch(
        "app.services.automation_engine.override_rules_repository.list_active", return_value=[]
    ), patch(
        "app.services.automation_engine.sheets_client.append_records"
    ), patch(
        "app.services.automation_engine.sheets_client.count_data_rows", return_value=0
    ), patch(
        "app.services.automation_engine.master_repository.list_tds_descriptions", return_value=[]
    ), patch(
        "app.services.automation_engine._attach_no_match_dropdowns",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        events = list(engine_module.run_automation_stream(dry_run=False, rows=bank_rows))  # must not raise

    assert events[-1]["type"] == "result"
    assert any(call.args[1] == "error" for call in mock_log.call_args_list)


def test_run_automation_stream_yields_error_event_on_unexpected_failure():
    # The structural backstop: an exception ANYWHERE in the pipeline (not
    # just the individually-guarded post-write cosmetic steps) must still
    # end the stream on a well-formed terminal event, never propagate out
    # and abruptly close the connection.
    from app.services import automation_engine as engine_module

    bank_rows = [{"SL#": "1", "REFERENCE": "REF-1", "DESCRIPTION": "x", "TXN DATE": "22-Jul-2026", "DEBITS": "1000", "CREDITS": "", "BUSINESS UNIT": "Casa Romana"}]

    with patch(
        "app.services.automation_engine.master_repository.clear_cache",
        side_effect=RuntimeError("quota exceeded"),
    ), patch(
        "app.services.automation_engine.ledger_repository.log_audit"
    ) as mock_log:
        events = list(engine_module.run_automation_stream(dry_run=True, rows=bank_rows))  # must not raise

    assert events[-1]["type"] == "error"
    assert "quota exceeded" in events[-1]["message"]
    assert any(call.args[1] == "error" for call in mock_log.call_args_list)


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


def test_run_automation_stream_is_deterministic_for_identical_repeated_input():
    # Re-uploading the same statement must classify every transaction
    # identically both times - no hidden state (caches, mutable defaults,
    # unseeded randomness) may cause a second pass over the same input to
    # produce a different Account Head/Parent Account Head.
    from app.services import automation_engine as engine_module

    bank_rows = [
        {
            "SL#": "1",
            "REFERENCE": "REF-DETERMINISM-1",
            "DESCRIPTION": "YIB-NEFT-REFDET1-Mukesh Kumar-KVBL0004201-Contractor-KARUR VYSYA BANK",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
            "source_sheet": "YES AH IDW 2457",
        }
    ]
    master_candidates = [{"Account Head": "MUKESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}]

    def run_once():
        with patch(
            "app.services.automation_engine.sheets_client.get_column_values", return_value=set()
        ), patch(
            "app.services.automation_engine.classifier.master_repository.find_party_candidates",
            return_value=master_candidates,
        ), patch(
            "app.services.automation_engine.master_repository.clear_cache"
        ), patch(
            "app.services.automation_engine.ref_code.get_next_ref_code", return_value=1
        ), patch(
            "app.services.automation_engine.override_rules_repository.list_active", return_value=[]
        ):
            events = list(engine_module.run_automation_stream(dry_run=True, rows=bank_rows))
        return next(e for e in events if e["type"] == "result")["result"]

    first = run_once()
    second = run_once()

    assert first.routed_receipt_payment == second.routed_receipt_payment == 1
    first_ledger = first.transactions[0].rows["LedgerDetails"][0]
    second_ledger = second.transactions[0].rows["LedgerDetails"][0]
    assert first_ledger["Account Head"] == second_ledger["Account Head"] == "MUKESH KUMAR"
    assert (
        first_ledger["Parent Account Head"]
        == second_ledger["Parent Account Head"]
        == "SUNDRY CREDITORS - CONTRACTORS"
    )
